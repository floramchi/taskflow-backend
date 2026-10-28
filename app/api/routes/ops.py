import redis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.cache import redis_client

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    checks = {"database": "ok", "redis": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        checks["database"] = "error"
    try:
        redis_client.ping()
    except redis.RedisError:
        checks["redis"] = "error"

    healthy = all(value == "ok" for value in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "unavailable", "checks": checks}
