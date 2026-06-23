# path: src/adapters/denwa.py
"""
Adapter for denwa.streampeaker.org — AnimeSaturn's CDN.
No Cloudflare, no Referer restrictions, direct HLS playback.
"""
from typing import Optional
import httpx

from src.adapters.base import BaseAdapter
from src.models.stream import StreamResult, ParserError
from src.utils.logger import get_logger
from consumet_api.miruro_pipe import MiruroPipe

log = get_logger(__name__)

# Known anime name mappings for denwa CDN
# Format: URL pattern is https://srv{N}.denwa.streampeaker.org/DDL/ANIME/{NAME}/{ep}/playlist.m3u8
DENWA_BASE = "https://srv17.denwa.streampeaker.org/DDL/ANIME"


class DenwaAdapter(BaseAdapter):
    """
    Fetches HLS streams from denwa.streampeaker.org (AnimeSaturn's CDN).
    Uses Miruro pipe API to resolve AniList IDs to anime names.
    """

    def __init__(self):
        super().__init__()
        self.miruro = MiruroPipe()

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        anilist_id = int(anime_id) if anime_id.isdigit() else 0
        if not anilist_id:
            raise ParserError("Denwa adapter requires numeric AniList ID")

        # Get episode data from Miruro pipe API to find the anime title
        ep_data = await self.miruro.get_episodes(anilist_id)
        providers = ep_data.get("providers", {})
        
        # Extract anime title from any provider that has it
        anime_title = None
        for pname, pdata in providers.items():
            meta = pdata.get("meta", {})
            title = meta.get("title")
            if title:
                anime_title = title
                break
        
        if not anime_title:
            raise ParserError("Could not determine anime title for denwa CDN")

        # Convert title to URL-safe format (remove spaces, special chars)
        safe_title = "".join(c for c in anime_title if c.isalnum() or c in " -_").strip()
        safe_title = safe_title.replace(" ", "")
        
        if not safe_title:
            raise ParserError(f"Invalid anime title: {anime_title}")

        # Try multiple server numbers
        for server_num in [17, 10, 11, 12, 13, 14, 15, 16, 18, 19, 20]:
            url = f"https://srv{server_num}.denwa.streampeaker.org/DDL/ANIME/{safe_title}/{episode:02d}/playlist.m3u8"
            
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url, follow_redirects=True)
                    if resp.status_code == 200:
                        log.info("Denwa stream found", server=server_num, title=safe_title)
                        return StreamResult(
                            url=url,
                            source="denwa",
                            format="hls",
                            headers={"Referer": "https://animesaturn.cx/"},
                        )
            except Exception:
                continue

        raise ParserError(f"No working denwa server found for {anime_title} ep {episode}")

    async def search(self, query: str) -> list[dict]:
        return []

    async def check_health(self) -> bool:
        return True
