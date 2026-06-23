# path: tests/test_fallback_manager.py
import pytest
from unittest.mock import AsyncMock, MagicMock
import time

from src.fallback_manager import FallbackManager, SourceState, SourceStatus
from src.models.stream import (
    StreamResult,
    AllSourcesExhaustedError,
    ScraperError,
    SourceTimeoutError,
)
from src.config import settings


@pytest.fixture
def fallback_manager():
    return FallbackManager(config={
        "circuit_breaker_threshold": 2,
        "circuit_breaker_timeout": 60,
        "max_retries_per_source": 1,
        "retry_base_delay": 0.1,
        "per_source_timeout": 5.0,
    })


@pytest.mark.asyncio
async def test_returns_first_successful_source(fallback_manager, mock_adapters):
    result = await fallback_manager.get_stream(mock_adapters, anime_id="21", episode=1)

    assert result.url == "https://anidb.example.com/stream/playlist.m3u8"
    assert result.source == "anidb"
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_fallback_to_secondary_when_primary_fails(fallback_manager, mock_adapter_anizone, mock_adapter_miruro):
    failing_adapter = MagicMock()
    failing_adapter.get_video_url = AsyncMock(side_effect=SourceTimeoutError("Timeout"))
    failing_adapter.search = AsyncMock(return_value=[])
    failing_adapter.check_health = AsyncMock(return_value=False)

    adapters = {
        "anidb": failing_adapter,
        "anizone": mock_adapter_anizone,
        "miruro": mock_adapter_miruro,
    }

    result = await fallback_manager.get_stream(adapters, anime_id="test", episode=1)

    assert result.source == "anizone"
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_all_sources_exhausted_raises_error(fallback_manager):
    adapters = {}
    for name in ["anidb", "anizone", "miruro"]:
        adapter = MagicMock()
        adapter.get_video_url = AsyncMock(side_effect=ScraperError("Failed"))
        adapters[name] = adapter

    with pytest.raises(AllSourcesExhaustedError):
        await fallback_manager.get_stream(adapters, anime_id="test", episode=1)


@pytest.mark.asyncio
async def test_circuit_breaker_skips_dead_source(fallback_manager):
    manager = FallbackManager(config={
        "circuit_breaker_threshold": 1,
        "circuit_breaker_timeout": 60,
        "max_retries_per_source": 0,
        "retry_base_delay": 0.1,
        "per_source_timeout": 5.0,
    })

    failing_adapter = MagicMock()
    failing_adapter.get_video_url = AsyncMock(side_effect=ScraperError("Failed"))
    failing_adapter.search = AsyncMock(return_value=[])
    failing_adapter.check_health = AsyncMock(return_value=False)

    working_adapter = MagicMock()
    working_adapter.get_video_url = AsyncMock(
        return_value=StreamResult(url="https://ok.com/v.m3u8", source="anizone")
    )
    working_adapter.search = AsyncMock(return_value=[])
    working_adapter.check_health = AsyncMock(return_value=True)

    adapters_failing = {
        "anidb": failing_adapter,
        "anizone": working_adapter,
    }

    await manager.get_stream(adapters_failing, anime_id="t", episode=1)

    await manager.get_stream(adapters_failing, anime_id="t2", episode=1)

    health = manager.get_health_report()
    assert health["anidb"]["status"] == "dead"
    assert health["anizone"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_circuit_breaker_half_open(fallback_manager):
    manager = FallbackManager(config={
        "circuit_breaker_threshold": 1,
        "circuit_breaker_timeout": 0.1,
        "max_retries_per_source": 0,
        "retry_base_delay": 0.01,
        "per_source_timeout": 5.0,
    })

    failing_adapter = MagicMock()
    failing_adapter.get_video_url = AsyncMock(side_effect=ScraperError("Failed"))
    failing_adapter.search = AsyncMock(return_value=[])
    failing_adapter.check_health = AsyncMock(return_value=False)

    working_adapter = MagicMock()
    working_adapter.get_video_url = AsyncMock(
        return_value=StreamResult(url="https://ok.com/v.m3u8", source="anizone")
    )
    working_adapter.search = AsyncMock(return_value=[])
    working_adapter.check_health = AsyncMock(return_value=True)

    adapters = {
        "anidb": failing_adapter,
        "anizone": working_adapter,
    }

    await manager.get_stream(adapters, anime_id="t", episode=1)

    health = manager.get_health_report()
    assert health["anidb"]["status"] == "dead"

    time.sleep(0.15)

    manager._is_source_available(manager.sources[0])
    assert manager.sources[0].status == SourceStatus.DEGRADED


@pytest.mark.asyncio
async def test_health_report(fallback_manager, mock_adapters):
    await fallback_manager.get_stream(mock_adapters, anime_id="21", episode=1)
    health = fallback_manager.get_health_report()

    assert "anidb" in health
    assert "anizone" in health
    assert "miruro" in health
    assert health["anidb"]["status"] == "healthy"
    assert "failure_count" in health["anidb"]
    assert "total_requests" in health["anidb"]


@pytest.mark.asyncio
async def test_fallback_attempts_tracked(fallback_manager, mock_adapter_anizone, mock_adapter_miruro):
    failing_adapter = MagicMock()
    failing_adapter.get_video_url = AsyncMock(side_effect=ScraperError("ParserError"))
    failing_adapter.search = AsyncMock(return_value=[])
    failing_adapter.check_health = AsyncMock(return_value=False)

    adapters = {
        "anidb": failing_adapter,
        "anizone": mock_adapter_anizone,
        "miruro": mock_adapter_miruro,
    }

    result = await fallback_manager.get_stream(adapters, anime_id="test", episode=1)

    assert result.fallback_used is True
    assert result.fallback_attempts is not None
    assert len(result.fallback_attempts) == 1
    assert result.fallback_attempts[0].source == "anidb"
    assert "error" in result.fallback_attempts[0].error or result.fallback_attempts[0].error


@pytest.mark.asyncio
async def test_reset_source(fallback_manager):
    source = fallback_manager.sources[0]
    source.status = SourceStatus.DEAD
    source.failure_count = 10

    await fallback_manager.reset_source("anidb")
    assert source.status == SourceStatus.HEALTHY
    assert source.failure_count == 0
    assert source.circuit_open_until == 0.0
