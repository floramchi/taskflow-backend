import hashlib
import json
import logging

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

redis_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=0.5,
    socket_timeout=0.5,
)

# Invalidation scheme: every cached task list is keyed with the owner's current
# version number. A write bumps the version (INCR), so older keys are never read
# again and simply expire via TTL. No SCAN or pattern deletes are needed.
#
# The version is read *before* the DB query. If a write lands in between, the
# reader stores possibly stale data under the old version, which nobody reads.
#
# Every Redis call degrades to a cache miss / no-op so an outage never breaks the
# API. If a bump is lost during an outage, stale entries can survive until their
# TTL, which is the accepted tradeoff.


def _version_key(user_id: int) -> str:
    return f"tasks_ver:{user_id}"


def tasks_key(user_id: int, params: dict) -> str | None:
    """Return the cache key for this user's query, or None if Redis is unavailable."""
    try:
        version = redis_client.get(_version_key(user_id)) or 0
    except redis.RedisError:
        logger.warning("Redis unavailable, skipping task cache")
        return None
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    return f"tasks:{user_id}:v{version}:{digest}"


def get_cached(key: str | None) -> str | None:
    if key is None:
        return None
    try:
        return redis_client.get(key)
    except redis.RedisError:
        logger.warning("Redis read failed, falling back to the database")
        return None


def set_cached(key: str | None, value: str) -> None:
    if key is None:
        return
    try:
        redis_client.set(key, value, ex=settings.cache_ttl_seconds)
    except redis.RedisError:
        logger.warning("Redis write failed, response not cached")


def bump_tasks_version(user_id: int) -> None:
    try:
        redis_client.incr(_version_key(user_id))
    except redis.RedisError:
        logger.warning("Redis unavailable, task cache version not bumped for user %s", user_id)
