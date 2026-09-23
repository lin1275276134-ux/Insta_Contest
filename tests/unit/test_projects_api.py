def test_delete_project_removes_it_from_the_list(client):
    project = client.post('/api/v1/projects', json={'goal': '一次性项目'}).json()

    response = client.request(
        'DELETE',
        f"/api/v1/projects/{project['id']}",
        json={'expected_revision': project['revision']},
    )

    assert response.status_code == 200
    assert response.json() == {'id': project['id'], 'deleted': True}
    assert client.get('/api/v1/projects').json()['items'] == []
    assert client.get(f"/api/v1/projects/{project['id']}/snapshot").status_code == 404


def test_delete_project_rejects_stale_revision(client):
    project = client.post('/api/v1/projects', json={'goal': '保留项目'}).json()
    client.post(
        f"/api/v1/projects/{project['id']}/plan:generate",
        json={'expected_revision': project['revision']},
    )

    response = client.request(
        'DELETE',
        f"/api/v1/projects/{project['id']}",
        json={'expected_revision': project['revision']},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'STALE_REVISION'
