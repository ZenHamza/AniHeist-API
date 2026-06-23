# path: tests/adapters/test_anizone.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bs4 import BeautifulSoup

from src.adapters.anizone import AniZoneAdapter
from src.models.stream import (
    StreamResult,
    CloudflareBlockError,
    ParserError,
    AnimeNotFoundError,
    EpisodeNotFoundError,
    SourceTimeoutError,
)


def _make_episode_page_html(m3u8_url: str = "https://cdn.example.com/stream/master.m3u8") -> str:
    return f"""<html><body>
    <media-player src="{m3u8_url}">
        <track kind="subtitles" label="English" src="https://subs.example.com/en.vtt" srclang="en"/>
    </media-player>
    </body></html>"""


@pytest.mark.asyncio
async def test_anizone_extracts_video_url(mock_http_pool):
    adapter = AniZoneAdapter(http_pool=mock_http_pool)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = _make_episode_page_html("https://cdn.example.com/stream/master.m3u8")
    session_wrapper = MagicMock()
    session_wrapper.get = AsyncMock(return_value=mock_resp)
    session_wrapper.close = AsyncMock()
    mock_http_pool.get_session = AsyncMock(return_value=session_wrapper)
    adapter.http_pool = mock_http_pool

    result = await adapter.get_video_url("7l26fe8l", 1)

    assert isinstance(result, StreamResult)
    assert result.url == "https://cdn.example.com/stream/master.m3u8"
    assert result.source == "anizone"
    assert result.format == "hls"
    assert len(result.subtitles) == 1


@pytest.mark.asyncio
async def test_anizone_handles_403(mock_http_pool):
    adapter = AniZoneAdapter(http_pool=mock_http_pool)
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    session_wrapper = MagicMock()
    session_wrapper.get = AsyncMock(return_value=mock_resp)
    session_wrapper.close = AsyncMock()
    mock_http_pool.get_session = AsyncMock(return_value=session_wrapper)
    adapter.http_pool = mock_http_pool

    with pytest.raises(CloudflareBlockError):
        await adapter.get_video_url("test-id", 1)


@pytest.mark.asyncio
async def test_anizone_handles_404(mock_http_pool):
    adapter = AniZoneAdapter(http_pool=mock_http_pool)
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    session_wrapper = MagicMock()
    session_wrapper.get = AsyncMock(return_value=mock_resp)
    session_wrapper.close = AsyncMock()
    mock_http_pool.get_session = AsyncMock(return_value=session_wrapper)
    adapter.http_pool = mock_http_pool

    with pytest.raises(EpisodeNotFoundError):
        await adapter.get_video_url("test-id", 1)


@pytest.mark.asyncio
async def test_anizone_handles_no_video(mock_http_pool):
    adapter = AniZoneAdapter(http_pool=mock_http_pool)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body>No player here</body></html>"
    session_wrapper = MagicMock()
    session_wrapper.get = AsyncMock(return_value=mock_resp)
    session_wrapper.close = AsyncMock()
    mock_http_pool.get_session = AsyncMock(return_value=session_wrapper)
    adapter.http_pool = mock_http_pool

    with pytest.raises(ParserError):
        await adapter.get_video_url("test-id", 1)


@pytest.mark.asyncio
async def test_anizone_search(mock_http_pool):
    adapter = AniZoneAdapter(http_pool=mock_http_pool)
    results = await adapter.search("naruto")
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_anizone_check_health(mock_http_pool):
    adapter = AniZoneAdapter(http_pool=mock_http_pool)
    healthy = await adapter.check_health()
    assert healthy is True


@pytest.mark.asyncio
async def test_anizone_extract_from_animepahe_chain(mock_http_pool):
    adapter = AniZoneAdapter(http_pool=mock_http_pool)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        '<html><script>var src = "https://cdn.example.com/stream/123/playlist.m3u8";</script></html>'
    )
    session_wrapper = MagicMock()
    session_wrapper.get = AsyncMock(return_value=mock_resp)

    soup = BeautifulSoup(
        '<html><iframe src="https://animepahe.pw/embed/test"></iframe></html>',
        "lxml"
    )

    result = await adapter._extract_from_animepahe_chain(soup, session_wrapper)
    assert result == "https://cdn.example.com/stream/123/playlist.m3u8"
