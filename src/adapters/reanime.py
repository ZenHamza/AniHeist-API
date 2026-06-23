# path: src/adapters/reanime.py
"""
Adapter for the ReAnime-API (reanime.to + flixcloud.cc).
Returns HLS streams with English subtitles.
"""
from typing import Optional
import httpx

from src.adapters.base import BaseAdapter
from src.models.stream import StreamResult, ParserError
from src.utils.logger import get_logger

log = get_logger(__name__)

REANIME_BASE = "http://localhost:4000"


class ReAnimeAdapter(BaseAdapter):
    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        # We need a reanime.to slug, not an AniList ID
        # For now, try using the anime_id as a slug or search
        slug = anime_id
        if slug.isdigit():
            log.info("ReAnime adapter needs a slug, not numeric ID", anime_id=anime_id)
            raise ParserError("ReAnime adapter requires a reanime.to slug")

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # Get available servers
                r = await client.get(
                    f"{REANIME_BASE}/servers/{slug}/{episode}",
                    params={"anilist_id": int(anime_id) if anime_id.isdigit() else None}
                )
                if r.status_code != 200:
                    raise ParserError(f"ReAnime servers: {r.status_code}")
                
                data = r.json()
                servers = data.get("sub", [])
                if not servers:
                    servers = data.get("dub", [])
                if not servers:
                    raise ParserError("No servers available")
                
                # Try each server
                for server in servers:
                    link = server.get("dataLink", "")
                    if not link:
                        continue
                    
                    # Get stream URL via decrypt
                    r2 = await client.get(
                        f"{REANIME_BASE}/stream/from-link",
                        params={"link": link}
                    )
                    if r2.status_code == 200:
                        stream_data = r2.json()
                        url = stream_data.get("url")
                        if url:
                            subs = stream_data.get("subtitles", [])
                            sub_list = []
                            for s in subs:
                                sub_list.append({
                                    "lang": s.get("language", "en"),
                                    "label": s.get("language", "English"),
                                    "url": s.get("url", ""),
                                })
                            log.info("ReAnime stream found", url=url[:60], subs=len(sub_list))
                            return StreamResult(
                                url=url,
                                source="reanime",
                                format="hls",
                                subtitles=sub_list,
                                headers={"Referer": "https://reanime.to/"},
                            )
                
                raise ParserError("No working server found")
        except httpx.ConnectError:
            raise ParserError("ReAnime-API not running")

    async def search(self, query: str) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{REANIME_BASE}/search", params={"q": query, "limit": 10})
                if r.status_code == 200:
                    data = r.json()
                    results = []
                    for item in data if isinstance(data, list) else data.get("results", []):
                        results.append({
                            "id": item.get("slug", ""),
                            "title": item.get("title", ""),
                            "source": "reanime",
                        })
                    return results
        except Exception:
            pass
        return []

    async def check_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{REANIME_BASE}/")
                return r.status_code == 200
        except Exception:
            return False
