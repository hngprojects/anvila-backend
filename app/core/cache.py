import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from redis.exceptions import LockError

from app.core.config import settings
from app.db.redis import get_redis

logger = logging.getLogger(__name__)


def normalize_key(key: str | dict) -> str:
    """
    Normalize a cache key to a stable string.
    - str keys are used as-is
    - dict keys are sorted, JSON serialized, then hashed (MD5)
      to keep keys short and Redis-safe regardless of content.
    """
    if isinstance(key, str):
        return key
    stable = json.dumps(key, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(stable.encode()).hexdigest()


class CacheNamespace:
    """
    A scoped cache client for a specific namespace.
    All keys are versioned — bumping the version instantly
    invalidates all entries without a delete scan.
    """

    def __init__(self, namespace: str, default_ttl: int = settings.DEFAULT_CACHE_TTL) -> None:
        self.namespace = namespace
        self.default_ttl = default_ttl
        self._version_key = f"cache:{namespace}:version"

    @property
    def redis(self):
        return get_redis()

    async def _version(self) -> int:
        raw = await self.redis.get(self._version_key)
        return int(raw) if raw else 0

    async def _key(self, key: str | dict) -> str:
        version = await self._version()
        return f"cache:{self.namespace}:v{version}:{normalize_key(key)}"

    def _get_ttl(self, ttl: int | None) -> int:
        if ttl is not None:
            return ttl
        return self.default_ttl

    async def get(self, key: str | dict) -> Any | None:
        """Return cached value or None if missing/expired."""
        full_key = await self._key(key)
        try:
            raw = await self.redis.get(full_key)
            return json.loads(raw) if raw is not None else None
        except Exception:
            logger.exception("cache.get failed namespace=%s key=%s", self.namespace, full_key)
            return None

    async def set(self, key: str | dict, value: Any, ttl: int | None = None) -> bool:
        """Cache a value. Returns True on success."""
        full_key = await self._key(key)
        try:
            await self.redis.set(full_key, json.dumps(value), ex=self._get_ttl(ttl))
            return True
        except Exception:
            logger.exception("cache.set failed namespace=%s key=%s", self.namespace, full_key)
            return False

    async def delete(self, key: str | dict) -> bool:
        """Delete a single entry. Returns True if it existed."""
        full_key = await self._key(key)
        try:
            return await self.redis.delete(full_key) > 0
        except Exception:
            logger.exception("cache.delete failed namespace=%s key=%s", self.namespace, full_key)
            return False

    async def get_or_set(
        self,
        key: str | dict,
        fetch_func: Callable[[], Awaitable[Any]],
        ttl: int | None = None,
    ) -> Any:
        """
        Return cached value if it exists, otherwise call fetcher(),
        cache and return the result.
        """
        cached = await self.get(key)
        if cached is not None:
            return cached

        lock_key = f"lock:{self.namespace}:{normalize_key(key)}"

        try:
            async with self.redis.lock(lock_key, timeout=5, blocking_timeout=5):
                # Double-check after acquiring lock — another request may
                cached = await self.get(key)
                if cached is not None:
                    return cached

                fresh = await fetch_func()
                if fresh is not None:
                    await self.set(key, fresh, ttl)
                return fresh
        except LockError:
            return await fetch_func()

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern in this namespace.
        Returns number of keys deleted.

        Usage:
            await user_cache.delete_pattern("profile:*")
        """
        full_pattern = await self._key(pattern)
        deleted = 0
        try:
            async for key in self.redis.scan_iter(full_pattern, count=100):
                await self.redis.delete(key)
                deleted += 1
            return deleted
        except Exception:
            logger.exception("cache.delete_pattern failed namespace=%s", self.namespace)
            return 0

    async def invalidate(self) -> None:
        """
        Invalidate all entries in this namespace by bumping the version.
        Old keys become unreachable and expire naturally via TTL.
        """
        try:
            await self.redis.incr(self._version_key)
        except Exception:
            logger.exception("cache.invalidate failed namespace=%s", self.namespace)


async def clear_all_cache() -> int:
    """Clears all cache"""
    redis_client = get_redis()
    deleted = 0
    try:
        async for key in redis_client.scan_iter("cache:*", count=100):
            await redis_client.delete(key)
            deleted += 1
        return deleted
    except Exception:
        logger.exception("cache.clear_all_cache failed")
        return 0


persona_cache = CacheNamespace("personas", default_ttl=120)
explore_cache = CacheNamespace("explore_personas", default_ttl=60)
session_cache = CacheNamespace("sessions", default_ttl=300)
