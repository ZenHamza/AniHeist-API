# path: tests/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import Optional

from src.models.stream import StreamResult


class MockBrowserPool:
    def __init__(self):
        self._next_page = None

    def set_next_page(self, page_mock):
        self._next_page = page_mock

    async def acquire(self):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = self._next_page if self._next_page else self._default_page()

        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        mock_wrapper = MagicMock()
        mock_wrapper.browser = mock_browser
        mock_wrapper.close = AsyncMock()
        return mock_wrapper

    def _default_page(self):
        page = AsyncMock()
        page.content.return_value = "<html><body>Mock page</body></html>"
        page.evaluate.return_value = None
        page.title.return_value = "Mock Title"
        page.goto.return_value = MagicMock(status=200)
        page.wait_for_selector.return_value = MagicMock()
        page.wait_for_load_state.return_value = None
        page.on.return_value = None

        mock_element = AsyncMock()
        mock_element.click.return_value = None
        mock_element.get_attribute.return_value = None
        mock_element.inner_text.return_value = ""
        page.query_selector.return_value = mock_element
        page.query_selector_all.return_value = [mock_element]
        type(page).url = PropertyMock(return_value="https://www.miruro.to/watch/16498?ep=1")
        return page

    async def start(self):
        pass

    async def stop(self):
        pass


class MockHttpClientPool:
    def __init__(self):
        self._next_session = None

    def set_next_session(self, session_wrapper):
        self._next_session = session_wrapper

    async def get_session(self):
        if self._next_session:
            return self._next_session
        return self._default_session()

    def _default_session(self):
        mock_session = MagicMock()
        mock_session_wrapper = MagicMock()
        mock_session_wrapper.session = mock_session
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Mock response</body></html>"
        mock_resp.json.return_value = {}
        mock_session_wrapper.get = AsyncMock(return_value=mock_resp)
        mock_session_wrapper.post = AsyncMock(return_value=mock_resp)
        mock_session_wrapper.close = AsyncMock()
        return mock_session_wrapper

    async def close_all(self):
        pass


@pytest.fixture
def mock_browser_pool():
    return MockBrowserPool()


@pytest.fixture
def mock_http_pool():
    return MockHttpClientPool()


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.content.return_value = "<html><body>Mock page</body></html>"
    page.evaluate.return_value = None
    page.title.return_value = "Mock Title"
    page.goto.return_value = MagicMock(status=200)
    page.wait_for_selector.return_value = MagicMock()
    page.wait_for_load_state.return_value = None
    page.on.return_value = None

    mock_element = AsyncMock()
    mock_element.click.return_value = None
    mock_element.get_attribute.return_value = None
    mock_element.inner_text.return_value = ""
    page.query_selector.return_value = mock_element
    page.query_selector_all.return_value = [mock_element]

    page.on = MagicMock()
    type(page).url = PropertyMock(return_value="https://www.miruro.to/watch/16498?ep=1")
    return page


@pytest.fixture
def mock_adapter_anidb():
    adapter = MagicMock()
    adapter.get_video_url = AsyncMock(
        return_value=StreamResult(
            url="https://anidb.example.com/stream/playlist.m3u8",
            source="anidb",
            format="hls",
            subtitles=[{"lang": "en", "label": "English", "url": "https://subs.example.com/en.vtt"}],
            headers={"Referer": "https://anidb.app/"},
        )
    )
    adapter.search = AsyncMock(
        return_value=[{"id": "noragami-3819", "title": "Noragami", "source": "anidb"}]
    )
    adapter.check_health = AsyncMock(return_value=True)
    return adapter


@pytest.fixture
def mock_adapter_anizone():
    adapter = MagicMock()
    adapter.get_video_url = AsyncMock(
        return_value=StreamResult(
            url="https://anizone.example.com/stream/video.m3u8",
            source="anizone",
            format="hls",
            subtitles=[],
            headers={"Referer": "https://anizone.to/"},
        )
    )
    adapter.search = AsyncMock(
        return_value=[{"id": "1lbgjbgr", "title": "Test Anime", "source": "anizone"}]
    )
    adapter.check_health = AsyncMock(return_value=True)
    return adapter


@pytest.fixture
def mock_adapter_miruro():
    adapter = MagicMock()
    adapter.get_video_url = AsyncMock(
        return_value=StreamResult(
            url="https://miruro.example.com/stream/playlist.m3u8",
            source="miruro",
            format="hls",
            subtitles=[],
            headers={"Referer": "https://www.miruro.to/"},
        )
    )
    adapter.search = AsyncMock(
        return_value=[{"id": "21", "title": "One Piece", "source": "miruro"}]
    )
    adapter.check_health = AsyncMock(return_value=True)
    return adapter


@pytest.fixture
def mock_adapters(mock_adapter_anidb, mock_adapter_anizone, mock_adapter_miruro):
    return {
        "anidb": mock_adapter_anidb,
        "anizone": mock_adapter_anizone,
        "miruro": mock_adapter_miruro,
    }
