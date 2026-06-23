# path: tests/adapters/test_anidb.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import asyncio

from src.adapters.anidb import AniDBAdapter
from src.models.stream import (
    StreamResult,
    SourceTimeoutError,
    CloudflareBlockError,
    ParserError,
    AnimeNotFoundError,
    EpisodeNotFoundError,
)


@pytest.fixture
def adapter(mock_browser_pool):
    return AniDBAdapter(browser_pool=mock_browser_pool)


@pytest.mark.asyncio
async def test_anidb_extracts_video_url(adapter, mock_browser_pool, mock_page):
    mock_page.title.return_value = "Death Note — Watch Online Free — AniDB"
    type(mock_page).url = PropertyMock(return_value="https://anidb.app/anime/death-note-1199")
    mock_browser_pool.set_next_page(mock_page)

    with patch.object(adapter, "_click_episode", new=AsyncMock()):
        with patch.object(adapter, "_extract_video_from_page", new=AsyncMock(
            return_value="https://hls.anidb.app/stream/abc123/master.m3u8"
        )):
            with patch.object(adapter, "_extract_subtitles_from_page", new=AsyncMock(return_value=[])):
                result = await adapter.get_video_url("death-note-1199", 1)

    assert isinstance(result, StreamResult)
    assert "master.m3u8" in result.url
    assert result.source == "anidb"
    assert result.format == "hls"


@pytest.mark.asyncio
async def test_anidb_handles_timeout(adapter, mock_browser_pool, mock_page):
    async def failing_goto(*args, **kwargs):
        raise asyncio.TimeoutError("Navigation timed out")

    mock_page.goto = failing_goto
    mock_page.title.return_value = "Death Note — AniDB"
    mock_browser_pool.set_next_page(mock_page)

    with pytest.raises(SourceTimeoutError):
        await adapter.get_video_url("death-note-1199", 1)


@pytest.mark.asyncio
async def test_anidb_handles_cloudflare(adapter, mock_browser_pool, mock_page):
    mock_page.title.return_value = "Just a moment..."
    mock_browser_pool.set_next_page(mock_page)

    with patch.object(adapter, "_wait_for_cloudflare", new=AsyncMock(return_value=False)):
        with pytest.raises(CloudflareBlockError):
            await adapter.get_video_url("death-note-1199", 1)


@pytest.mark.asyncio
async def test_anidb_handles_no_video_found(adapter, mock_browser_pool, mock_page):
    mock_page.title.return_value = "Death Note — AniDB"
    type(mock_page).url = PropertyMock(return_value="https://anidb.app/anime/death-note-1199")
    mock_browser_pool.set_next_page(mock_page)

    with patch.object(adapter, "_click_episode", new=AsyncMock()):
        with patch.object(adapter, "_extract_video_from_page", new=AsyncMock(return_value=None)):
            with patch.object(adapter, "_extract_video_from_iframe", new=AsyncMock(return_value=None)):
                with patch.object(adapter, "_extract_subtitles_from_page", new=AsyncMock(return_value=[])):
                    with pytest.raises(ParserError):
                        await adapter.get_video_url("death-note-1199", 1)


@pytest.mark.asyncio
async def test_anidb_search(adapter, mock_browser_pool, mock_page):
    mock_page.title.return_value = "Search — AniDB"
    mock_browser_pool.set_next_page(mock_page)
    results = await adapter.search("naruto")
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_anidb_check_health(adapter, mock_browser_pool, mock_page):
    mock_page.title.return_value = "AniDB — Watch Anime Online Free in HD"
    mock_browser_pool.set_next_page(mock_page)
    with patch.object(adapter, "_wait_for_cloudflare", new=AsyncMock(return_value=True)):
        healthy = await adapter.check_health()
        assert healthy is True
