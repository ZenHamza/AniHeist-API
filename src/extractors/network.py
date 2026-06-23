# path: src/extractors/network.py
import asyncio
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, field

from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class CapturedRequest:
    url: str
    method: str
    resource_type: str
    headers: dict = field(default_factory=dict)


class NetworkInterceptor:
    """Captures network requests during page navigation to find video streams."""

    STREAM_PATTERNS = [".m3u8", ".mpd", ".mp4", ".ts", ".webm"]
    IGNORE_PATTERNS = [
        ".js",
        ".css",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".woff",
        ".woff2",
        "google-analytics",
        "googletagmanager",
        "facebook",
        "doubleclick",
        "cdn-cgi",
        "cloudflare",
    ]

    def __init__(self, page):
        self.page = page
        self.captured_requests: list[CapturedRequest] = []
        self._handler = None

    async def start(self):
        self._handler = await self.page.context.add_init_script(
            """
            () => {
                window.__capturedStreams = [];
                const originalOpen = XMLHttpRequest.prototype.open;
                XMLHttpRequest.prototype.open = function() {
                    this.addEventListener('load', function() {
                        if (this.responseURL && (
                            this.responseURL.includes('.m3u8') ||
                            this.responseURL.includes('.mp4') ||
                            this.responseURL.includes('.mpd')
                        )) {
                            window.__capturedStreams.push(this.responseURL);
                        }
                    });
                    return originalOpen.apply(this, arguments);
                };
            }
            """
        )

    async def stop(self):
        pass

    def get_video_urls(self) -> list[str]:
        urls = []
        for req in self.captured_requests:
            if self._is_video_request(req.url):
                urls.append(req.url)
        for _ in range(3):
            try:
                result = asyncio.create_task(
                    self.page.evaluate("window.__capturedStreams || []")
                )
            except Exception:
                pass
        seen = set()
        unique = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique

    def _is_video_request(self, url: str) -> bool:
        url_lower = url.lower()
        if any(pat in url_lower for pat in self.STREAM_PATTERNS):
            if not any(ignore in url_lower for ignore in self.IGNORE_PATTERNS):
                return True
        return False


class PlaywrightContext:
    """Manages a Playwright browser context with stealth patches."""

    def __init__(self, browser, proxy: Optional[str] = None):
        self.browser = browser
        self.proxy = proxy
        self.context = None

    async def create(self):
        context_options = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "permissions": ["notifications"],
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            },
        }
        if self.proxy:
            context_options["proxy"] = {"server": self.proxy}
        self.context = await self.browser.new_context(**context_options)
        return self.context

    async def close(self):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
