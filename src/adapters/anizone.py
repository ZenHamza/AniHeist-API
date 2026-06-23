# path: src/adapters/anizone.py
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.adapters.base import BaseAdapter
from src.models.stream import (
    StreamResult,
    CloudflareBlockError,
    ParserError,
    AnimeNotFoundError,
    EpisodeNotFoundError,
    SourceTimeoutError,
)
from src.extractors.video import VideoExtractor
from src.extractors.subtitles import SubtitleExtractor
from src.utils.http_client import HttpClientPool
from src.utils.logger import get_logger
from src.config import settings

log = get_logger(__name__)


class AniZoneAdapter(BaseAdapter):
    """
    Adapter for anizone.to.
    Uses curl_cffi with Chrome TLS impersonation for Cloudflare bypass.
    AniZone uses Laravel + Livewire with Vidstack player.
    Episode URL format: /anime/{id}/{episode_number}
    """

    BASE_URL = settings.anizone_base_url

    def __init__(self, http_pool: Optional[HttpClientPool] = None):
        super().__init__()
        self.http_pool = http_pool or HttpClientPool(max_sessions=5)

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        session_wrapper = await self.http_pool.get_session()
        try:
            episode_url = f"{self.BASE_URL}/anime/{anime_id}/{episode}"
            self.log.info("Fetching AniZone episode page", url=episode_url, episode=episode)

            try:
                resp = await session_wrapper.get(episode_url, max_retries=2)
            except Exception as e:
                raise SourceTimeoutError(f"AniZone request failed: {e}")

            if resp.status_code == 403:
                raise CloudflareBlockError("AniZone Cloudflare block encountered")
            if resp.status_code == 404:
                raise EpisodeNotFoundError(f"Episode {episode} not found on AniZone (ID: {anime_id})")
            if resp.status_code != 200:
                raise ParserError(f"AniZone returned status {resp.status_code}")

            soup = BeautifulSoup(resp.text, "lxml")

            video_url = self._extract_video_from_media_player(soup)
            if not video_url:
                video_url = self._extract_video_from_html(soup)

            if not video_url:
                video_url = await self._extract_from_animepahe_chain(soup, session_wrapper)

            if not video_url:
                raise ParserError("Could not extract video URL from AniZone")

            subtitles = self._extract_subtitles(soup)

            headers = {
                "Referer": f"{self.BASE_URL}/",
                "Origin": self.BASE_URL,
            }

            video_format = "hls" if ".m3u8" in video_url.lower() else "mp4" if ".mp4" in video_url.lower() else "dash"

            return StreamResult(
                url=video_url,
                source="anizone",
                format=video_format,
                subtitles=subtitles,
                headers=headers,
            )

        finally:
            await session_wrapper.close()

    def _extract_video_from_media_player(self, soup: BeautifulSoup) -> Optional[str]:
        player = soup.find("media-player")
        if player:
            src = player.get("src")
            if src:
                return VideoExtractor.clean_url(src)

        player_video = soup.select_one("media-player[src], video[src], video source[src]")
        if player_video:
            src = player_video.get("src")
            if src:
                return VideoExtractor.clean_url(src)

        return None

    def _extract_video_from_html(self, soup: BeautifulSoup) -> Optional[str]:
        urls = VideoExtractor.extract_from_html(str(soup))
        if urls:
            return urls[0]

        vid_container = soup.find("div", class_=re.compile(r"player|video|stream", re.I))
        if vid_container:
            for attr in ["data-src", "data-url", "data-video", "data-stream"]:
                val = vid_container.get(attr)
                if val:
                    return VideoExtractor.clean_url(val)

        scripts = soup.find_all("script")
        for script in scripts:
            if script.string and ".m3u8" in script.string:
                urls = VideoExtractor.extract_from_html(script.string)
                if urls:
                    return urls[0]

        return None

    def _extract_subtitles(self, soup: BeautifulSoup) -> list[dict]:
        subtitles = []
        tracks = soup.find_all("track")
        for track in tracks:
            src = track.get("src")
            if not src:
                continue
            subtitles.append({
                "lang": track.get("srclang", "en") or "en",
                "label": track.get("label", "") or "",
                "url": src.strip(),
            })
        if not subtitles:
            subtitles = SubtitleExtractor.extract_from_html(soup, base_url=self.BASE_URL)
        return subtitles

    async def _extract_from_animepahe_chain(self, soup: BeautifulSoup, session_wrapper) -> Optional[str]:
        iframe = soup.find("iframe", src=re.compile(r"(player|embed|animepahe|animevibe|gogo)", re.I))
        if iframe:
            iframe_src = iframe.get("src")
            if iframe_src:
                iframe_src = urljoin(self.BASE_URL, iframe_src)
                try:
                    iframe_resp = await session_wrapper.get(iframe_src, max_retries=1)
                    if iframe_resp.status_code == 200:
                        urls = VideoExtractor.extract_from_html(iframe_resp.text)
                        if urls:
                            return urls[0]
                except Exception as e:
                    self.log.debug("Iframe fetch failed", error=str(e))
        return None

    async def search(self, query: str) -> list[dict]:
        results = []
        session_wrapper = await self.http_pool.get_session()
        try:
            search_url = f"{self.BASE_URL}/?s={query}"
            resp = await session_wrapper.get(search_url, max_retries=2)
            if resp.status_code != 200:
                return results

            soup = BeautifulSoup(resp.text, "lxml")
            anime_links = soup.find_all("a", href=re.compile(r"/anime/[a-z0-9]+$"))
            seen = set()
            for link in anime_links:
                href = link.get("href", "")
                anime_id = href.split("/anime/")[-1].strip("/")
                if anime_id and anime_id not in seen and re.match(r"^[a-z0-9]{6,12}$", anime_id):
                    seen.add(anime_id)
                    title_el = link.get("title") or link.text.strip()
                    title = title_el if isinstance(title_el, str) else str(title_el)
                    results.append({"id": anime_id, "title": title[:80], "source": "anizone"})
        except Exception as e:
            self.log.warning("AniZone search failed", error=str(e))
        finally:
            await session_wrapper.close()
        return results

    async def check_health(self) -> bool:
        session_wrapper = await self.http_pool.get_session()
        try:
            resp = await session_wrapper.get(self.BASE_URL, max_retries=1)
            return resp.status_code == 200
        except Exception:
            return False
        finally:
            await session_wrapper.close()
