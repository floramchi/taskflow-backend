import pytest
import redis

from app.core import cache


@pytest.fixture
def project(client, create_user):
    headers = create_user("owner@example.com")
    resp = client.post("/projects", json={"name": "Alpha"}, headers=headers)
    return {"id": resp.json()["id"], "headers": headers}


def _create_task(client, project, **fields):
    resp = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "t", **fields},
        headers=project["headers"],
    )
    assert resp.status_code == 201
    return resp.json()


def _get_tasks(client, headers, query=""):
    return client.get(f"/tasks?{query}", headers=headers)


def test_first_request_misses_then_hits(client, project):
    _create_task(client, project)

    first = _get_tasks(client, project["headers"])
    second = _get_tasks(client, project["headers"])

    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()


def test_status_change_is_visible_on_next_get(client, project):
    task = _create_task(client, project, status="todo")
    _get_tasks(client, project["headers"])
    assert _get_tasks(client, project["headers"]).headers["X-Cache"] == "HIT"

    client.patch(f"/tasks/{task['id']}", json={"status": "done"}, headers=project["headers"])

    after = _get_tasks(client, project["headers"])
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["items"][0]["status"] == "done"
    assert _get_tasks(client, project["headers"], "status=todo").json()["items"] == []


def test_create_invalidates_cache(client, project):
    _create_task(client, project, title="first")
    assert _get_tasks(client, project["headers"]).json()["total"] == 1

    _create_task(client, project, title="second")

    after = _get_tasks(client, project["headers"])
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["total"] == 2


def test_delete_invalidates_cache(client, project):
    task = _create_task(client, project)
    assert _get_tasks(client, project["headers"]).json()["total"] == 1

    client.delete(f"/tasks/{task['id']}", headers=project["headers"])

    after = _get_tasks(client, project["headers"])
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["total"] == 0


def test_project_delete_invalidates_cache(client, project):
    _create_task(client, project)
    assert _get_tasks(client, project["headers"]).json()["total"] == 1

    client.delete(f"/projects/{project['id']}", headers=project["headers"])

    after = _get_tasks(client, project["headers"])
    assert after.headers["X-Cache"] == "MISS"
    assert after.json()["total"] == 0


def test_different_filters_use_different_cache_entries(client, project):
    _create_task(client, project, status="done")
    _create_task(client, project, status="todo")

    assert _get_tasks(client, project["headers"], "status=done").headers["X-Cache"] == "MISS"
    assert _get_tasks(client, project["headers"], "status=todo").headers["X-Cache"] == "MISS"
    done = _get_tasks(client, project["headers"], "status=done")
    assert done.headers["X-Cache"] == "HIT"
    assert done.json()["total"] == 1


def test_users_do_not_share_cache_entries(client, project, create_user):
    _create_task(client, project, title="secret")
    other = create_user("other@example.com")

    assert _get_tasks(client, project["headers"]).json()["total"] == 1
    assert _get_tasks(client, project["headers"]).headers["X-Cache"] == "HIT"

    theirs = _get_tasks(client, other)
    assert theirs.headers["X-Cache"] == "MISS"
    assert theirs.json()["items"] == []


def test_one_users_write_does_not_invalidate_another_users_cache(client, project, create_user):
    other = create_user("other@example.com")
    _get_tasks(client, other)

    _create_task(client, project)

    assert _get_tasks(client, other).headers["X-Cache"] == "HIT"


def test_falls_back_to_database_when_redis_is_down(client, project, monkeypatch):
    class BrokenRedis:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise redis.ConnectionError("redis is down")

            return fail

    monkeypatch.setattr(cache, "redis_client", BrokenRedis())
    task = _create_task(client, project)

    resp = _get_tasks(client, project["headers"])
    assert resp.status_code == 200
    assert resp.headers["X-Cache"] == "MISS"
    assert resp.json()["items"][0]["id"] == task["id"]

    client.patch(f"/tasks/{task['id']}", json={"status": "done"}, headers=project["headers"])
    assert _get_tasks(client, project["headers"]).json()["items"][0]["status"] == "done"
