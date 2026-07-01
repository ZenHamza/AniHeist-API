# path: src/adapters/unified.py
"""
Unified streaming adapter combining multiple backends:
1. Miruro Pipe API (fast, no browser, multiple providers)
2. Consumet API (AnimeSaturn, Hianime, etc.)
3. Playwright (fallback for Miruro)
"""
from typing import Optional

from src.adapters.base import BaseAdapter
from src.adapters.miruro import MiruroAdapter
from src.adapters.reanime import ReAnimeAdapter
from src.adapters.anikoto_scraper import get_anikoto_stream
from src.models.stream import StreamResult, ParserError
from src.utils.logger import get_logger
from consumet_api.miruro_pipe import MiruroPipe
from src.proxy_pool import get_proxy_pool

log = get_logger(__name__)


class UnifiedAdapter(BaseAdapter):
    """
    Master adapter that tries multiple backends in order:
    1. Miruro Pipe API (instant, 3+ providers)
    2. Consumet API (AnimeSaturn via Node.js)
    3. Playwright Miruro (fallback)
    """

    def __init__(self, browser_pool=None):
        super().__init__()
        self._proxy_pool = None
        self.miruro_pipe = MiruroPipe(proxy_pool=None)
        self.miruro_pw = MiruroAdapter(browser_pool=browser_pool)
        self.reanime = ReAnimeAdapter()

    async def _ensure_proxy_pool(self):
        if self._proxy_pool is None:
            try:
                self._proxy_pool = await get_proxy_pool()
                self.miruro_pipe._proxy_pool = self._proxy_pool
                log.info("Proxy pool initialized", nodes=len(self._proxy_pool.nodes))
            except Exception as e:
                log.warning("Failed to initialize proxy pool", error=str(e))
        

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        anilist_id = int(anime_id) if anime_id.isdigit() else 0
        category = "dub" if kwargs.get("dub") else "sub"
        provider = kwargs.get("provider") or ""
        source = kwargs.get("source") or ""

        await self._ensure_proxy_pool()
        errors = []

        preferred = None
        if provider:
            preferred = [p.strip() for p in provider.split(",")]

        # When a specific Miruro provider is requested, skip Anikoto and go straight to Miruro
        if provider and source in ("", "miruro"):
            log.info("Trying Miruro pipe with specific provider", anime_id=anilist_id, episode=episode, provider=preferred)
            try:
                return await self.miruro_pipe.get_stream(
                    anilist_id, episode, category=category, preferred_providers=preferred
                )
            except Exception as e:
                errors.append(f"miruro_pipe: {e}")
                log.warning("Miruro pipe failed", error=str(e))
            raise ParserError(f"All providers failed: {'; '.join(errors)}")

        # 1. Miruro Pipe (primary - direct HLS when CDN works)
        if anilist_id > 0 and source in ("", "miruro"):
            try:
                log.info("Trying Miruro pipe", anime_id=anilist_id, episode=episode)
                result = await self.miruro_pipe.get_stream(
                    anilist_id, episode, category=category
                )
                return result
            except Exception as e:
                errors.append(f"miruro_pipe: {e}")
                log.warning("Miruro pipe failed", error=str(e))

        # 2. Anikoto (fallback - vidtube/megaplay embed player)
        if anilist_id > 0 and source in ("", "anikoto"):
            try:
                log.info("Trying Anikoto", anime_id=anilist_id, episode=episode)
                return await get_anikoto_stream(anilist_id, episode, dub=kwargs.get("dub", False))
            except Exception as e:
                errors.append(f"anikoto: {e}")
                log.warning("Anikoto failed", error=str(e))

        # 3. ReAnime API (reanime.to + flixcloud.cc) - only when explicitly requested (Cloudflare-blocked)
        if source == "reanime":
            try:
                log.info("Trying ReAnime", anime_id=anime_id, episode=episode)
                return await self.reanime.get_video_url(anime_id, episode, **kwargs)
            except Exception as e:
                errors.append(f"reanime: {e}")
                log.warning("ReAnime failed", error=str(e))

        # 3. Playwright Miruro (last resort)
        if source in ("", "playwright"):
            try:
                log.info("Trying Miruro Playwright", anime_id=anime_id, episode=episode)
                return await self.miruro_pw.get_video_url(anime_id, episode, **kwargs)
            except Exception as e:
                errors.append(f"miruro_pw: {e}")
                log.warning("Miruro Playwright failed", error=str(e))

        raise ParserError(f"All providers failed: {'; '.join(errors)}")

    async def search(self, query: str) -> list[dict]:
        results = []
        try:
            import httpx
            anilist_q = """
                query ($q: String) {
                    Page(page: 1, perPage: 15) {
                        media(search: $q, type: ANIME) {
                            id
                            title { romaji english }
                            coverImage { large }
                            episodes
                            format
                            averageScore
                            seasonYear
                            status
                            genres
                            description
                        }
                    }
                }
            """
            resp = httpx.post("https://graphql.anilist.co",
                json={"query": anilist_q, "variables": {"q": query}},
                timeout=10)
            if resp.status_code == 200:
                for m in resp.json().get("data", {}).get("Page", {}).get("media", []):
                    t = m.get("title", {})
                    desc = (m.get("description") or "")[:200]
                    import re
                    desc_clean = re.sub(r"<[^>]+>", "", desc)
                    results.append({
                        "id": m["id"],
                        "title": t.get("english") or t.get("romaji") or "",
                        "cover_image": m.get("coverImage", {}).get("large"),
                        "episodes": m.get("episodes"),
                        "format": m.get("format"),
                        "score": m.get("averageScore"),
                        "year": m.get("seasonYear"),
                        "status": m.get("status"),
                        "genres": m.get("genres", []),
                        "description": desc_clean[:200],
                    })
        except Exception as e:
            log.warning("AniList search failed", error=str(e))

        if not results:
            results = await self.miruro_pw.search(query)

        return results

    async def check_health(self) -> bool:
        """Check if Miruro pipe API is accessible."""
        try:
            from urllib.request import urlopen
            urlopen("https://www.miruro.tv", timeout=10)
            return True
        except Exception:
            return False
