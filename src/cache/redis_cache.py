# path: src/cache/redis_cache.py
import json
from typing import Optional, Any
from datetime import datetime, timezone

from src.utils.logger import get_logger
from src.config import settings

log = get_logger(__name__)

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None
    log.warning("redis.asyncio not available, cache will be disabled")


class RedisCache:
    """Async Redis cache layer with structured key patterns and TTLs."""

    KEY_PREFIXES = {
        "stream": "stream:v2",
        "health": "source_health",
        "search": "search",
        "anime": "anime_meta",
        "rate_limit": "rate_limit",
    }

    def __init__(self, redis_url: str = settings.redis_url):
        self.redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._enabled = aioredis is not None

    async def connect(self):
        if not self._enabled:
            log.warning("Redis not available, operating without cache")
            return
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    health_check_interval=15,
                )
                await self._redis.ping()
                log.info("Connected to Redis", url=self.redis_url)
            except Exception as e:
                log.warning("Failed to connect to Redis", error=str(e))
                self._enabled = False

    async def disconnect(self):
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

    def _key(self, prefix: str, *parts: str) -> str:
        return f"{self.KEY_PREFIXES.get(prefix, prefix)}:{':'.join(parts)}"

    async def get_stream(self, anime_id: int, episode: int) -> Optional[dict]:
        key = self._key("stream", str(anime_id), str(episode))
        return await self._get_json(key)

    async def set_stream(self, anime_id: int, episode: int, data: dict, ttl: int = settings.redis_stream_ttl):
        key = self._key("stream", str(anime_id), str(episode))
        await self._set_json(key, data, ttl)

    async def get_source_health(self, source: str) -> Optional[dict]:
        key = self._key("health", source)
        return await self._get_json(key)

    async def set_source_health(self, source: str, data: dict, ttl: int = settings.redis_health_ttl):
        key = self._key("health", source)
        await self._set_json(key, data, ttl)

    async def get_search(self, query: str) -> Optional[list]:
        key = self._key("search", query.lower().strip())
        return await self._get_json(key)

    async def set_search(self, query: str, data: list, ttl: int = settings.redis_search_ttl):
        key = self._key("search", query.lower().strip())
        await self._set_json(key, data, ttl)

    async def get_anime_meta(self, anilist_id: int) -> Optional[dict]:
        key = self._key("anime", str(anilist_id))
        return await self._get_json(key)

    async def set_anime_meta(self, anilist_id: int, data: dict, ttl: int = settings.redis_anime_ttl):
        key = self._key("anime", str(anilist_id))
        await self._set_json(key, data, ttl)

    async def check_rate_limit(self, ip: str, limit: int, window: int = 60) -> tuple[bool, int]:
        if not self._enabled or not self._redis:
            return True, 0
        key = self._key("rate_limit", ip)
        try:
            current = await self._redis.get(key)
            if current is None:
                await self._redis.setex(key, window, 1)
                return True, 1
            count = int(current)
            if count >= limit:
                return False, count
            await self._redis.incr(key)
            return True, count + 1
        except Exception as e:
            log.warning("Rate limit check failed", error=str(e))
            return True, 0

    async def _get_json(self, key: str) -> Optional[Any]:
        if not self._enabled or not self._redis:
            return None
        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            log.warning("Cache read failed", key=key, error=str(e))
        return None

    async def _set_json(self, key: str, value: Any, ttl: int):
        if not self._enabled or not self._redis:
            return
        try:
            data = json.dumps(value, default=str)
            await self._redis.setex(key, ttl, data)
        except Exception as e:
            log.warning("Cache write failed", key=key, error=str(e))

    async def clear_pattern(self, pattern: str):
        if not self._enabled or not self._redis:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            log.warning("Cache clear failed", pattern=pattern, error=str(e))

    @property
    def enabled(self) -> bool:
        return self._enabled


_cache_instance: Optional[RedisCache] = None


async def get_cache() -> RedisCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = RedisCache()
        await _cache_instance.connect()
    return _cache_instance
