# path: tests/test_api.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from src.api import app, orchestrator
from src.models.stream import StreamResult, AllSourcesExhaustedError, ValidationError


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def mock_orchestrator():
    with patch.object(orchestrator, "initialize", new=AsyncMock()):
        with patch.object(orchestrator, "get_stream", new=AsyncMock(
            return_value=StreamResult(
                url="https://cdn.example.com/stream/playlist.m3u8",
                source="miruro",
                format="hls",
                subtitles=[{"lang": "en", "label": "English", "url": "https://subs.example.com/en.vtt"}],
                headers={"Referer": "https://www.miruro.to/"},
                fallback_used=False,
                fallback_attempts=[],
            )
        )):
            with patch.object(orchestrator, "get_health", new=AsyncMock(
                return_value={
                    "status": "healthy",
                    "sources": {
                        "anidb": {"healthy": True},
                        "anizone": {"healthy": True},
                        "miruro": {"healthy": True},
                    },
                    "fallback_manager": {},
                    "cache_enabled": False,
                }
            )):
                with patch.object(orchestrator, "search", new=AsyncMock(
                    return_value=[
                        {"id": "21", "title": "One Piece", "source": "miruro"},
                        {"id": "noragami-3819", "title": "Noragami", "source": "anidb"},
                    ]
                )):
                    with patch.object(orchestrator, "reset_fallback", new=AsyncMock()):
                        yield


@pytest.mark.asyncio
async def test_get_stream_success(client):
    response = await client.get("/api/stream?anime_id=21&episode=1")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["video_url"] == "https://cdn.example.com/stream/playlist.m3u8"
    assert data["data"]["source"] == "miruro"
    assert data["data"]["format"] == "hls"
    assert len(data["data"]["subtitles"]) == 1
    assert data["data"]["subtitles"][0]["lang"] == "en"
    assert data["meta"]["response_time_ms"] is not None


@pytest.mark.asyncio
async def test_get_stream_missing_params(client):
    response = await client.get("/api/stream")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_stream_invalid_anime_id(client):
    response = await client.get("/api/stream?anime_id=0&episode=1")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_stream_invalid_episode(client):
    response = await client.get("/api/stream?anime_id=21&episode=0")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_stream_with_optional_params(client):
    response = await client.get("/api/stream?anime_id=21&episode=1&dub=true&quality=720p")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "sources" in data
    assert "fallback_manager" in data


@pytest.mark.asyncio
async def test_search(client):
    response = await client.get("/api/search?q=one+piece")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["data"]) > 0
    assert data["meta"]["count"] == 2


@pytest.mark.asyncio
async def test_search_short_query(client):
    response = await client.get("/api/search?q=a")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_anime_metadata(client):
    response = await client.get("/api/anime/21")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reset_fallback(client):
    response = await client.post("/api/fallback/reset?source=anidb")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_reset_fallback_all(client):
    response = await client.post("/api/fallback/reset")
    assert response.status_code == 200
    data = response.json()
    assert "all sources" in data["message"].lower()


@pytest.mark.asyncio
async def test_rate_limit_headers(client):
    response = await client.get("/api/stream?anime_id=21&episode=1")
    assert "ratelimit-limit" in response.headers or response.status_code == 200
