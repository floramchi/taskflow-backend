from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import Counter

REQUESTS = Counter("http_requests_total", "Total HTTP requests", ["method", "route", "status"])
ERRORS = Counter(
    "http_request_errors_total", "HTTP requests answered with a 5xx", ["method", "route", "status"]
)


def _route_template(request: Request) -> str:
    # The route template (/tasks/{task_id}) keeps label cardinality bounded, unlike the raw path.
    route = request.scope.get("route")
    return route.path if route is not None else "unmatched"


def _record(request: Request, status_code: int) -> None:
    labels = (request.method, _route_template(request), str(status_code))
    REQUESTS.labels(*labels).inc()
    if status_code >= 500:
        ERRORS.labels(*labels).inc()


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    try:
        response = await call_next(request)
    except Exception:
        _record(request, 500)
        raise
    _record(request, response.status_code)
    return response
