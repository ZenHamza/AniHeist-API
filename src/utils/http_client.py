# path: src/utils/http_client.py
import asyncio
import random
from typing import Optional
from src.utils.logger import get_logger

log = get_logger(__name__)

try:
    from curl_cffi import requests as curl_requests

    CURL_AVAILABLE = True
except ImportError:
    CURL_AVAILABLE = False
    log.warning("curl_cffi not available, falling back to httpx")
    import httpx


class HttpClientPool:
    """Pool of curl_cffi sessions with TLS impersonation for Cloudflare bypass."""

    def __init__(
        self,
        max_sessions: int = 5,
        impersonate: str = "chrome120",
        timeout: float = 30.0,
        proxies: Optional[list[str]] = None,
    ):
        self.max_sessions = max_sessions
        self.impersonate = impersonate
        self.timeout = timeout
        self.proxies = proxies or []
        self._sessions: list = []
        self._semaphore = asyncio.Semaphore(max_sessions)
        self._lock = asyncio.Lock()

    async def get_session(self):
        await self._semaphore.acquire()
        session = self._create_session()
        return _SessionWrapper(session, self._semaphore)

    def _create_session(self):
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        proxy = random.choice(self.proxies) if self.proxies else None

        if CURL_AVAILABLE:
            session_kwargs = {
                "impersonate": self.impersonate,
                "timeout": self.timeout,
                "headers": {
                    "User-Agent": user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            }
            if proxy:
                session_kwargs["proxies"] = {"http": proxy, "https": proxy}
            return curl_requests.Session(**session_kwargs)

        client_kwargs = {
            "timeout": self.timeout,
            "headers": {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if proxy:
            client_kwargs["proxies"] = {"http://": proxy, "https://": proxy}
        return httpx.AsyncClient(**client_kwargs)

    async def close_all(self):
        async with self._lock:
            for session in self._sessions:
                try:
                    if CURL_AVAILABLE:
                        session.close()
                    else:
                        await session.aclose()
                except Exception:
                    pass
            self._sessions.clear()


class _SessionWrapper:
    def __init__(self, session, semaphore):
        self._session = session
        self._semaphore = semaphore

    @property
    def session(self):
        return self._session

    async def get(self, url: str, **kwargs):
        max_retries = kwargs.pop("max_retries", 2)
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if CURL_AVAILABLE:
                    return self._session.get(url, **kwargs)
                else:
                    return await self._session.get(url, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = (2 ** attempt) + random.uniform(0, 0.5)
                    await asyncio.sleep(delay)
                else:
                    raise last_error

    async def post(self, url: str, **kwargs):
        if CURL_AVAILABLE:
            return self._session.post(url, **kwargs)
        else:
            return await self._session.post(url, **kwargs)

    async def close(self):
        try:
            if CURL_AVAILABLE:
                self._session.close()
            else:
                await self._session.aclose()
        finally:
            self._semaphore.release()

    def __getattr__(self, name):
        return getattr(self._session, name)
