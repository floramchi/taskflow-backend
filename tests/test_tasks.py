import pytest


@pytest.fixture
def project(client, create_user):
    headers = create_user("owner@example.com")
    resp = client.post("/projects", json={"name": "Alpha"}, headers=headers)
    return {"id": resp.json()["id"], "headers": headers}


def _create_task(client, project, **fields):
    body = {"title": "task", **fields}
    resp = client.post(f"/projects/{project['id']}/tasks", json=body, headers=project["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


def _list(client, headers, query=""):
    resp = client.get(f"/tasks?{query}", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_task_crud_flow(client, project):
    headers = project["headers"]
    task = _create_task(client, project, title="write tests", due_date="2030-01-01T00:00:00Z")
    assert task["status"] == "todo"
    assert task["assignee_id"] is None

    assert client.get(f"/tasks/{task['id']}", headers=headers).json()["title"] == "write tests"

    resp = client.patch(f"/tasks/{task['id']}", json={"status": "in_progress"}, headers=headers)
    assert resp.json()["status"] == "in_progress"
    assert resp.json()["title"] == "write tests"

    assert client.delete(f"/tasks/{task['id']}", headers=headers).status_code == 204
    assert client.get(f"/tasks/{task['id']}", headers=headers).status_code == 404


def test_create_task_validates_input(client, project):
    url = f"/projects/{project['id']}/tasks"
    headers = project["headers"]
    assert client.post(url, json={"title": ""}, headers=headers).status_code == 422
    assert (
        client.post(url, json={"title": "x", "status": "bogus"}, headers=headers).status_code == 422
    )


def test_assignee_must_exist(client, project):
    url = f"/projects/{project['id']}/tasks"
    resp = client.post(url, json={"title": "x", "assignee_id": 9999}, headers=project["headers"])
    assert resp.status_code == 422

    task = _create_task(client, project)
    resp = client.patch(
        f"/tasks/{task['id']}", json={"assignee_id": 9999}, headers=project["headers"]
    )
    assert resp.status_code == 422


def test_assignee_can_be_cleared(client, project, create_user):
    create_user("dev@example.com")
    me = client.get("/auth/me", headers=project["headers"]).json()
    task = _create_task(client, project, assignee_id=me["id"])

    resp = client.patch(
        f"/tasks/{task['id']}", json={"assignee_id": None}, headers=project["headers"]
    )
    assert resp.json()["assignee_id"] is None


def test_filter_by_status(client, project):
    _create_task(client, project, title="a", status="todo")
    _create_task(client, project, title="b", status="done")

    result = _list(client, project["headers"], "status=done")
    assert [t["title"] for t in result["items"]] == ["b"]
    assert result["total"] == 1


def test_filter_by_assignee(client, project, create_user):
    create_user("dev@example.com")
    me = client.get("/auth/me", headers=project["headers"]).json()
    _create_task(client, project, title="mine", assignee_id=me["id"])
    _create_task(client, project, title="unassigned")

    result = _list(client, project["headers"], f"assignee_id={me['id']}")
    assert [t["title"] for t in result["items"]] == ["mine"]


def test_filter_by_project(client, project):
    other = client.post("/projects", json={"name": "Beta"}, headers=project["headers"]).json()
    _create_task(client, project, title="in-alpha")
    client.post(
        f"/projects/{other['id']}/tasks", json={"title": "in-beta"}, headers=project["headers"]
    )

    result = _list(client, project["headers"], f"project_id={other['id']}")
    assert [t["title"] for t in result["items"]] == ["in-beta"]


def test_filter_by_due_date_range(client, project):
    _create_task(client, project, title="early", due_date="2030-01-01T00:00:00Z")
    _create_task(client, project, title="middle", due_date="2030-01-15T00:00:00Z")
    _create_task(client, project, title="late", due_date="2030-02-01T00:00:00Z")
    _create_task(client, project, title="no-date")

    headers = project["headers"]
    after = _list(client, headers, "due_after=2030-01-10T00:00:00Z")
    assert [t["title"] for t in after["items"]] == ["middle", "late"]

    before = _list(client, headers, "due_before=2030-01-20T00:00:00Z")
    assert [t["title"] for t in before["items"]] == ["early", "middle"]

    window = _list(
        client, headers, "due_after=2030-01-10T00:00:00Z&due_before=2030-01-20T00:00:00Z"
    )
    assert [t["title"] for t in window["items"]] == ["middle"]


def test_filters_combine(client, project):
    _create_task(client, project, title="a", status="done", due_date="2030-01-01T00:00:00Z")
    _create_task(client, project, title="b", status="todo", due_date="2030-01-01T00:00:00Z")

    result = _list(client, project["headers"], "status=done&due_before=2030-06-01T00:00:00Z")
    assert [t["title"] for t in result["items"]] == ["a"]


def test_pagination_boundaries(client, project):
    for i in range(5):
        _create_task(client, project, title=f"t{i}")
    headers = project["headers"]

    first = _list(client, headers, "page=1&size=2")
    assert [t["title"] for t in first["items"]] == ["t0", "t1"]
    assert (first["total"], first["page"], first["size"]) == (5, 1, 2)

    last = _list(client, headers, "page=3&size=2")
    assert [t["title"] for t in last["items"]] == ["t4"]

    beyond = _list(client, headers, "page=4&size=2")
    assert beyond["items"] == []
    assert beyond["total"] == 5


@pytest.mark.parametrize("query", ["page=0", "size=0", "size=101"])
def test_invalid_pagination_returns_422(client, project, query):
    assert client.get(f"/tasks?{query}", headers=project["headers"]).status_code == 422


def test_tasks_require_authentication(client):
    assert client.get("/tasks").status_code == 401
    assert client.get("/tasks/1").status_code == 401


def test_other_user_cannot_access_tasks(client, project, create_user):
    task = _create_task(client, project)
    other = create_user("intruder@example.com")

    assert client.get(f"/tasks/{task['id']}", headers=other).status_code == 404
    resp = client.patch(f"/tasks/{task['id']}", json={"status": "done"}, headers=other)
    assert resp.status_code == 404
    assert client.delete(f"/tasks/{task['id']}", headers=other).status_code == 404

    still_there = client.get(f"/tasks/{task['id']}", headers=project["headers"]).json()
    assert still_there["status"] == "todo"


def test_other_user_cannot_create_task_in_project(client, project, create_user):
    other = create_user("intruder@example.com")
    resp = client.post(f"/projects/{project['id']}/tasks", json={"title": "x"}, headers=other)
    assert resp.status_code == 404


def test_task_list_excludes_other_users_tasks(client, project, create_user):
    _create_task(client, project, title="secret")
    other = create_user("intruder@example.com")

    assert _list(client, other)["items"] == []
    assert _list(client, other)["total"] == 0


def test_deleting_project_removes_its_tasks(client, project):
    task = _create_task(client, project)
    client.delete(f"/projects/{project['id']}", headers=project["headers"])
    assert client.get(f"/tasks/{task['id']}", headers=project["headers"]).status_code == 404
