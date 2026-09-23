from pathlib import Path

from conftest import drain, snapshot


def upload(client, pid, revision, paths, key='batch'):
    handles = [Path(path).open('rb') for path in paths]
    try:
        response = client.post(
            f'/api/v1/projects/{pid}/imports',
            data={'expected_revision': str(revision), 'projection': 'rectilinear'},
            files=[('files', (Path(path).name, handle, 'video/mp4')) for path, handle in zip(paths, handles)],
            headers={'Idempotency-Key': key},
        )
    finally:
        for handle in handles:
            handle.close()
    assert response.status_code == 202, response.text
    return response.json()


def test_batch_local_import_is_primary_deduplicated_and_camera_free(client, app, setup_project, seed):
    pid = setup_project
    fixture_root = app.state.service.settings.data_dir / 'simulator'
    before = snapshot(client, pid)
    result = upload(client, pid, before['revision'], [
        fixture_root / seed[0]['members'][0],
        fixture_root / seed[1]['members'][0],
    ])
    assert [item['status'] for item in result['items']] == ['accepted', 'accepted']
    checking = snapshot(client, pid)
    assert checking['readiness'] == 'checking'
    assert 'sync' not in checking and 'camera_mode' not in checking
    drain(app)
    done = snapshot(client, pid)
    assert all(clip['state'] == 'analyzed' for clip in done['clips'])
    assert all(clip['source'] == 'local' and clip['sha256'] for clip in done['clips'])
    duplicate = upload(client, pid, done['revision'], [
        fixture_root / seed[0]['members'][0],
    ], key='duplicate')
    assert duplicate['items'][0]['status'] == 'duplicate'
    assert len(snapshot(client, pid)['clips']) == 2


def test_partial_invalid_batch_keeps_successful_files(client, app, setup_project, seed, tmp_path):
    empty = tmp_path / 'empty.mp4'
    empty.write_bytes(b'')
    pid = setup_project
    before = snapshot(client, pid)
    handles = [
        (app.state.service.settings.data_dir / 'simulator' / seed[0]['members'][0]).open('rb'),
        empty.open('rb'),
    ]
    try:
        response = client.post(
            f'/api/v1/projects/{pid}/imports',
            data={'expected_revision': str(before['revision']), 'projection': 'rectilinear'},
            files=[('files', ('good.mp4', handles[0], 'video/mp4')), ('files', ('empty.mp4', handles[1], 'video/mp4'))],
        )
    finally:
        for handle in handles:
            handle.close()
    assert response.status_code == 202
    assert sorted(item['status'] for item in response.json()['items']) == ['accepted', 'failed']
    assert len(snapshot(client, pid)['clips']) == 1


def test_exclude_and_reinclude_local_clip_requeues_analysis(client, app, setup_project, seed):
    pid = setup_project
    result = upload(client, pid, snapshot(client, pid)['revision'], [
        app.state.service.settings.data_dir / 'simulator' / seed[0]['members'][0],
    ])
    drain(app)
    snap = snapshot(client, pid)
    cid = result['items'][0]['clip_id']
    excluded = client.patch(f'/api/v1/projects/{pid}/clips/{cid}/membership', json={
        'expected_revision': snap['revision'], 'membership': 'excluded', 'reason': '误选'})
    assert excluded.status_code == 200
    current = snapshot(client, pid)
    included = client.patch(f'/api/v1/projects/{pid}/clips/{cid}/membership', json={
        'expected_revision': current['revision'], 'membership': 'included'})
    assert included.status_code == 200
    assert snapshot(client, pid)['readiness'] == 'checking'
    drain(app)
    assert snapshot(client, pid)['clips'][0]['state'] == 'analyzed'
