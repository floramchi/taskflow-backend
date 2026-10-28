import redis
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.exc import OperationalError

from app.api.deps import get_db
from app.main import app
from app.services import task_service


def _count(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_health_reports_ok_when_dependencies_are_up(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_health_returns_503_when_redis_is_down(client, monkeypatch):
    class BrokenRedis:
        def ping(self):
            raise redis.ConnectionError("redis is down")

    monkeypatch.setattr("app.api.routes.ops.redis_client", BrokenRedis())

    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": "ok", "redis": "error"}


def test_health_returns_503_when_database_is_down(client):
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("db is down"))

    app.dependency_overrides[get_db] = lambda: BrokenSession()

    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {"database": "error", "redis": "ok"}


def test_metrics_exposes_prometheus_format(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in resp.text


def test_request_counter_uses_route_template_not_raw_path(client):
    labels = {"method": "GET", "route": "/tasks/{task_id}", "status": "401"}
    before = _count("http_requests_total", **labels)

    client.get("/tasks/1")
    client.get("/tasks/2")

    assert _count("http_requests_total", **labels) == before + 2


def test_unknown_paths_share_one_label(client):
    labels = {"method": "GET", "route": "unmatched", "status": "404"}
    before = _count("http_requests_total", **labels)

    client.get("/does-not-exist-1")
    client.get("/does-not-exist-2")

    assert _count("http_requests_total", **labels) == before + 2


def test_client_errors_do_not_increment_error_counter(client):
    labels = {"method": "GET", "route": "/auth/me", "status": "401"}
    errors_before = _count("http_request_errors_total", **labels)
    requests_before = _count("http_requests_total", **labels)

    client.get("/auth/me")

    assert _count("http_requests_total", **labels) == requests_before + 1
    assert _count("http_request_errors_total", **labels) == errors_before


def test_server_errors_increment_error_counter(client, create_user, monkeypatch):
    headers = create_user("a@example.com")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(task_service, "list_tasks_json", boom)
    labels = {"method": "GET", "route": "/tasks", "status": "500"}
    errors_before = _count("http_request_errors_total", **labels)
    requests_before = _count("http_requests_total", **labels)

    with TestClient(app, raise_server_exceptions=False) as quiet_client:
        resp = quiet_client.get("/tasks", headers=headers)

    assert resp.status_code == 500
    assert _count("http_requests_total", **labels) == requests_before + 1
    assert _count("http_request_errors_total", **labels) == errors_before + 1
