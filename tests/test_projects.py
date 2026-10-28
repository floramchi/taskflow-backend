def _create_project(client, headers, name="Alpha"):
    resp = client.post("/projects", json={"name": name, "description": "d"}, headers=headers)
    assert resp.status_code == 201
    return resp.json()


def test_project_crud_flow(client, create_user):
    headers = create_user("a@example.com")

    project = _create_project(client, headers)
    assert project["name"] == "Alpha"

    assert client.get("/projects", headers=headers).json() == [project]
    assert client.get(f"/projects/{project['id']}", headers=headers).json() == project

    resp = client.patch(f"/projects/{project['id']}", json={"name": "Beta"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Beta"
    assert resp.json()["description"] == "d"

    assert client.delete(f"/projects/{project['id']}", headers=headers).status_code == 204
    assert client.get(f"/projects/{project['id']}", headers=headers).status_code == 404


def test_projects_require_authentication(client):
    assert client.get("/projects").status_code == 401
    assert client.post("/projects", json={"name": "x"}).status_code == 401


def test_create_project_validates_name(client, create_user):
    headers = create_user()
    assert client.post("/projects", json={"name": ""}, headers=headers).status_code == 422


def test_user_cannot_read_another_users_project(client, create_user):
    owner = create_user("a@example.com")
    other = create_user("b@example.com")
    project = _create_project(client, owner)

    assert client.get(f"/projects/{project['id']}", headers=other).status_code == 404


def test_user_cannot_update_another_users_project(client, create_user):
    owner = create_user("a@example.com")
    other = create_user("b@example.com")
    project = _create_project(client, owner)

    resp = client.patch(f"/projects/{project['id']}", json={"name": "Hacked"}, headers=other)
    assert resp.status_code == 404
    assert client.get(f"/projects/{project['id']}", headers=owner).json()["name"] == "Alpha"


def test_user_cannot_delete_another_users_project(client, create_user):
    owner = create_user("a@example.com")
    other = create_user("b@example.com")
    project = _create_project(client, owner)

    assert client.delete(f"/projects/{project['id']}", headers=other).status_code == 404
    assert client.get(f"/projects/{project['id']}", headers=owner).status_code == 200


def test_project_list_only_contains_own_projects(client, create_user):
    owner = create_user("a@example.com")
    other = create_user("b@example.com")
    _create_project(client, owner, "mine")
    _create_project(client, other, "theirs")

    names = [p["name"] for p in client.get("/projects", headers=owner).json()]
    assert names == ["mine"]
