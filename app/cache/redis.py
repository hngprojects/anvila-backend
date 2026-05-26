from redis.asyncio import Redis

from app.core.config import settings


class RedisClient:
    def __init__(self) -> None:
        self.client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )

    async def close(self) -> None:
        await self.client.aclose()


redis = RedisClient()
redis_client = redis.client


async def close_redis() -> None:
    await redis.close()