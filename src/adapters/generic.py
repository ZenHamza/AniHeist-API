# path: src/adapters/generic.py
import re
from typing import Optional

from src.adapters.base import BaseAdapter
from src.models.stream import (
    StreamResult,
    SourceTimeoutError,
    ParserError,
)
from src.extractors.video import VideoExtractor
from src.utils.http_client import HttpClientPool
from src.utils.logger import get_logger

log = get_logger(__name__)


class GenericSiteAdapter(BaseAdapter):
    """
    Universal adapter for any anime streaming site.
    Uses curl_cffi for fast HTTP + regex m3u8 extraction.
    The .m3u8 URL pattern never changes — this is format-stable.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        episode_path: str = "/watch/{anime_id}",
        http_pool: Optional[HttpClientPool] = None,
    ):
        super().__init__()
        self.source_name = name
        self.base_url = base_url.rstrip("/")
        self.episode_path = episode_path
        self.http_pool = http_pool or HttpClientPool(max_sessions=5)

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        session_wrapper = await self.http_pool.get_session()
        try:
            ep_url = self.episode_path.replace("{anime_id}", anime_id).replace("{episode}", str(episode))
            page_url = f"{self.base_url}{ep_url}"
            self.log.info("Fetching %s page", self.source_name, url=page_url)

            try:
                resp = await session_wrapper.get(page_url, max_retries=2)
            except Exception as e:
                raise SourceTimeoutError(f"{self.source_name} request failed: {e}")

            if resp.status_code != 200:
                raise ParserError(f"{self.source_name} returned status {resp.status_code}")

            video_url = self._extract_m3u8(resp.text)

            if not video_url:
                video_url = await self._follow_iframes(resp.text, session_wrapper)

            if not video_url:
                raise ParserError(f"Could not extract video URL from {self.source_name}")

            video_format = "hls" if ".m3u8" in video_url.lower() else "mp4" if ".mp4" in video_url.lower() else "dash"
            headers = {"Referer": f"{self.base_url}/", "Origin": self.base_url}

            return StreamResult(url=video_url, source=self.source_name, format=video_format, headers=headers)

        finally:
            await session_wrapper.close()

    def _extract_m3u8(self, html: str) -> Optional[str]:
        urls = VideoExtractor.extract_from_html(html)
        if urls:
            return urls[0]

        js_pattern = re.compile(r'(?:src|url|file|stream)\s*[=:]\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', re.I)
        for match in js_pattern.finditer(html):
            url = match.group(1)
            if VideoExtractor.is_video_url(url):
                return VideoExtractor.clean_url(url)

        return None

    async def _follow_iframes(self, html: str, session_wrapper) -> Optional[str]:
        iframe_pattern = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']', re.I)
        for match in iframe_pattern.finditer(html):
            src = match.group(1)
            if "player" in src.lower() or "embed" in src.lower() or "stream" in src.lower():
                if not src.startswith("http"):
                    src = self.base_url + src
                try:
                    iframe_resp = await session_wrapper.get(src, max_retries=1)
                    if iframe_resp.status_code == 200:
                        url = self._extract_m3u8(iframe_resp.text)
                        if url:
                            return url
                except Exception:
                    continue
        return None

    async def search(self, query: str) -> list[dict]:
        return []

    async def check_health(self) -> bool:
        session_wrapper = await self.http_pool.get_session()
        try:
            resp = await session_wrapper.get(self.base_url, max_retries=1)
            return resp.status_code == 200
        except Exception:
            return False
        finally:
            await session_wrapper.close()
