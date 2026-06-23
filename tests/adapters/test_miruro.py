# path: tests/adapters/test_miruro.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import asyncio

from src.adapters.miruro import MiruroAdapter
from src.models.stream import (
    StreamResult,
    SourceTimeoutError,
    CloudflareBlockError,
    ParserError,
    AnimeNotFoundError,
)


@pytest.fixture
def adapter(mock_browser_pool):
    return MiruroAdapter(browser_pool=mock_browser_pool)


@pytest.mark.asyncio
async def test_miruro_captures_m3u8_via_network(adapter, mock_browser_pool, mock_page):
    mock_page.content.return_value = "<html><body>Miruro watch page</body></html>"
    mock_browser_pool.set_next_page(mock_page)

    with patch.object(adapter, "_extract_video_from_page", new=AsyncMock(
        return_value="https://kiwi-cdn.example.com/stream/abc/playlist.m3u8"
    )):
        with patch.object(adapter, "_extract_subtitles_from_page", new=AsyncMock(return_value=[])):
            result = await adapter.get_video_url("21", 1)

    assert isinstance(result, StreamResult)
    assert result.url == "https://kiwi-cdn.example.com/stream/abc/playlist.m3u8"
    assert result.source == "miruro"


@pytest.mark.asyncio
async def test_miruro_handles_timeout(adapter, mock_browser_pool, mock_page):
    async def failing_goto(*args, **kwargs):
        raise asyncio.TimeoutError("Navigation timed out")

    mock_page.goto = failing_goto
    mock_page.content.return_value = "<html><body>Miruro page</body></html>"
    mock_browser_pool.set_next_page(mock_page)

    with pytest.raises(SourceTimeoutError):
        await adapter.get_video_url("21", 1)


@pytest.mark.asyncio
async def test_miruro_handles_redirect_away(adapter, mock_browser_pool, mock_page):
    type(mock_page).url = PropertyMock(return_value="https://www.miruro.to/login")
    mock_page.title.return_value = "Watch Test Anime"
    mock_page.content.return_value = "<html><body>Login page</body></html>"
    mock_browser_pool.set_next_page(mock_page)

    with pytest.raises(AnimeNotFoundError):
        await adapter.get_video_url("21", 1)


@pytest.mark.asyncio
async def test_miruro_handles_no_video(adapter, mock_browser_pool, mock_page):
    mock_page.content.return_value = "<html><body>Anime page without player</body></html>"
    mock_browser_pool.set_next_page(mock_page)

    with patch.object(adapter, "_extract_video_from_page", new=AsyncMock(return_value=None)):
        with patch.object(adapter, "_extract_from_ssr_config", new=AsyncMock(return_value=None)):
            with patch.object(adapter, "_extract_video_from_iframe", new=AsyncMock(return_value=None)):
                with patch.object(adapter, "_extract_subtitles_from_page", new=AsyncMock(return_value=[])):
                    with pytest.raises(ParserError):
                        await adapter.get_video_url("21", 1)


@pytest.mark.asyncio
async def test_miruro_extracts_from_ssr_config(adapter):
    mock_page = AsyncMock()
    mock_page.evaluate = AsyncMock(
        return_value="https://provider.example.com/stream.m3u8"
    )

    result = await adapter._extract_from_ssr_config(mock_page)
    assert result == "https://provider.example.com/stream.m3u8"


@pytest.mark.asyncio
async def test_miruro_search(adapter, mock_browser_pool, mock_page):
    mock_browser_pool.set_next_page(mock_page)
    results = await adapter.search("one piece")
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_miruro_check_health(adapter, mock_browser_pool, mock_page):
    mock_browser_pool.set_next_page(mock_page)
    healthy = await adapter.check_health()
    assert healthy is True
