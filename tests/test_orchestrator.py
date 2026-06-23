# path: tests/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator import Orchestrator
from src.models.stream import StreamResult, AllSourcesExhaustedError, ValidationError


@pytest.fixture
async def orchestrator():
    orch = Orchestrator()
    with patch.object(orch, "initialize", new=AsyncMock()):
        orch._initialized = True
        orch._adapters = {}
        yield orch


@pytest.mark.asyncio
async def test_get_stream_success(orchestrator):
    mock_adapter = MagicMock()
    mock_adapter.get_video_url = AsyncMock(
        return_value=StreamResult(
            url="https://example.com/stream.m3u8",
            source="miruro",
            format="hls",
        )
    )
    orchestrator._adapters = {"miruro": mock_adapter}

    with patch.object(orchestrator.fallback_manager, "get_stream", new=AsyncMock(
        return_value=StreamResult(
            url="https://example.com/stream.m3u8",
            source="miruro",
            format="hls",
        )
    )):
        result = await orchestrator.get_stream(anime_id=21, episode=1)

    assert result.url == "https://example.com/stream.m3u8"
    assert result.source == "miruro"


@pytest.mark.asyncio
async def test_get_stream_invalid_anime_id(orchestrator):
    with pytest.raises(ValidationError):
        await orchestrator.get_stream(anime_id=0, episode=1)

    with pytest.raises(ValidationError):
        await orchestrator.get_stream(anime_id=-1, episode=1)


@pytest.mark.asyncio
async def test_get_stream_invalid_episode(orchestrator):
    with pytest.raises(ValidationError):
        await orchestrator.get_stream(anime_id=21, episode=0)

    with pytest.raises(ValidationError):
        await orchestrator.get_stream(anime_id=21, episode=-5)


@pytest.mark.asyncio
async def test_get_stream_all_sources_fail(orchestrator):
    with patch.object(
        orchestrator.fallback_manager,
        "get_stream",
        AsyncMock(side_effect=AllSourcesExhaustedError("All sources failed")),
    ):
        with pytest.raises(AllSourcesExhaustedError):
            await orchestrator.get_stream(anime_id=99999, episode=1)


@pytest.mark.asyncio
async def test_search_success(orchestrator):
    mock_adapter = MagicMock()
    mock_adapter.search = AsyncMock(
        return_value=[{"id": "21", "title": "One Piece", "source": "miruro"}]
    )
    with patch.object(
        orchestrator, "_adapters", {"miruro": mock_adapter}
    ):
        with patch.object(orchestrator, "_initialized", True):
            results = await orchestrator.search("naruto")
            assert isinstance(results, list)
            assert len(results) > 0


@pytest.mark.asyncio
async def test_search_invalid_query(orchestrator):
    with pytest.raises(ValidationError):
        await orchestrator.search("x")

    with pytest.raises(ValidationError):
        await orchestrator.search("")


@pytest.mark.asyncio
async def test_get_health(orchestrator):
    with patch.object(orchestrator, "_initialized", True):
        with patch.object(orchestrator, "_adapters", {}):
            health = await orchestrator.get_health()
            assert "status" in health
            assert "fallback_manager" in health


@pytest.mark.asyncio
async def test_reset_fallback(orchestrator):
    with patch.object(orchestrator.fallback_manager, "reset_source", new=AsyncMock()) as mock_reset:
        await orchestrator.reset_fallback("anidb")
        mock_reset.assert_called_once_with("anidb")

    with patch.object(orchestrator.fallback_manager, "reset_all", new=AsyncMock()) as mock_reset_all:
        await orchestrator.reset_fallback()
        mock_reset_all.assert_called_once()
