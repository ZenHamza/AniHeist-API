# path: src/adapters/base.py
import asyncio
from abc import ABC, abstractmethod
from typing import Optional

from src.models.stream import StreamResult
from src.utils.logger import get_logger
from src.config import settings

log = get_logger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    log.warning("Playwright not available, browser-dependent adapters will fail")


class BrowserPool:
    """Pool of managed Playwright browser instances with memory limits."""

    def __init__(self, max_browsers: int = settings.max_browsers):
        self.max_browsers = max_browsers
        self._semaphore = asyncio.Semaphore(max_browsers)
        self._playwright = None
        self._browsers: list[Browser] = []
        self._page_count: dict[int, int] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    async def start(self):
        if self._initialized:
            return
        if not PLAYWRIGHT_AVAILABLE:
            log.error("Playwright is not installed")
            return
        try:
            self._playwright = await async_playwright().start()
            self._initialized = True
            log.info("Browser pool started", max_browsers=self.max_browsers)
        except Exception as e:
            log.error("Failed to start Playwright", error=str(e))
            raise

    async def acquire(self) -> Browser:
        await self._semaphore.acquire()
        if not self._playwright:
            await self.start()
        async with self._lock:
            browser = await self._get_or_create_browser()
            return _BrowserWrapper(browser, self._semaphore, self)

    async def _get_or_create_browser(self) -> Browser:
        for i, b in enumerate(self._browsers):
            if self._page_count.get(i, 0) < settings.browser_restart_after:
                try:
                    await b.version
                    self._page_count[i] = self._page_count.get(i, 0) + 1
                    return b
                except Exception:
                    self._browsers[i] = await self._create_browser()
                    self._page_count[i] = 1
                    return self._browsers[i]
        browser = await self._create_browser()
        self._browsers.append(browser)
        self._page_count[len(self._browsers) - 1] = 1
        return browser

    async def _create_browser(self) -> Browser:
        return await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-accelerated-2d-canvas",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--single-process",
                "--no-zygote",
                "--disable-font-subpixel-positioning",
                "--disable-lcd-text",
            ],
            ignore_default_args=[
                "--enable-automation",
                "--enable-blink-features=IdleDetection",
            ],
        )

    async def release_browser(self, browser: Browser):
        self._semaphore.release()

    async def stop(self):
        async with self._lock:
            for browser in self._browsers:
                try:
                    await browser.close()
                except Exception:
                    pass
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
            self._browsers.clear()
            self._page_count.clear()
            self._initialized = False
            log.info("Browser pool stopped")


class _BrowserWrapper:
    def __init__(self, browser: Browser, semaphore: asyncio.Semaphore, pool: BrowserPool):
        self._browser = browser
        self._semaphore = semaphore
        self._pool = pool

    @property
    def browser(self) -> Browser:
        return self._browser

    async def close(self):
        self._semaphore.release()

    def __getattr__(self, name):
        return getattr(self._browser, name)


class BaseAdapter(ABC):
    """Abstract base class for all source adapters."""

    def __init__(self):
        self.log = get_logger(self.__class__.__name__)

    @abstractmethod
    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        ...

    @abstractmethod
    async def search(self, query: str) -> list[dict]:
        ...

    @abstractmethod
    async def check_health(self) -> bool:
        ...

    def resolve_anime_id(self, anime_id: str) -> str:
        return anime_id.strip()
