"""Redis client helper used for chat memory cache."""

from __future__ import annotations

from functools import lru_cache

from app.core.settings import settings

try:  # Optional dependency until requirements are installed.
    import redis
except Exception:  # pragma: no cover - depends on local optional packages
    redis = None  # type: ignore[assignment]


class RedisUnavailableError(RuntimeError):
    """Raised when Redis client cannot be created."""


@lru_cache(maxsize=1)
def get_redis_client():
    if redis is None:
        raise RedisUnavailableError("redis-py is not installed. Run: python -m pip install -r requirements.txt")

    if settings.redis_url:
        return redis.Redis.from_url(settings.redis_url, decode_responses=True)

    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        decode_responses=True,
    )
