import json
from conftest import snapshot, start, drain
from tools.simulator import add, write
from backend.app.schema import DomainError


def test_SY08_replacement_and_storage_epoch_require_scope(client, app, setup_project, seed):
    pid = setup_project
    sid = start(client, app, pid, [seed[0]['id']])
    drain(app)
    root = app.state.service.camera.root
    data = json.loads((root / 'catalog.json').read_text())
    data['groups'][0]['revision'] = 'replaced'
    data['groups'][0]['scenario'] = 'unrelated'
    write(root, data)
    app.state.service.reconcile(sid)
    snap = snapshot(client, pid)
    assert not snap['evidence']  # old source revision is no longer current
    assert len(snap['clips']) == 2
    data['groups'][0]['storage_epoch'] = 'new_card'
    data['groups'] = data['groups'][:1]
    write(root, data)
    app.state.service.reconcile(sid)
    snap = snapshot(client, pid)
    assert snap['sync']['state'] == 'awaiting_scope'
    assert snap['pending_scope_count'] == 1


def test_E02_model_failure_retry_preserves_evidence(client, app, setup_project, seed, monkeypatch):
    pid = setup_project
    sid = start(client, app, pid, [seed[0]['id']])
    drain(app)
    initial = snapshot(client, pid)['evidence']
    add(app.state.service.camera.root, 'result')
    app.state.service.reconcile(sid)
    from backend.app.analysis import simulator
    original = simulator.observe
    def timeout(*args):
        raise DomainError('MODEL_TIMEOUT', '模拟模型超时', retryable=True)
    monkeypatch.setattr(simulator, 'observe', timeout)
    app.state.worker.step()
    snap = snapshot(client, pid)
    assert snap['evidence'] == initial
    assert snap['jobs'][0]['state'] == 'retry_wait'
    monkeypatch.setattr(simulator, 'observe', original)
    with app.state.service.repo.transaction() as db:
        db.execute("UPDATE jobs SET next_attempt_at=0 WHERE state='retry_wait'")
    drain(app)
    snap = snapshot(client, pid)
    assert len(snap['evidence']) == 2
    assert all(c['state'] == 'analyzed' for c in snap['clips'])


def test_RU07_excluded_inflight_result_cannot_commit(client, app, setup_project, seed):
    pid = setup_project
    start(client, app, pid, [seed[0]['id']])
    job = app.state.worker.claim()
    snap = snapshot(client, pid)
    cid = snap['clips'][0]['id']
    client.patch(f'/api/v1/projects/{pid}/clips/{cid}/membership', json=dict(
        expected_revision=snap['revision'], membership='excluded'))
    try:
        app.state.worker.execute(job)
    except DomainError as error:
        app.state.worker.fail(job, error)
    snap = snapshot(client, pid)
    assert snap['jobs'][0]['state'] == 'cancelled'
    assert not snap['evidence']


def test_ME04_segment_covers_whole_source(client, app, setup_project, seed):
    app.state.service.settings.segment_seconds = 1
    start(client, app, setup_project, [seed[0]['id']])
    drain(app)
    with app.state.service.repo.transaction() as db:
        p = app.state.service.repo.project(db, setup_project)
    assert len(p['renditions']) == 3
    assert [r['group_start'] for r in p['renditions']] == [0, 1, 2]
    assert sum(r['source_duration'] for r in p['renditions']) == 3


def test_model_time_bounds_cannot_be_accepted(client, app, setup_project, seed, monkeypatch):
    start(client, app, setup_project, [seed[0]['id']])
    from backend.app.analysis import simulator
    original = simulator.observe
    def invalid(*args):
        evidence = original(*args)
        evidence[0]['end'] = 999
        return evidence
    monkeypatch.setattr(simulator, 'observe', invalid)
    drain(app)
    snap = snapshot(client, setup_project)
    assert not snap['evidence']
    assert snap['clips'][0]['error']['code'] == 'MODEL_OUTPUT_INVALID'
