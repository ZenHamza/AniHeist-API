# path: consumet_api/pulsar.py
"""
Pulsar server scraper — Anivexa's "Pulsar" provider.
Simple URL pattern: https://megaplay.buzz/stream/ani/{anilist_id}/{ep_num}/{sub|dub}
"""
from typing import Optional

from src.extractors.video import VideoExtractor
from src.utils.http_client import HttpClientPool
from src.utils.logger import get_logger

log = get_logger(__name__)

BASE = "https://megaplay.buzz"


class Pulsar:
    def __init__(self, http_pool: Optional[HttpClientPool] = None):
        self.http_pool = http_pool or HttpClientPool(max_sessions=5)

    async def get_stream_url(self, anilist_id: str, episode: int, audio: str = "sub") -> Optional[str]:
        """Get stream URL from megaplay.buzz."""
        url = f"{BASE}/stream/ani/{anilist_id}/{episode}/{audio}"
        session_wrapper = await self.http_pool.get_session()
        try:
            resp = await session_wrapper.get(
                url,
                headers={
                    "Referer": f"{BASE}/",
                    "Origin": BASE,
                },
            )
            if resp.status_code == 200:
                urls = VideoExtractor.extract_from_html(resp.text)
                if urls:
                    log.info("Pulsar stream found via HTML extraction", url=urls[0][:60])
                    return urls[0]

            return None
        except Exception as e:
            log.warning("Pulsar stream error", error=str(e))
            return None
        finally:
            await session_wrapper.close()

    async def search(self, query: str) -> list[dict]:
        return []
