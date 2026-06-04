import logging

from redis.asyncio import Redis, from_url

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


def get_redis() -> Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() in lifespan.")
    return _redis_client


async def init_redis() -> None:
    global _redis_client
    if not settings.REDIS_URL:
        raise RuntimeError("REDIS_URL is not configured.")
    _redis_client = from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    await _redis_client.ping()  # type: ignore[awaitable-return]
    logger.info("Redis client initialized")


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis client closed")
