import pytest
from fastapi.testclient import TestClient
from backend.app.config import Settings
from backend.app.api.main import create_app
from tools.simulator import add


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path, simulation=True, min_free_bytes=0), run_worker=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def setup_project(client, app):
    p = client.post('/api/v1/projects', json={'goal': '安装支架'}).json()
    pid = p['id']
    client.post(f'/api/v1/projects/{pid}/plan:generate', json={'expected_revision': p['revision']})
    app.state.worker.step()
    snap = client.get(f'/api/v1/projects/{pid}/snapshot').json()
    response = client.post(f'/api/v1/projects/{pid}/plan:confirm', json={'expected_revision': snap['revision']})
    assert response.status_code == 200, response.text
    return pid


@pytest.fixture
def seed(app):
    root = app.state.service.settings.data_dir / 'simulator'
    return [add(root, s) for s in ('materials', 'result', 'unrelated')]


def snapshot(client, pid):
    response = client.get(f'/api/v1/projects/{pid}/snapshot')
    assert response.status_code == 200, response.text
    return response.json()


def start(client, app, pid, selected):
    catalog = app.state.service.scan()
    response = client.post(f'/api/v1/projects/{pid}/sync-sessions', json=dict(
        device_id='camera_demo', snapshot_id=catalog['id'], selected_group_ids=selected,
        expected_revision=snapshot(client, pid)['revision']))
    assert response.status_code == 201, response.text
    return response.json()['session']['id']


def drain(app):
    for _ in range(100):
        if not app.state.worker.step():
            return
    raise AssertionError('queue did not drain')
