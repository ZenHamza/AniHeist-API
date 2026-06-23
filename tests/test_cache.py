# path: tests/test_cache.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.cache.redis_cache import RedisCache, get_cache


@pytest.fixture
def cache():
    return RedisCache(redis_url="redis://localhost:6379/0")


@pytest.mark.asyncio
async def test_connect_disconnect(cache):
    with patch.object(cache, "_redis", None):
        assert cache._enabled is True


@pytest.mark.asyncio
async def test_key_generation(cache):
    stream_key = cache._key("stream", "21", "1")
    assert stream_key == "stream:v2:21:1"

    health_key = cache._key("health", "anidb")
    assert health_key == "source_health:anidb"

    search_key = cache._key("search", "naruto")
    assert search_key == "search:naruto"

    anime_key = cache._key("anime", "21")
    assert anime_key == "anime_meta:21"


@pytest.mark.asyncio
async def test_get_set_stream(cache):
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._enabled = True

    mock_redis.get = AsyncMock(return_value='{"url": "https://example.com/stream.m3u8", "source": "miruro"}')

    result = await cache.get_stream(21, 1)

    assert result is not None
    assert result["url"] == "https://example.com/stream.m3u8"
    assert result["source"] == "miruro"


@pytest.mark.asyncio
async def test_set_stream(cache):
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._enabled = True
    mock_redis.setex = AsyncMock()

    data = {
        "url": "https://example.com/stream.m3u8",
        "source": "miruro",
        "format": "hls",
    }

    await cache.set_stream(21, 1, data, ttl=600)

    mock_redis.setex.assert_called_once()
    args = mock_redis.setex.call_args[0]
    assert args[0] == "stream:v2:21:1"
    assert isinstance(args[1], int)
    assert args[1] == 600


@pytest.mark.asyncio
async def test_cache_miss_returns_none(cache):
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._enabled = True
    mock_redis.get = AsyncMock(return_value=None)

    result = await cache.get_stream(21, 999)
    assert result is None


@pytest.mark.asyncio
async def test_cache_disabled(cache):
    cache._enabled = False
    result = await cache.get_stream(21, 1)
    assert result is None


@pytest.mark.asyncio
async def test_rate_limit_within_bounds(cache):
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._enabled = True
    mock_redis.get = AsyncMock(return_value=None)

    allowed, count = await cache.check_rate_limit("127.0.0.1", 30)
    assert allowed is True


@pytest.mark.asyncio
async def test_rate_limit_exceeded(cache):
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._enabled = True
    mock_redis.get = AsyncMock(return_value="30")

    allowed, count = await cache.check_rate_limit("127.0.0.1", 30)
    assert allowed is False
    assert count == 30


@pytest.mark.asyncio
async def test_clear_pattern(cache):
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._enabled = True

    mock_redis.scan = AsyncMock(return_value=(0, ["stream:v2:21:1", "stream:v2:21:2"]))
    mock_redis.delete = AsyncMock()

    await cache.clear_pattern("stream:v2:*")

    mock_redis.delete.assert_called_once_with("stream:v2:21:1", "stream:v2:21:2")


@pytest.mark.asyncio
async def test_source_health_cache(cache):
    mock_redis = AsyncMock()
    cache._redis = mock_redis
    cache._enabled = True
    mock_redis.get = AsyncMock(return_value='{"status": "healthy"}')

    result = await cache.get_source_health("anidb")
    assert result is not None
    assert result["status"] == "healthy"
