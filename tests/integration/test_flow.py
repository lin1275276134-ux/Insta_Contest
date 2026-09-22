import json
from pathlib import Path
import pytest
from conftest import snapshot, start, drain
from tools.simulator import add, write
from backend.app.schema import DomainError
from backend.app.camera.simulator import group_key
from backend.app.api.main import create_app
from fastapi.testclient import TestClient


def test_E01_E05_and_RU02_RU03_RU06(client, app, setup_project, seed):
    pid = setup_project
    sid = start(client, app, pid, [g['id'] for g in seed[:2]])
    drain(app)
    snap = snapshot(client, pid)
    assert [s['state'] for s in snap['shots']] == ['covered', 'pending', 'covered']
    assert len(snap['clips']) == 2
    root = app.state.service.camera.root
    add(root, 'occluded')
    app.state.service.reconcile(sid)
    drain(app)
    assert snapshot(client, pid)['shots'][1]['state'] == 'reshoot'
    add(root, 'clear')
    app.state.service.reconcile(sid)
    drain(app)
    assert snapshot(client, pid)['readiness'] == 'checking'
    app.state.service.reconcile(sid)
    snap = snapshot(client, pid)
    assert snap['readiness'] == 'ready'
    assert snap['checked_at'] and snap['verified_snapshot_id']
    calls = len([j for j in snap['jobs'] if j['kind'] == 'pipeline'])
    for _ in range(10):
        app.state.service.reconcile(sid)
    assert len([j for j in snapshot(client, pid)['jobs'] if j['kind'] == 'pipeline']) == calls
    # New bad footage never erases good coverage, but pending work retracts ready.
    add(root, 'occluded')
    app.state.service.reconcile(sid)
    assert snapshot(client, pid)['readiness'] == 'checking'
    drain(app)
    app.state.service.reconcile(sid)
    snap = snapshot(client, pid)
    assert snap['readiness'] == 'ready'
    good = next(c for c in snap['clips'] if c['name'].endswith('clear'))
    result = client.patch(f"/api/v1/projects/{pid}/clips/{good['id']}/membership", json=dict(
        expected_revision=snap['revision'], membership='excluded', reason='误收'))
    assert result.status_code == 200
    assert snapshot(client, pid)['readiness'] == 'not_ready'
    assert snapshot(client, pid)['shots'][1]['state'] == 'reshoot'


def test_SY02_SY03_scope_race_and_page_failure(client, app, setup_project, seed):
    pid = setup_project
    baseline = app.state.service.scan()
    root = app.state.service.camera.root
    new = add(root, 'clear')
    response = client.post(f'/api/v1/projects/{pid}/sync-sessions', json=dict(
        device_id='camera_demo', snapshot_id=baseline['id'], selected_group_ids=[seed[0]['id']],
        expected_revision=snapshot(client, pid)['revision']))
    s = response.json()['session']
    assert s['state'] == 'awaiting_scope'
    assert s['membership'][group_key(new)] == 'pending_confirmation'
    original_snapshot = s['snapshot_id']
    data = json.loads((root / 'catalog.json').read_text())
    data['fail_page'] = 2
    write(root, data)
    with pytest.raises(DomainError, match='分页失败'):
        app.state.service.reconcile(s['id'])
    assert snapshot(client, pid)['sync']['snapshot_id'] == original_snapshot


def test_SY05_SY06_group_closure(client, app, setup_project, seed):
    pid = setup_project
    sid = start(client, app, pid, [])
    root = app.state.service.camera.root
    add(root, 'clear', closed=False)
    app.state.service.reconcile(sid)
    snap = snapshot(client, pid)
    assert snap['clips'][0]['state'] == 'awaiting_ready'
    drain(app)
    assert not snapshot(client, pid)['evidence']
    data = json.loads((root / 'catalog.json').read_text())
    data['groups'][-1].update(closed=True, complete=True)
    write(root, data)
    app.state.service.reconcile(sid)
    drain(app)
    assert snapshot(client, pid)['clips'][0]['state'] == 'analyzed'


def test_SY09_SY10_E04_pause_resume_and_project_boundary(client, app, setup_project, seed):
    pid = setup_project
    sid = start(client, app, pid, [])
    snap = snapshot(client, pid)
    client.post(f'/api/v1/sync-sessions/{sid}/pause', json={'expected_revision': snap['revision']})
    new = add(app.state.service.camera.root, 'clear')
    app.state.service.reconcile(sid)
    assert not snapshot(client, pid)['clips']
    app.state.service.reconcile(sid, resume=True)
    snap = snapshot(client, pid)
    assert snap['sync']['state'] == 'awaiting_scope'
    assert not snap['clips']
    response = client.post(f'/api/v1/sync-sessions/{sid}/scope:confirm', json=dict(
        expected_revision=snap['revision'], snapshot_id=snap['sync']['snapshot_id'],
        include_group_ids=[group_key(new)], exclude_group_ids=[]))
    assert response.status_code == 200, response.text
    assert len(snapshot(client, pid)['clips']) == 1
    # A second confirmed project cannot seize the device, including while A is paused.
    p2 = client.post('/api/v1/projects', json={'goal': '另一个教程'}).json()
    service = app.state.service
    with service.repo.transaction() as db:
        p = service.repo.project(db, p2['id'])
        p['shots'], p['confirmed'] = snap['project']['shots'], True
        service.repo.save(db, p)
    catalog = service.scan()
    response = client.post(f"/api/v1/projects/{p2['id']}/sync-sessions", json=dict(
        device_id='camera_demo', snapshot_id=catalog['id'], selected_group_ids=[],
        expected_revision=snapshot(client, p2['id'])['revision']))
    assert response.status_code == 409


def test_RU05_freshness_and_missing_local_evidence(client, app, setup_project, seed):
    pid = setup_project
    add(app.state.service.camera.root, 'clear')
    catalog = app.state.service.camera.scan()
    sid = start(client, app, pid, [g['id'] for g in catalog])
    drain(app)
    app.state.service.reconcile(sid)
    snap = snapshot(client, pid)
    assert snap['readiness'] == 'ready'
    settings = app.state.service.settings
    settings.freshness_seconds = -1
    stale = snapshot(client, pid)
    assert stale['readiness'] == 'unverified' and stale['coverage_complete']
    assert stale['revision'] > snap['revision']
    settings.freshness_seconds = 15
    repo = app.state.service.repo
    with repo.transaction() as db:
        p = repo.project(db, pid)
        rid = next(e['rendition_id'] for e in p['evidence'] if e['shot_id'] == p['shots'][1]['id'])
        Path(next(r['path'] for r in p['renditions'] if r['id'] == rid)).unlink()
    assert not snapshot(client, pid)['coverage_complete']


def test_E03_expired_attempt_cannot_commit(client, app, setup_project, seed):
    pid = setup_project
    start(client, app, pid, [seed[0]['id']])
    worker = app.state.worker
    old = worker.claim()
    with worker.repo.transaction() as db:
        db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (old['id'],))
    new = worker.claim()
    assert new['id'] == old['id'] and new['attempt'] == old['attempt'] + 1
    with worker.repo.transaction() as db:
        with pytest.raises(DomainError, match='租约'):
            worker.complete(db, old, {})
    worker.execute(new)
    assert snapshot(client, pid)['clips'][0]['state'] == 'analyzed'
    # Reopening storage preserves projects and evidence.
    restarted = create_app(app.state.service.settings, run_worker=False)
    with TestClient(restarted) as c:
        assert snapshot(c, pid)['evidence']


def test_ME03_unknown_projection_blocks(client, app, setup_project, seed):
    root = app.state.service.camera.root
    data = json.loads((root / 'catalog.json').read_text())
    data['groups'][0]['projection'] = 'panorama'
    write(root, data)
    start(client, app, setup_project, [seed[0]['id']])
    drain(app)
    snap = snapshot(client, setup_project)
    assert snap['clips'][0]['state'] == 'blocked_format'
    assert snap['clips'][0]['error']['code'] == 'MEDIA_UNSUPPORTED'
    assert not snap['evidence']


def test_api_idempotency_origin_cross_project_and_ranges(client, app, setup_project, seed):
    body = {'goal': '重复点击'}
    one = client.post('/api/v1/projects', json=body, headers={'Idempotency-Key': 'same'}).json()
    two = client.post('/api/v1/projects', json=body, headers={'Idempotency-Key': 'same'}).json()
    assert one == two
    assert client.post('/api/v1/projects', json={'goal': '不同'}, headers={'Idempotency-Key': 'same'}).status_code == 409
    assert client.post('/api/v1/projects', json=body, headers={'Origin': 'https://evil.example'}).status_code == 403
    pid = setup_project
    start(client, app, pid, [seed[0]['id']])
    drain(app)
    snap = snapshot(client, pid)
    cid = snap['clips'][0]['id']
    assert client.patch(f"/api/v1/projects/{one['id']}/clips/{cid}/membership", json=dict(
        expected_revision=one['revision'], membership='excluded')).status_code == 404
    rid = snap['clips'][0]['rendition_id']
    response = client.get(f'/api/v1/renditions/{rid}/content', headers={'Range': 'bytes=0-99'})
    assert response.status_code == 206 and len(response.content) == 100
    assert client.get('/api/v1/renditions/..%2Fsecret/content').status_code in (404, 422)


def test_SY07_partial_download_fails_without_evidence(client, app, setup_project, seed):
    start(client, app, setup_project, [seed[0]['id']])
    (app.state.service.camera.root / seed[0]['members'][0]).write_bytes(b'truncated')
    app.state.worker.step()
    snap = snapshot(client, setup_project)
    assert not snap['evidence']
    assert snap['clips'][0]['error']['code'] == 'DOWNLOAD_INCOMPLETE'
    assert snap['jobs'][0]['state'] == 'retry_wait'
