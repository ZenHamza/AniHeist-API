# path: consumet_api/animepahe.py
"""
Animepahe scraper — Anivexa's "Astra" provider.
Extracts HLS streams from animepahe.pw using session-based API.
"""
import re
import json
from typing import Optional
from urllib.parse import urljoin

from src.extractors.video import VideoExtractor
from src.utils.http_client import HttpClientPool
from src.utils.logger import get_logger

log = get_logger(__name__)

BASE = "https://animepahe.pw"
API = "https://animepahe.pw/api"
REFERER = "https://animepahe.pw/"


class AnimePahe:
    def __init__(self, http_pool: Optional[HttpClientPool] = None):
        self.http_pool = http_pool or HttpClientPool(max_sessions=5)
        self.session = None
        self._session_data = None

    async def get_episodes(self, provider_id: str) -> list[dict]:
        """Get episode list for an anime by animepahe provider ID."""
        session_wrapper = await self.http_pool.get_session()
        try:
            resp = await session_wrapper.get(
                f"{API}?m=release&id={provider_id}&sort=episode_asc&page=1",
                headers={"Referer": REFERER},
            )
            if resp.status_code != 200:
                log.warning("AnimePahe episodes API failed", status=resp.status_code)
                return []

            data = resp.json() if hasattr(resp, "json") else json.loads(resp.text)
            episodes = []
            for ep in data.get("data", []):
                episodes.append({
                    "number": ep.get("episode"),
                    "title": ep.get("title"),
                    "session": ep.get("session"),
                    "snapshot": ep.get("snapshot"),
                })
            return episodes
        except Exception as e:
            log.warning("AnimePahe episodes error", error=str(e))
            return []
        finally:
            await session_wrapper.close()

    async def get_stream_url(self, provider_id: str, episode: int) -> Optional[str]:
        """Get HLS stream URL for a specific episode."""
        episodes = await self.get_episodes(provider_id)
        target = None
        for ep in episodes:
            if ep["number"] == episode:
                target = ep
                break

        if not target or not target.get("session"):
            log.warning("Episode session not found", provider_id=provider_id, episode=episode)
            return None

        session = target["session"]
        session_wrapper = await self.http_pool.get_session()
        try:
            resp = await session_wrapper.get(
                f"{API}?m=links&id={provider_id}&session={session}&p=cyber",
                headers={"Referer": REFERER},
            )
            if resp.status_code != 200:
                return None

            data = resp.json() if hasattr(resp, "json") else json.loads(resp.text)
            for kval, kval_data in data.get("data", {}).items():
                for item in kval_data:
                    # Look for the best quality
                    url = item.get("links", {}).get("src")
                    if url:
                        log.info("AnimePahe stream found", episode=episode, quality=kval)
                        return VideoExtractor.clean_url(url)

            # Fallback: extract from HTML if API returns HTML
            urls = VideoExtractor.extract_from_html(resp.text)
            if urls:
                return urls[0]

            return None
        except Exception as e:
            log.warning("AnimePahe stream error", error=str(e))
            return None
        finally:
            await session_wrapper.close()

    async def search(self, query: str) -> list[dict]:
        """Search anime on animepahe."""
        session_wrapper = await self.http_pool.get_session()
        try:
            resp = await session_wrapper.get(
                f"{API}?m=search&q={query}",
                headers={"Referer": REFERER},
            )
            if resp.status_code != 200:
                return []

            data = resp.json() if hasattr(resp, "json") else json.loads(resp.text)
            results = []
            for item in data.get("data", []):
                results.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "type": item.get("type"),
                    "episodes": item.get("episodes"),
                    "status": item.get("status"),
                    "session": item.get("session"),
                })
            return results
        except Exception as e:
            log.warning("AnimePahe search error", error=str(e))
            return []
        finally:
            await session_wrapper.close()
