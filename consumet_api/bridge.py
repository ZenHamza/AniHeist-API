# path: consumet_api/bridge.py
"""
Bridge between our Python API and the Node.js Consumet API server.
Proxies stream requests through the local Consumet server for providers
that the Python scrapers can't handle directly (Anti-bot, Cloudflare, etc).
"""
from typing import Optional
import httpx

from src.utils.logger import get_logger
from src.models.stream import StreamResult, ParserError

log = get_logger(__name__)

CONSUMET_BASE = "http://localhost:3099"
TIMEOUT = 30


class ConsumetBridge:
    """
    Proxies requests to the local Node.js Consumet API server.
    The Consumet server uses Puppeteer/Playwright internally to handle
    Cloudflare and anti-bot protections on streaming sites.
    """

    def __init__(self, base_url: str = CONSUMET_BASE):
        self.base_url = base_url

    async def search(self, provider: str, query: str) -> list[dict]:
        """Search anime on a specific provider."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(
                    f"{self.base_url}/search/{provider}",
                    params={"q": query, "page": 1},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("results", [])
                return []
        except Exception as e:
            log.warning("Consumet search failed", provider=provider, error=str(e))
            return []

    async def get_episodes(self, provider: str, anime_id: str) -> list[dict]:
        """Get episode list from a provider."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/info/{provider}/{anime_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("episodes", [])
                return []
        except Exception as e:
            log.warning("Consumet episodes failed", provider=provider, error=str(e))
            return []

    async def get_stream_url(self, provider: str, episode_id: str) -> tuple:
        """Get a stream URL and subtitles from a provider."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(f"{self.base_url}/watch/{provider}/{episode_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    sources = data.get("sources", [])
                    subtitles = data.get("subtitles", [])
                    
                    # Filter for English subtitles if available
                    en_subs = [s for s in subtitles if s.get("lang", "").lower().startswith("en")]
                    subs = en_subs if en_subs else subtitles
                    
                    if sources:
                        url = sources[0].get("url")
                        if url:
                            log.info(
                                "Consumet stream found",
                                provider=provider,
                                url=url[:60],
                                subs=len(subs),
                            )
                            return (url, subs)
            return (None, [])
        except Exception as e:
            log.warning("Consumet stream failed", provider=provider, error=str(e))
            return None

    async def get_providers(self) -> list[str]:
        """Get list of available providers from the Consumet server."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(self.base_url)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("providers", [])
                return []
        except Exception:
            return []
