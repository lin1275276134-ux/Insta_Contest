import json
import logging
import shutil
import threading
import time
from pathlib import Path
from backend.app.schema import DomainError
from backend.app.storage.repository import encode
from backend.app.analysis import simulator as model
from backend.app.media.service import prepare
from backend.app.camera.simulator import digest

log = logging.getLogger('bold.worker')


class Worker:
    def __init__(self, service):
        self.service, self.repo, self.settings = service, service.repo, service.settings
        self.stopping = threading.Event()
        self.thread = None
        self.scan_thread = None

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True, name='pipeline-worker')
        self.thread.start()

    def stop(self):
        self.stopping.set()
        for thread in (self.thread,):
            if thread:
                thread.join(timeout=5)

    def claim(self):
        with self.repo.transaction() as db:
            now = time.time()
            db.execute("UPDATE jobs SET state='queued' WHERE state='running' AND lease_until < ?", (now,))
            row = db.execute("SELECT * FROM jobs WHERE state IN ('queued','retry_wait') AND next_attempt_at <= ? ORDER BY created_at LIMIT 1", (now,)).fetchone()
            if not row:
                return None
            attempt = row['attempt'] + 1
            db.execute("UPDATE jobs SET state='running', attempt=?, lease_until=? WHERE id=?",
                       (attempt, now + self.settings.lease_seconds, row['id']))
            return dict(row) | dict(attempt=attempt, payload=json.loads(row['payload']))

    def owns(self, db, job):
        row = db.execute('SELECT state,attempt,lease_until FROM jobs WHERE id=?', (job['id'],)).fetchone()
        return row and row['state'] == 'running' and row['attempt'] == job['attempt'] and row['lease_until'] > time.time()

    def renew(self, job, done):
        while not done.wait(max(0.1, self.settings.lease_seconds / 3)):
            with self.repo.transaction() as db:
                db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND attempt=? AND state='running'",
                           (time.time() + self.settings.lease_seconds, job['id'], job['attempt']))

    def current_clip(self, db, job):
        p = self.repo.project(db, job['project_id'])
        c = next((c for c in p['clips'] if c['id'] == job['payload']['clip_id']), None)
        if (not self.owns(db, job) or not c or not c['active']
                or c['generation'] != job['payload']['generation']
                or p['plan_version'] != job['payload']['plan_version']):
            raise DomainError('STALE_REVISION', '任务输入已过期，结果不会提交', action='refresh')
        return p, c

    def phase(self, job, state):
        with self.repo.transaction() as db:
            p, c = self.current_clip(db, job)
            c['state'] = state
            self.repo.save(db, p)
            return p, c

    def pipeline(self, job):
        p, c = self.phase(job, 'downloading')
        attempt_dir = self.settings.data_dir / 'tmp' / f"{job['id']}_{job['attempt']}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        renditions = [r for r in p['renditions'] if r['clip_id'] == c['id']]
        cached = (c.get('prepared_generation') == c['generation'] and renditions
                  and {r['id'] for r in renditions} == set(c.get('prepared_rendition_ids', []))
                  and all(Path(r['path']).is_file() and digest(Path(r['path'])) == r['sha256'] for r in renditions))
        if not cached:
            if not c.get('local_source'):
                raise DomainError('INVALID_INPUT', '旧相机素材需重新从本地导入', action='import_local')
            paths = [Path(c['local_source'])]
            projection = c['projection']
            original_dir = self.settings.data_dir / 'originals' / c['id']
            original_dir.mkdir(parents=True, exist_ok=True)
            originals = []
            for i, source in enumerate(paths):
                dest = original_dir / f"{c['generation']}_{i}.media"
                temp = dest.with_suffix('.part')
                shutil.copyfile(source, temp)
                temp.replace(dest)
                originals.append(dest)
            self.phase(job, 'preparing')
            rendition_dir = self.settings.data_dir / 'renditions' / f"{c['id']}_{job['attempt']}"
            renditions = prepare(originals, projection, rendition_dir, self.settings)
            # Keep prepared media accessible even when the model is offline or unconfigured.
            with self.repo.transaction() as db:
                p, current = self.current_clip(db, job)
                current.update(rendition_id=renditions[0]['id'], duration=sum(r['duration'] for r in renditions),
                               prepared_generation=c['generation'], prepared_rendition_ids=[r['id'] for r in renditions],
                               hashes=[digest(path) for path in originals])
                p['renditions'] = [r for r in p['renditions'] if r['clip_id'] != c['id']]
                p['renditions'].extend(r | dict(clip_id=c['id']) for r in renditions)
                self.repo.save(db, p)
        self.phase(job, 'analyzing')
        records = []
        if self.settings.simulation:
            scenario = c.get('group', {}).get('scenario', 'unrelated')
            candidates = [e for r in renditions for e in model.observe(p['shots'], c['id'], r, scenario)]
        else:
            if not p.get('model_upload_consent', False):
                raise DomainError('MODEL_UPLOAD_NOT_AUTHORIZED', '请先允许本项目向千问上传分析副本',
                                  action='authorize_upload')
            candidates = []
            for rendition in renditions:
                items, record = self.service.model.observe(p['shots'], c['id'], rendition)
                candidates.extend(items)
                records.append(record)
        evidence = model.validate_evidence(candidates, p['shots'], c['id'], renditions)
        with self.repo.transaction() as db:
            p, c = self.current_clip(db, job)
            c.update(state='analyzed', rendition_id=renditions[0]['id'],
                     duration=sum(r['duration'] for r in renditions), error=None)
            p['evidence'] = [e for e in p['evidence'] if e['clip_id'] != c['id']] + evidence
            p['last_processed_at'] = time.time()
            self.repo.save(db, p)
            self.complete(db, job, dict(clip_id=c['id'],
                model='simulator-v1' if self.settings.simulation else self.settings.model_name,
                prompt_version='fixture-v1' if self.settings.simulation else self.service.model.prompt_version,
                calls=records, visual_evaluation=not self.settings.simulation))
        shutil.rmtree(attempt_dir, ignore_errors=True)

    def complete(self, db, job, result):
        if not self.owns(db, job):
            raise DomainError('STALE_REVISION', '租约已过期，旧结果不能提交')
        db.execute("UPDATE jobs SET state='succeeded', result=?, error=NULL, lease_until=NULL WHERE id=?",
                   (encode(result), job['id']))

    def execute(self, job):
        kind = job['kind']
        if kind == 'pipeline':
            self.pipeline(job)
            return
        if kind == 'plan':
            with self.repo.transaction() as db:
                p = self.repo.project(db, job['project_id'])
                if p['confirmed'] or p['plan_version'] != job['payload']['plan_version']:
                    raise DomainError('STALE_REVISION', '草稿已改变，旧规划结果不覆盖当前清单')
            if self.settings.simulation:
                shots, record = model.plan(p['goal']), dict(model='simulator-v1')
            else:
                shots, record = self.service.model.plan(p['goal'], p['conditions'], p['target_seconds'])
            with self.repo.transaction() as db:
                current = self.repo.project(db, job['project_id'])
                if (not self.owns(db, job) or current['confirmed']
                        or current['plan_version'] != job['payload']['plan_version']):
                    raise DomainError('STALE_REVISION', '规划输入已过期，结果未提交')
                current['shots'] = shots
                current['plan_version'] += 1
                self.repo.save(db, current)
                self.complete(db, job, dict(plan_version=current['plan_version'], **record))
            return
        raise DomainError('INVALID_INPUT', '未知任务类型', 422)

    def fail(self, job, error):
        with self.repo.transaction() as db:
            if not self.owns(db, job):
                return
            state = 'cancelled' if error.code == 'STALE_REVISION' else 'failed'
            retrying = error.retryable and job['attempt'] < self.settings.max_attempts
            if retrying:
                state = 'retry_wait'
            detail = dict(code=error.code, message=error.message, retryable=error.retryable,
                          action=error.action, job_id=job['id'])
            db.execute('UPDATE jobs SET state=?,error=?,lease_until=NULL,next_attempt_at=? WHERE id=?',
                       (state, encode(detail), time.time() + min(60, 5 * 2 ** (job['attempt'] - 1)), job['id']))
            if job['project_id'] and job['kind'] == 'pipeline':
                p = self.repo.project(db, job['project_id'])
                c = next((c for c in p['clips'] if c['id'] == job['payload']['clip_id']), None)
                if c and c['active'] and c['generation'] == job['payload']['generation']:
                    c['state'] = 'blocked_format' if error.code == 'MEDIA_UNSUPPORTED' else 'failed'
                    c['error'] = detail
                    self.repo.save(db, p)
        log.warning('job=%s attempt=%s code=%s', job['id'], job['attempt'], error.code)

    def step(self):
        job = self.claim()
        if not job:
            return False
        done = threading.Event()
        renewer = threading.Thread(target=self.renew, args=(job, done), daemon=True)
        renewer.start()
        try:
            self.execute(job)
        except DomainError as exc:
            self.fail(job, exc)
        except OSError as exc:
            self.fail(job, DomainError('STORAGE_FULL' if exc.errno == 28 else 'INVALID_INPUT',
                                       '本地文件处理失败，请检查素材与磁盘', retryable=False))
        except Exception:
            # Do not log exception bodies: external errors can contain credentials or URLs.
            self.fail(job, DomainError('INVALID_INPUT', '任务输入无效或处理异常，请检查运行日志'))
            log.error('job=%s unexpected processing error', job['id'])
        finally:
            done.set()
            renewer.join(timeout=1)
        return True

    def loop(self):
        while not self.stopping.is_set():
            if not self.step():
                self.stopping.wait(0.25)

    def scan_loop(self):
        failures = 0
        while not self.stopping.wait(min(60, self.settings.poll_seconds * 2 ** failures)):
            try:
                with self.repo.transaction() as db:
                    p = self.service.active_session(db)
                if p and p['sync']['state'] in ('watching', 'disconnected'):
                    self.service.reconcile(p['sync']['id'])
                failures = 0
            except DomainError as exc:
                log.warning('scan code=%s', exc.code)
                failures = min(failures + 1, 4)
            except Exception:
                log.error('scan internal error')
                failures = min(failures + 1, 4)
