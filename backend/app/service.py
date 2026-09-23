import json
import time
from pathlib import Path
from backend.app.schema import DomainError, Shot, Evidence, PlanEdit
from backend.app.storage.repository import Repository, uid, encode
from backend.app.analysis.qwen import QwenModel
from backend.app.coverage.rules import evaluate


def public_project(p):
    return {'model_upload_consent': p.get('model_upload_consent', False)} | {k: p[k] for k in ('id', 'goal', 'target_seconds', 'conditions', 'revision',
                              'plan_version', 'confirmed', 'shots', 'created_at')}


class Service:
    def __init__(self, settings):
        self.settings = settings
        self.repo = Repository(settings.data_dir)
        self.model = QwenModel(settings)

    @property
    def model_mode(self):
        return 'simulator' if self.settings.simulation else 'qwen' if self.model.configured else 'unconfigured'

    def mutate(self, key, fingerprint, operation):
        with self.repo.transaction() as db:
            if key:
                row = db.execute('SELECT * FROM idempotency WHERE key=?', (key,)).fetchone()
                if row:
                    if row['fingerprint'] != fingerprint:
                        raise DomainError('CONFLICT', '幂等键已用于不同请求')
                    return json.loads(row['response'])
            result = operation(db)
            if key:
                db.execute('INSERT INTO idempotency VALUES (?,?,?)', (key, fingerprint, encode(result)))
            return result

    def create_project(self, db, body):
        p = body | dict(id=uid('project'), revision=0, plan_version=0, confirmed=False,
                        shots=[], clips=[], evidence=[], renditions=[], sync=None,
                        created_at=time.time(), last_processed_at=0, readiness='not_ready')
        self.repo.save(db, p, False)
        return public_project(p)

    def edit_plan(self, db, pid, body):
        p = self.repo.project(db, pid)
        self.repo.expect(p, body['expected_revision'])
        if p['confirmed']:
            raise DomainError('CONFLICT', '清单已锁定，请创建新项目修改目标')
        PlanEdit.model_validate(body)
        p['shots'] = body['shots']
        p['plan_version'] += 1
        self.repo.save(db, p)
        return public_project(p)

    def confirm_plan(self, db, pid, revision):
        p = self.repo.project(db, pid)
        self.repo.expect(p, revision)
        if not p['shots']:
            raise DomainError('INVALID_INPUT', '先生成并检查非空分镜清单', 422)
        PlanEdit(expected_revision=revision, shots=p['shots'])
        p['confirmed'] = True
        self.repo.save(db, p)
        return public_project(p)

    def queue_plan(self, db, pid, revision):
        p = self.repo.project(db, pid)
        self.repo.expect(p, revision)
        if p['confirmed']:
            raise DomainError('CONFLICT', '已确认清单不能重新生成')
        jid = self.repo.enqueue(db, 'plan', dict(revision=revision, plan_version=p['plan_version']),
                                f'plan:{pid}:{revision}', pid)
        self.repo.save(db, p)
        return self.repo.job(db, jid)

    def queue_clip(self, db, p, c):
        if not c['active'] or c['state'] != 'awaiting_ready':
            return
        payload = dict(clip_id=c['id'], generation=c['generation'], plan_version=p['plan_version'])
        jid = self.repo.enqueue(db, 'pipeline', payload,
                                f"pipeline:{p['id']}:{c['id']}:{c['generation']}:{p['plan_version']}:v1", p['id'])
        c['job_id'], c['state'] = jid, 'queued'

    def membership(self, db, pid, cid, body):
        p = self.repo.project(db, pid)
        self.repo.expect(p, body['expected_revision'])
        c = next((c for c in p['clips'] if c['id'] == cid), None)
        if not c:
            raise DomainError('NOT_FOUND', '素材不属于当前项目', 404)
        included = body['membership'] == 'included'
        if included == c['active']:
            return dict(revision=p['revision'])
        c['active'] = included
        c['generation'] += 1
        c['state'] = 'awaiting_ready' if included else 'excluded'
        c['error'] = None
        p['evidence'] = [e for e in p['evidence'] if e['clip_id'] != cid]
        if included:
            self.queue_clip(db, p, c)
        self.repo.save(db, p)
        return dict(revision=p['revision'])

    def snapshot(self, pid):
        with self.repo.transaction() as db:
            p = self.repo.project(db, pid)
            active = {c['id'] for c in p['clips'] if c['active'] and c['state'] == 'analyzed'}
            present = {r['id'] for r in p['renditions'] if Path(r['path']).is_file()}
            evidence = [e for e in p['evidence'] if e['clip_id'] in active and e['rendition_id'] in present]
            result = evaluate([Shot.model_validate(s) for s in p['shots']],
                              [Evidence.model_validate(e) for e in evidence], p['confirmed'])
            active_clips = [c for c in p['clips'] if c['active']]
            unfinished = [c for c in active_clips if c['state'] != 'analyzed']
            missing_files = any(c['rendition_id'] and c['rendition_id'] not in present for c in active_clips)
            readiness = ('checking' if unfinished or missing_files else
                         'ready' if result['coverage_complete'] else 'not_ready')
            if p['readiness'] != readiness or p.get('visible_evidence') != [e['id'] for e in evidence]:
                p['readiness'] = readiness
                p['visible_evidence'] = [e['id'] for e in evidence]
                self.repo.save(db, p)
            if result['next_action']:
                result['next_action']['project_revision'] = p['revision']
            jobs = [self.repo.job_dict(row) for row in db.execute(
                'SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 100', (pid,))]
            return dict(project=public_project(p), project_id=pid, revision=p['revision'],
                        plan_version=p['plan_version'], model_mode=self.model_mode, pipeline=dict(
                            waiting=sum(c['state'] in ('awaiting_ready', 'queued') for c in active_clips),
                            running=sum(c['state'] in ('downloading', 'preparing', 'analyzing') for c in active_clips),
                            failed=sum(c['state'] in ('failed', 'blocked_format') for c in active_clips)),
                        clips=p['clips'], evidence=evidence, **result, readiness=readiness,
                        checked_at=p['last_processed_at'] if readiness == 'ready' else None, jobs=jobs)
