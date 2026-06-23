# path: src/adapters/consumet.py
"""
Adapter that proxies through the local Node.js Consumet API server.
Handles providers like AnimeSaturn, Hianime, etc. that our Python
scrapers can't handle directly due to anti-bot protection.
"""
from typing import Optional

from src.adapters.base import BaseAdapter
from src.models.stream import StreamResult, ParserError, AnimeNotFoundError
from src.utils.logger import get_logger
from consumet_api.bridge import ConsumetBridge

log = get_logger(__name__)


class ConsumetAdapter(BaseAdapter):
    """
    Uses the local Node.js Consumet API to scrape streaming providers.
    The Consumet server handles Puppeteer/anti-bot internally.
    """

    PROVIDERS = ["animesaturn", "animepahe", "hianime", "kickassanime"]

    def __init__(self, provider: str = "animesaturn", bridge: Optional[ConsumetBridge] = None):
        super().__init__()
        self.provider = provider
        self.bridge = bridge or ConsumetBridge()

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        # Resolve AniList ID to title first
        title = kwargs.get("title", "")
        if not title and anime_id.isdigit():
            try:
                import httpx
                q = """query ($id: Int) { Media(id: $id, type: ANIME) { title { romaji english } } }"""
                r = httpx.post("https://graphql.anilist.co",
                    json={"query": q, "variables": {"id": int(anime_id)}}, timeout=10)
                if r.status_code == 200:
                    t = r.json().get("data", {}).get("Media", {}).get("title", {})
                    title = t.get("english") or t.get("romaji") or anime_id
            except:
                title = anime_id
        
        results = await self.bridge.search(self.provider, title)

        if not results:
            raise AnimeNotFoundError(f"Anime not found on {self.provider}")

        # Try each result to find the one matching our anime_id
        target_id = None
        for r in results:
            rid = r.get("id", "")
            if rid and (anime_id in rid or rid in anime_id):
                target_id = rid
                break

        if not target_id:
            target_id = results[0].get("id", "")

        if not target_id:
            raise AnimeNotFoundError(f"No valid ID found on {self.provider}")

        # Get episode list
        episodes = await self.bridge.get_episodes(self.provider, target_id)
        if not episodes:
            raise ParserError(f"No episodes found on {self.provider}")

        # Find the target episode
        target_ep = None
        for ep in episodes:
            if ep.get("number") == episode:
                target_ep = ep
                break

        if not target_ep:
            target_ep = episodes[episode - 1] if episode <= len(episodes) else episodes[-1]

        ep_id = target_ep.get("id")
        if not ep_id:
            raise ParserError(f"Episode ID not found for episode {episode}")

        # Get stream URL
        url, subtitles = await self.bridge.get_stream_url(self.provider, ep_id)
        if not url:
            raise ParserError(f"No stream URL returned by {self.provider}")

        video_format = "hls" if ".m3u8" in url.lower() else "mp4"
        headers = {"Referer": "https://animesaturn.cx/", "Origin": "https://animesaturn.cx"}
        
        # Format subtitles for the response
        sub_list = []
        for s in subtitles:
            sub_list.append({
                "lang": s.get("lang", "en"),
                "label": s.get("label", s.get("lang", "English")),
                "url": s.get("url", ""),
            })
        
        return StreamResult(
            url=url,
            source=f"consumet/{self.provider}",
            format=video_format,
            subtitles=sub_list,
            headers=headers,
        )

    async def search(self, query: str) -> list[dict]:
        return await self.bridge.search(self.provider, query)

    async def check_health(self) -> bool:
        providers = await self.bridge.get_providers()
        return self.provider in providers
