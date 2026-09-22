import json
import time
from pathlib import Path
from backend.app.schema import DomainError, Shot, Evidence, PlanEdit
from backend.app.storage.repository import Repository, uid, encode
from backend.app.camera.simulator import SimulatorCamera, group_key
from backend.app.coverage.rules import evaluate


def public_project(p):
    return {k: p[k] for k in ('id', 'goal', 'target_seconds', 'conditions', 'revision',
                              'plan_version', 'confirmed', 'shots', 'created_at')}


class Service:
    def __init__(self, settings):
        self.settings = settings
        self.repo = Repository(settings.data_dir)
        self.camera = SimulatorCamera(settings)

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

    def device(self, profile='simulator'):
        simulation = self.settings.simulation and profile == 'simulator'
        return dict(id='camera_demo' if simulation else 'camera_x5',
                    connection_state='configured' if simulation else 'unverified',
                    mode='simulator' if simulation else 'unconfigured',
                    firmware='fixture-v1' if simulation else 'v1.11.6 (用户提供，未实测)',
                    capabilities={k: 'supported' if simulation else 'unknown' for k in (
                        'history_video_listing', 'listing_during_recording', 'download_during_recording',
                        'group_metadata', 'readiness_signal')},
                    evidence='本地固定输入模拟器' if simulation else 'G0/G1 尚未验证；MCU v1.2.5，硬件 523')

    def save_catalog(self, db, groups):
        catalog = dict(id=uid('catalog'), device_id='camera_demo', complete=True,
                       completed_at=time.time(), groups=groups, next_cursor=None)
        db.execute('INSERT INTO catalogs VALUES (?,?)', (catalog['id'], encode(catalog)))
        return catalog

    def catalog(self, db, sid):
        row = db.execute('SELECT document FROM catalogs WHERE id=?', (sid,)).fetchone()
        if not row:
            raise DomainError('NOT_FOUND', '目录快照不存在', 404)
        return json.loads(row[0])

    def scan(self):
        groups = self.camera.scan()
        with self.repo.transaction() as db:
            return self.save_catalog(db, groups)

    def active_session(self, db):
        return next((p for p in self.repo.projects(db) if p['sync'] and p['sync']['state'] != 'closed'), None)

    def add_clip(self, db, p, g):
        key = group_key(g)
        old = next((c for c in p['clips'] if c['group_key'] == key), None)
        if old:
            return old
        # A replacement revision invalidates previous source-version evidence.
        for c in p['clips']:
            if c.get('remote_id') == g['id'] and c.get('storage_epoch') == g['storage_epoch'] and c['active']:
                c['active'] = False
                c['generation'] += 1
        c = dict(id=uid('clip'), name=g['name'], group_key=key, remote_id=g['id'],
                 storage_epoch=g['storage_epoch'], group=g, state='awaiting_ready', active=True,
                 generation=1, rendition_id=None, duration=None, error=None, job_id=None)
        p['clips'].append(c)
        return c

    def queue_clip(self, db, p, c):
        if not c['active'] or c['state'] != 'awaiting_ready':
            return
        g = c.get('group')
        if g and (not g['closed'] or not g['complete']):
            return
        payload = dict(clip_id=c['id'], generation=c['generation'], plan_version=p['plan_version'])
        jid = self.repo.enqueue(db, 'pipeline', payload,
                                f"pipeline:{p['id']}:{c['id']}:{c['generation']}:{p['plan_version']}:v1", p['id'])
        c['job_id'], c['state'] = jid, 'queued'

    def start_session(self, db, pid, body, fresh_groups):
        p = self.repo.project(db, pid)
        self.repo.expect(p, body['expected_revision'])
        if not p['confirmed']:
            raise DomainError('CONFLICT', '请先确认分镜清单')
        if self.active_session(db):
            raise DomainError('CONFLICT', '已有活动同步会话，请先结束该会话', action='close_session')
        baseline = self.catalog(db, body['snapshot_id'])
        if body['device_id'] != baseline['device_id']:
            raise DomainError('SCOPE_STALE', '设备与目录不一致')
        ids = {g['id'] for g in baseline['groups']}
        selected = set(body['selected_group_ids'])
        if not selected <= ids:
            raise DomainError('SCOPE_STALE', '选择包含不属于该目录的组')
        membership = {group_key(g): 'included' if g['id'] in selected else 'excluded'
                      for g in baseline['groups']}
        fresh = self.save_catalog(db, fresh_groups)
        for g in fresh_groups:
            membership.setdefault(group_key(g), 'pending_confirmation')
        epochs = {g['storage_epoch'] for g in fresh_groups}
        if len(epochs) > 1:
            raise DomainError('SCOPE_STALE', '混合存储会话，需要重新扫描确认')
        session = dict(id=uid('session'), project_id=pid, device_id=body['device_id'],
                       state='awaiting_scope' if 'pending_confirmation' in membership.values() else 'watching',
                       snapshot_id=fresh['id'], last_complete_scan_at=fresh['completed_at'],
                       membership=membership, storage_epoch=next(iter(epochs), None))
        p['sync'] = session
        for g in fresh_groups:
            if membership[group_key(g)] == 'included':
                self.queue_clip(db, p, self.add_clip(db, p, g))
        self.repo.save(db, p)
        return dict(revision=p['revision'], session=session)

    def session_project(self, db, sid):
        p = next((p for p in self.repo.projects(db) if p['sync'] and p['sync']['id'] == sid), None)
        if not p:
            raise DomainError('NOT_FOUND', '同步会话不存在', 404)
        return p

    def reconcile(self, sid, resume=False):
        try:
            groups = self.camera.scan()
        except DomainError:
            with self.repo.transaction() as db:
                p = self.session_project(db, sid)
                if p['sync']['state'] not in ('closed', 'paused'):
                    p['sync']['state'] = 'disconnected'
                    self.repo.save(db, p)
            raise
        with self.repo.transaction() as db:
            p = self.session_project(db, sid)
            s = p['sync']
            if s['state'] == 'closed' or (s['state'] == 'paused' and not resume):
                return
            catalog = self.save_catalog(db, groups)
            epochs = {g['storage_epoch'] for g in groups}
            changed_card = bool(epochs and epochs != {s['storage_epoch']})
            require_scope = resume or s['state'] != 'watching' or changed_card
            for g in groups:
                key = group_key(g)
                if key not in s['membership']:
                    s['membership'][key] = 'pending_confirmation' if require_scope else 'included'
                if s['membership'][key] == 'included':
                    c = self.add_clip(db, p, g)
                    if c['state'] == 'awaiting_ready':
                        c['group'] = g
                    self.queue_clip(db, p, c)
            s['snapshot_id'] = catalog['id']
            s['last_complete_scan_at'] = catalog['completed_at']
            s['state'] = 'awaiting_scope' if 'pending_confirmation' in s['membership'].values() else 'watching'
            if len(epochs) == 1:
                s['storage_epoch'] = next(iter(epochs))
            if len(epochs) > 1:
                s['state'] = 'error'
            self.repo.save(db, p)

    def confirm_scope(self, db, sid, body):
        p = self.session_project(db, sid)
        self.repo.expect(p, body['expected_revision'])
        s = p['sync']
        if s['state'] != 'awaiting_scope' or body['snapshot_id'] != s['snapshot_id']:
            raise DomainError('SCOPE_STALE', '待确认目录已变化，请刷新')
        catalog = self.catalog(db, s['snapshot_id'])
        include, exclude = set(body['include_group_ids']), set(body['exclude_group_ids'])
        pending = {k for k, v in s['membership'].items() if v == 'pending_confirmation'}
        # Scope confirmation uses group revision keys, so overwritten names stay unambiguous.
        if include & exclude or include | exclude != pending:
            raise DomainError('SCOPE_STALE', '必须明确处理全部待确认组')
        for key in pending:
            s['membership'][key] = 'included' if key in include else 'excluded'
        for g in catalog['groups']:
            if group_key(g) in include:
                self.queue_clip(db, p, self.add_clip(db, p, g))
        s['state'] = 'watching'
        self.repo.save(db, p)
        return dict(revision=p['revision'], session=s)

    def session_action(self, db, sid, revision, action):
        p = self.session_project(db, sid)
        self.repo.expect(p, revision)
        if p['sync']['state'] == 'closed':
            raise DomainError('CONFLICT', '会话已结束，请重新选择范围')
        if action == 'resume':
            p['sync']['state'] = 'awaiting_scope'
            jid = self.repo.enqueue(db, 'resume', dict(session_id=sid), f'resume:{sid}:{revision}', p['id'])
            self.repo.save(db, p)
            return self.repo.job(db, jid)
        p['sync']['state'] = 'paused' if action == 'pause' else 'closed'
        self.repo.save(db, p)
        return dict(revision=p['revision'], session=p['sync'])

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
        if p['sync']:
            p['sync']['membership'][c['group_key']] = body['membership']
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
            s = p['sync']
            pending = sum(v == 'pending_confirmation' for v in s['membership'].values()) if s else 0
            active_clips = [c for c in p['clips'] if c['active']]
            unfinished = [c for c in active_clips if c['state'] != 'analyzed']
            missing_files = any(c['rendition_id'] and c['rendition_id'] not in present for c in active_clips)
            readiness = 'not_ready'
            if result['coverage_complete']:
                if not s or s['state'] in ('paused', 'disconnected', 'error', 'closed') or not s['last_complete_scan_at'] or time.time() - s['last_complete_scan_at'] > self.settings.freshness_seconds:
                    readiness = 'unverified'
                elif (pending or unfinished or missing_files or s['state'] != 'watching'
                      or s['last_complete_scan_at'] < p['last_processed_at']):
                    readiness = 'checking'
                else:
                    readiness = 'ready'
            if p['readiness'] != readiness or p.get('visible_evidence') != [e['id'] for e in evidence]:
                p['readiness'] = readiness
                p['visible_evidence'] = [e['id'] for e in evidence]
                self.repo.save(db, p)
            if result['next_action']:
                result['next_action']['project_revision'] = p['revision']
            jobs = [self.repo.job_dict(row) for row in db.execute(
                'SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 100', (pid,))]
            return dict(project=public_project(p), project_id=pid, revision=p['revision'],
                        plan_version=p['plan_version'], camera_mode='simulator' if self.settings.simulation else 'unconfigured',
                        model_mode='simulator' if self.settings.simulation else 'unconfigured', sync=s,
                        pending_scope_count=pending, pipeline=dict(
                            waiting=sum(c['state'] in ('awaiting_ready', 'queued') for c in active_clips),
                            running=sum(c['state'] in ('downloading', 'preparing', 'analyzing') for c in active_clips),
                            failed=sum(c['state'] in ('failed', 'blocked_format') for c in active_clips)),
                        clips=p['clips'], evidence=evidence, **result, readiness=readiness,
                        checked_at=s['last_complete_scan_at'] if readiness == 'ready' else None,
                        verified_snapshot_id=s['snapshot_id'] if readiness == 'ready' else None, jobs=jobs)
