# path: src/adapters/miruro.py
import asyncio
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.adapters.base import BaseAdapter
from src.models.stream import (
    StreamResult,
    SourceTimeoutError,
    CloudflareBlockError,
    ParserError,
    AnimeNotFoundError,
    EpisodeNotFoundError,
)
from src.extractors.video import VideoExtractor
from src.extractors.subtitles import SubtitleExtractor
from src.extractors.network import NetworkInterceptor
from src.utils.logger import get_logger
from src.config import settings

log = get_logger(__name__)


class MiruroAdapter(BaseAdapter):
    """
    Adapter for miruro.to.
    Uses Playwright with network interception to capture .m3u8/.mp4 streams.
    Miruro is a React SPA that tries multiple built-in providers.
    """

    BASE_URL = settings.miruro_base_url

    def __init__(self, browser_pool=None):
        super().__init__()
        self.browser_pool = browser_pool

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        browser_wrapper = await self.browser_pool.acquire()
        browser = browser_wrapper.browser
        context = None
        page = None
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            page = await context.new_page()

            watch_url = f"{self.BASE_URL}/watch/{anime_id}?ep={episode}"

            captured_m3u8 = []
            captured_mp4 = []

            async def handle_request(request):
                url = request.url.lower()
                if ".m3u8" in url:
                    captured_m3u8.append(request.url)
                elif ".mp4" in url and not any(ext in url for ext in [".js", ".css", ".png", ".jpg"]):
                    captured_mp4.append(request.url)

            page.on("request", handle_request)

            self.log.info("Navigating to Miruro watch page", url=watch_url, episode=episode)

            try:
                resp = await page.goto(watch_url, wait_until="domcontentloaded", timeout=settings.navigation_timeout)
            except Exception as e:
                raise SourceTimeoutError(f"Miruro page navigation timed out: {e}")

            page_title = await page.title()
            if "404" in page_title or page_title == "Miruro":
                raise AnimeNotFoundError(f"Anime ID '{anime_id}' not found on Miruro")

            current_url = page.url
            if "watch" not in current_url and "anime" not in current_url:
                raise AnimeNotFoundError(f"Redirected away from watch page: {current_url}")

            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

            await asyncio.sleep(4)

            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

            await asyncio.sleep(2)

            await page.wait_for_selector(
                "video, iframe[src*='player'], .player-container, #player",
                timeout=30000,
            )

            await asyncio.sleep(3)

            video_url = None
            if captured_m3u8:
                video_url = captured_m3u8[0]
                self.log.info("Captured m3u8 URL via network interception", url=video_url)
            elif captured_mp4:
                video_url = captured_mp4[0]
                self.log.info("Captured mp4 URL via network interception", url=video_url)

            if not video_url:
                video_url = await self._extract_video_from_page(page)

            if not video_url:
                video_url = await self._extract_from_ssr_config(page)

            if not video_url:
                video_url = await self._extract_video_from_iframe(page, context)

            if not video_url:
                raise ParserError("Could not extract video URL from Miruro page")

            soup = BeautifulSoup(await page.content(), "lxml")
            subtitles = SubtitleExtractor.extract_from_html(soup, base_url=self.BASE_URL)
            if not subtitles:
                subtitles = await self._extract_subtitles_from_page(page)

            headers = {
                "Referer": f"{self.BASE_URL}/",
                "Origin": self.BASE_URL,
            }

            video_format = "hls" if ".m3u8" in video_url.lower() else "mp4" if ".mp4" in video_url.lower() else "dash"

            return StreamResult(
                url=video_url,
                source="miruro",
                format=video_format,
                subtitles=subtitles,
                headers=headers,
            )

        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser_wrapper:
                await browser_wrapper.close()

    async def _extract_video_from_page(self, page) -> Optional[str]:
        try:
            video_src = await page.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    if (video && video.src) return video.src;
                    const source = document.querySelector('video source');
                    if (source && source.src) return source.src;
                    const iframe = document.querySelector('iframe[src*="player"], iframe[src*="embed"]');
                    if (iframe && iframe.src) return iframe.src;
                    const player = document.querySelector('[data-video-src], [data-stream], [data-url]');
                    if (player) {
                        return player.getAttribute('data-video-src')
                            || player.getAttribute('data-stream')
                            || player.getAttribute('data-url');
                    }
                    return null;
                }
            """)
            if video_src:
                return VideoExtractor.clean_url(video_src)
        except Exception as e:
            self.log.debug("DOM video extraction failed", error=str(e))
        return None

    async def _extract_from_ssr_config(self, page) -> Optional[str]:
        try:
            config = await page.evaluate("""
                () => {
                    try {
                        const config = window.__SSR_CONFIG__;
                        if (config && config.streaming && config.streaming.url) {
                            return config.streaming.url;
                        }
                        if (config && config.video && config.video.url) {
                            return config.video.url;
                        }
                        const providerOrder = config && config.providerOrder;
                        if (providerOrder && config.providers) {
                            for (const provider of providerOrder) {
                                if (config.providers[provider] && config.providers[provider].url) {
                                    return config.providers[provider].url;
                                }
                            }
                        }
                        return null;
                    } catch(e) {
                        return null;
                    }
                }
            """)
            if config:
                return VideoExtractor.clean_url(config)

            initial_state = await page.evaluate("""
                () => {
                    try {
                        return window.__INITIAL_STATE__ || window.__NEXT_DATA__ || null;
                    } catch(e) {
                        return null;
                    }
                }
            """)
            if initial_state:
                if isinstance(initial_state, dict):
                    for key in ["video", "stream", "episode", "data"]:
                        val = initial_state.get(key, {})
                        if isinstance(val, dict):
                            url = val.get("url") or val.get("src") or val.get("video_url") or val.get("stream_url")
                            if url:
                                return VideoExtractor.clean_url(url)
        except Exception as e:
            self.log.debug("SSR config extraction failed", error=str(e))
        return None

    async def _extract_video_from_iframe(self, page, context) -> Optional[str]:
        try:
            iframe_element = await page.query_selector("iframe[src]")
            if iframe_element:
                iframe_src = await iframe_element.get_attribute("src")
                if iframe_src:
                    iframe_src = urljoin(self.BASE_URL, iframe_src)
                    iframe_page = await context.new_page()
                    try:
                        await iframe_page.goto(iframe_src, wait_until="networkidle", timeout=15000)
                        await asyncio.sleep(2)
                        iframe_content = await iframe_page.content()
                        urls = VideoExtractor.extract_from_html(iframe_content)
                        if urls:
                            return urls[0]
                    finally:
                        await iframe_page.close()
        except Exception as e:
            self.log.debug("Iframe video extraction failed", error=str(e))
        return None

    async def _extract_subtitles_from_page(self, page) -> list[dict]:
        try:
            subs = await page.evaluate("""
                () => {
                    const tracks = document.querySelectorAll('track');
                    return Array.from(tracks).map(t => ({
                        lang: t.getAttribute('srclang') || 'en',
                        label: t.getAttribute('label') || '',
                        url: t.getAttribute('src') || ''
                    })).filter(t => t.url);
                }
            """)
            return subs
        except Exception:
            return []

    async def search(self, query: str) -> list[dict]:
        results = []
        browser_wrapper = None
        try:
            browser_wrapper = await self.browser_pool.acquire()
            browser = browser_wrapper.browser
            context = await browser.new_context()
            page = await context.new_page()

            search_url = f"{self.BASE_URL}/search?q={query}"
            await page.goto(search_url, wait_until="networkidle", timeout=15000)

            await asyncio.sleep(2)

            results_data = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('[class*="search"] a[href*="/watch/"], a[href*="/anime/"]');
                    const results = [];
                    const seen = new Set();
                    items.forEach(item => {
                        const href = item.getAttribute('href');
                        if (href && !seen.has(href)) {
                            seen.add(href);
                            const match = href.match(/\\/(?:watch|anime)\\/(\\d+)/);
                            if (match) {
                                results.push({
                                    id: match[1],
                                    title: item.textContent.trim() || item.getAttribute('title') || '',
                                    source: 'miruro'
                                });
                            }
                        }
                    });
                    return results;
                }
            """)
            results = results_data if results_data else []

            if not results:
                anime_links = await page.query_selector_all("a[href*='/watch/'], a[href*='/anime/']")
                seen = set()
                for link in anime_links:
                    href = await link.get_attribute("href")
                    if href and href not in seen:
                        seen.add(href)
                        import re
                        match = re.search(r"/(?:watch|anime)/(\d+)", href)
                        if match:
                            title = await link.inner_text() or await link.get_attribute("title") or ""
                            results.append({"id": match.group(1), "title": title.strip(), "source": "miruro"})

            await page.close()
            await context.close()
        except Exception as e:
            self.log.warning("Miruro search failed", error=str(e))
        finally:
            if browser_wrapper:
                await browser_wrapper.close()
        return results

    async def check_health(self) -> bool:
        try:
            browser_wrapper = await self.browser_pool.acquire()
            browser = browser_wrapper.browser
            context = await browser.new_context()
            page = await context.new_page()
            resp = await page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=15000)
            status = resp.status if resp else 0
            await page.close()
            await context.close()
            await browser_wrapper.close()
            return status == 200
        except Exception as e:
            self.log.warning("Miruro health check failed", error=str(e))
            return False
