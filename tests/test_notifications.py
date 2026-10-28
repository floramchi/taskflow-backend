from datetime import UTC, datetime, timedelta

import pytest

from app.worker import jobs

PAST = (datetime.now(UTC) - timedelta(days=1)).isoformat()
FUTURE = (datetime.now(UTC) + timedelta(days=1)).isoformat()


@pytest.fixture
def setup(client, create_user):
    owner = create_user("owner@example.com")
    dev = create_user("dev@example.com")
    project = client.post("/projects", json={"name": "Alpha"}, headers=owner).json()
    return {
        "owner": owner,
        "dev": dev,
        "dev_id": client.get("/auth/me", headers=dev).json()["id"],
        "owner_id": client.get("/auth/me", headers=owner).json()["id"],
        "project_id": project["id"],
    }


def _create_task(client, setup, **fields):
    resp = client.post(
        f"/projects/{setup['project_id']}/tasks",
        json={"title": "ship it", **fields},
        headers=setup["owner"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _notifications(client, headers):
    resp = client.get("/notifications", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_reassignment_creates_one_notification_for_new_assignee(client, setup):
    task = _create_task(client, setup)

    client.patch(
        f"/tasks/{task['id']}", json={"assignee_id": setup["dev_id"]}, headers=setup["owner"]
    )

    result = _notifications(client, setup["dev"])
    assert result["total"] == 1
    note = result["items"][0]
    assert note["type"] == "reassigned"
    assert note["task_id"] == task["id"]
    assert "ship it" in note["message"]
    assert _notifications(client, setup["owner"])["total"] == 0


def test_reassigning_again_notifies_the_new_assignee_only(client, setup):
    task = _create_task(client, setup, assignee_id=setup["dev_id"])

    client.patch(
        f"/tasks/{task['id']}", json={"assignee_id": setup["owner_id"]}, headers=setup["owner"]
    )

    assert _notifications(client, setup["owner"])["total"] == 1
    assert _notifications(client, setup["dev"])["total"] == 0


def test_update_without_reassignment_creates_no_notification(client, setup):
    task = _create_task(client, setup, assignee_id=setup["dev_id"])

    client.patch(f"/tasks/{task['id']}", json={"status": "done"}, headers=setup["owner"])
    client.patch(f"/tasks/{task['id']}", json={"title": "renamed"}, headers=setup["owner"])
    client.patch(
        f"/tasks/{task['id']}", json={"assignee_id": setup["dev_id"]}, headers=setup["owner"]
    )

    assert _notifications(client, setup["dev"])["total"] == 0


def test_unassigning_creates_no_notification(client, setup):
    task = _create_task(client, setup, assignee_id=setup["dev_id"])

    client.patch(f"/tasks/{task['id']}", json={"assignee_id": None}, headers=setup["owner"])

    assert _notifications(client, setup["dev"])["total"] == 0


def test_overdue_scan_creates_one_notification_even_when_run_twice(client, setup):
    task = _create_task(client, setup, assignee_id=setup["dev_id"], due_date=PAST)

    assert jobs.scan_overdue_tasks.delay().get() == 1
    assert jobs.scan_overdue_tasks.delay().get() == 0

    result = _notifications(client, setup["dev"])
    assert result["total"] == 1
    assert result["items"][0]["type"] == "overdue"
    assert result["items"][0]["task_id"] == task["id"]


def test_overdue_scan_ignores_done_future_unassigned_and_undated_tasks(client, setup):
    _create_task(client, setup, assignee_id=setup["dev_id"], due_date=PAST, status="done")
    _create_task(client, setup, assignee_id=setup["dev_id"], due_date=FUTURE)
    _create_task(client, setup, assignee_id=setup["dev_id"])
    _create_task(client, setup, due_date=PAST)

    assert jobs.scan_overdue_tasks.delay().get() == 0
    assert _notifications(client, setup["dev"])["total"] == 0


def test_task_that_becomes_overdue_later_is_picked_up_by_next_scan(client, setup):
    task = _create_task(client, setup, assignee_id=setup["dev_id"], due_date=FUTURE)
    assert jobs.scan_overdue_tasks.delay().get() == 0

    client.patch(f"/tasks/{task['id']}", json={"due_date": PAST}, headers=setup["owner"])

    assert jobs.scan_overdue_tasks.delay().get() == 1


def test_overdue_task_marked_done_before_scan_is_not_notified(client, setup):
    task = _create_task(client, setup, assignee_id=setup["dev_id"], due_date=PAST)
    client.patch(f"/tasks/{task['id']}", json={"status": "done"}, headers=setup["owner"])

    assert jobs.scan_overdue_tasks.delay().get() == 0


def test_overdue_notification_goes_to_assignee_not_owner(client, setup):
    _create_task(client, setup, assignee_id=setup["dev_id"], due_date=PAST)
    jobs.scan_overdue_tasks.delay().get()

    assert _notifications(client, setup["owner"])["total"] == 0


def test_notifications_are_paginated_newest_first(client, setup):
    for i in range(3):
        _create_task(client, setup, title=f"task-{i}", assignee_id=setup["dev_id"], due_date=PAST)
    jobs.scan_overdue_tasks.delay().get()

    first = client.get("/notifications?page=1&size=2", headers=setup["dev"]).json()
    second = client.get("/notifications?page=2&size=2", headers=setup["dev"]).json()

    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    ids = [n["id"] for n in first["items"] + second["items"]]
    assert ids == sorted(ids, reverse=True)


def test_notifications_require_authentication(client):
    assert client.get("/notifications").status_code == 401
