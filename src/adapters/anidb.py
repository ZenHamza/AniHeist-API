# path: src/adapters/anidb.py
import asyncio
from typing import Optional
from urllib.parse import urljoin, urlparse

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
from src.utils.logger import get_logger
from src.config import settings

log = get_logger(__name__)

class AniDBAdapter(BaseAdapter):
    """
    Adapter for anidb.app.
    Uses Playwright headless browser with Cloudflare challenge handling.
    """

    BASE_URL = settings.anidb_base_url

    def __init__(self, browser_pool=None):
        super().__init__()
        self.browser_pool = browser_pool

    async def _wait_for_cloudflare(self, page, timeout: int = 45):
        """Wait for Cloudflare JS challenge to complete."""
        for _ in range(timeout):
            title = await page.title()
            if "just a moment" not in title.lower():
                return True
            await page.wait_for_timeout(1000)
        return False

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        browser_wrapper = await self.browser_pool.acquire()
        browser = browser_wrapper.browser
        context = None
        page = None
        captured_m3u8 = []
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

            page.on("request", lambda req: captured_m3u8.append(req.url) if ".m3u8" in req.url.lower() else None)

            anime_url = f"{self.BASE_URL}/anime/{anime_id}"
            self.log.info("Navigating to AniDB", url=anime_url, episode=episode)

            try:
                await page.goto(anime_url, wait_until="domcontentloaded", timeout=settings.navigation_timeout)
            except Exception as e:
                raise SourceTimeoutError(f"AniDB page navigation timed out: {e}")

            cf_passed = await self._wait_for_cloudflare(page)
            if not cf_passed:
                raise CloudflareBlockError("AniDB Cloudflare challenge could not be solved")

            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            await page.wait_for_timeout(2000)

            page_title = await page.title()
            if "404" in page_title or not page_title:
                raise AnimeNotFoundError(f"Anime ID '{anime_id}' not found on AniDB")

            current_url = page.url
            if "anime" not in current_url:
                raise AnimeNotFoundError(f"Redirected away from anime page: {current_url}")

            await self._click_episode(page, episode)

            for _ in range(15):
                if captured_m3u8:
                    break
                await page.wait_for_timeout(1000)

            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            video_url = None
            if captured_m3u8:
                video_url = captured_m3u8[0]
                self.log.info("Captured video URL via network interception", url=video_url)

            if not video_url:
                video_url = await self._extract_video_from_page(page)

            if not video_url:
                video_url = await self._extract_video_from_iframe(page, context)

            if not video_url:
                raise ParserError("Could not extract video URL from AniDB page")

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
                source="anidb",
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

    async def _click_episode(self, page, episode: int):
        await page.wait_for_timeout(1500)

        clicked = await page.evaluate(f"""
            () => {{
                const epNum = '{episode}';
                const all = document.querySelectorAll('*');
                let containers = [];
                for (const el of all) {{
                    if (el.textContent.includes('Episodes') || el.textContent.includes('episodes')) {{
                        containers.push(el);
                    }}
                }}
                for (const container of containers) {{
                    const items = container.querySelectorAll('button, a, div, span, li');
                    for (const item of items) {{
                        if (item.textContent.trim() === epNum && item.offsetParent !== null) {{
                            item.click();
                            return 'clicked in container: ' + epNum;
                        }}
                    }}
                }}
                for (const item of all) {{
                    if (item.textContent.trim() === epNum && item.offsetParent !== null && !item.querySelector('*') && item.parentElement.offsetParent !== null) {{
                        item.click();
                        return 'clicked leaf: ' + epNum;
                    }}
                }}
                for (const item of document.querySelectorAll('[class*=\"ep\"] button, [class*=\"ep\"] a, [class*=\"ep\"] div, [class*=\"ep\"] span')) {{
                    if (item.textContent.trim() === epNum) {{
                        item.click();
                        return 'clicked ep-class: ' + epNum;
                    }}
                }}
                return 'not found';
            }}
        """)
        self.log.info("Episode click result", result=clicked, number=episode)
        await page.wait_for_timeout(2000)
        if clicked == "not found":
            raise EpisodeNotFoundError(f"Episode {episode} not found on AniDB")

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
                    const el = document.querySelector('[data-src], [data-url], [data-video]');
                    if (el) return el.getAttribute('data-src') || el.getAttribute('data-url') || el.getAttribute('data-video');
                    const els = document.querySelectorAll('script');
                    for (const s of els) {
                        if (s.textContent && s.textContent.includes('.m3u8')) {
                            const m = s.textContent.match(/https?:\\/\\/[^\\s"']+\\.m3u8[^\\s"']*/);
                            if (m) return m[0];
                        }
                    }
                    return null;
                }
            """)
            if video_src:
                return VideoExtractor.clean_url(video_src)
        except Exception as e:
            self.log.debug("DOM video extraction failed", error=str(e))
        return None

    async def _extract_video_from_iframe(self, page, context) -> Optional[str]:
        try:
            iframe_element = await page.query_selector("iframe[src]")
            if iframe_element:
                iframe_src = await iframe_element.get_attribute("src")
                if iframe_src and "player" in iframe_src.lower():
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

            search_url = f"{self.BASE_URL}/search/suggestions?q={query}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)

            content = await page.content()
            soup = BeautifulSoup(content, "lxml")
            links = soup.find_all("a", href=lambda h: h and "/anime/" in h)
            seen = set()
            for link in links:
                href = link.get("href")
                if href and href not in seen:
                    seen.add(href)
                    slug = href.split("/anime/")[-1].strip("/")
                    title = link.text.strip()
                    results.append({"id": slug, "title": title, "source": "anidb"})

            await page.close()
            await context.close()
        except Exception as e:
            self.log.warning("AniDB search failed", error=str(e))
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
            try:
                resp = await page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=15000)
                if resp and resp.status == 200:
                    await page.wait_for_timeout(2000)
                    title = await page.title()
                    return "anidb" in title.lower() and "just a moment" not in title.lower()
                return False
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass
                await browser_wrapper.close()
        except Exception as e:
            self.log.warning("AniDB health check failed", error=str(e))
            return False
