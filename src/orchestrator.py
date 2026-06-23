# path: src/orchestrator.py
import time
from typing import Optional

from src.fallback_manager import FallbackManager
from src.adapters.base import BrowserPool
from src.adapters.unified import UnifiedAdapter
from src.adapters.consumet import ConsumetAdapter
from src.cache.redis_cache import get_cache
from src.models.stream import StreamResult, AllSourcesExhaustedError, ValidationError
from src.utils.http_client import HttpClientPool
from src.utils.logger import get_logger
from src.config import settings

log = get_logger(__name__)


class Orchestrator:
    """
    Main entry point that coordinates anime stream resolution.

    - Resolves AniList IDs to source-specific IDs
    - Checks cache before scraping
    - Delegates to FallbackManager for multi-source failover
    """

    def __init__(self):
        self.browser_pool = BrowserPool(max_browsers=settings.max_browsers)
        self.http_pool = HttpClientPool(max_sessions=5)
        self.fallback_manager = FallbackManager(source_order=["unified"])
        self._initialized = False
        self._adapters: dict = {}

    async def initialize(self):
        if self._initialized:
            return
        try:
            await self.browser_pool.start()
        except Exception as e:
            log.warning("BrowserPool failed to start", error=str(e))
        self._adapters = {
            "unified": UnifiedAdapter(browser_pool=self.browser_pool),
        }
        self._initialized = True
        log.info("Orchestrator initialized with adapters", adapters=list(self._adapters.keys()))

    async def get_stream(
        self,
        anime_id: str,
        episode: int,
        dub: bool = False,
        quality: Optional[str] = None,
        provider: Optional[str] = None,
        source: Optional[str] = None,
    ) -> StreamResult:
        if not self._initialized:
            await self.initialize()

        if not anime_id or anime_id < 1:
            raise ValidationError("Invalid anime_id: must be a positive integer")
        if not episode or episode < 1:
            raise ValidationError("Invalid episode: must be a positive integer")

        cache_provider = provider or ""
        cache_source = source or ""
        cache = await get_cache()

        cached = await cache.get_stream(anime_id, episode, provider=cache_provider, source=cache_source)
        if cached:
            log.info("Cache hit for stream", anime_id=anime_id, episode=episode, provider=provider)
            return StreamResult(from_cache=True,
                url=cached["url"],
                source=cached.get("source", "cache"),
                format=cached.get("format", "hls"),
                subtitles=cached.get("subtitles"),
                thumbnails=cached.get("thumbnails"),
                headers=cached.get("headers"),
                fallback_used=cached.get("fallback_used", False),
                fallback_attempts=cached.get("fallback_attempts"),
            )

        anime_id_str = str(anime_id)

        extra_kwargs = {}
        if provider:
            extra_kwargs["provider"] = provider
        if source:
            extra_kwargs["source"] = source
        result = await self.fallback_manager.get_stream(
            adapters=self._adapters,
            anime_id=anime_id_str,
            episode=episode,
            dub=dub,
            quality=quality,
            **extra_kwargs,
        )

        try:
            await cache.set_stream(anime_id, episode, {
                "url": result.url,
                "source": result.source,
                "format": result.format,
                "subtitles": result.subtitles,
                "thumbnails": result.thumbnails,
                "headers": result.headers,
                "fallback_used": result.fallback_used,
                "fallback_attempts": [
                    {"source": a.source, "error": a.error, "latency_ms": a.latency_ms}
                    for a in (result.fallback_attempts or [])
                ],
            }, provider=cache_provider, source=cache_source)
        except Exception as e:
            log.warning("Failed to cache stream result", error=str(e))

        return result

    async def search(self, query: str) -> list[dict]:
        if not self._initialized:
            await self.initialize()

        if not query or len(query.strip()) < 2:
            raise ValidationError("Search query must be at least 2 characters")

        cache = await get_cache()
        cached = await cache.get_search(query)
        if cached:
            log.info("Cache hit for search", query=query)
            return cached

        all_results = []
        seen_ids = set()

        for source_name, adapter in self._adapters.items():
            try:
                results = await adapter.search(query)
                for r in results:
                    dedup_key = f"{r['source']}:{r['id']}"
                    if dedup_key not in seen_ids:
                        seen_ids.add(dedup_key)
                        all_results.append(r)
            except Exception as e:
                log.warning("Search failed for source", source=source_name, error=str(e))

        try:
            await cache.set_search(query, all_results)
        except Exception as e:
            log.warning("Failed to cache search results", error=str(e))

        return all_results

    async def get_health(self) -> dict:
        if not self._initialized:
            await self.initialize()

        source_health = {}
        for name, adapter in self._adapters.items():
            try:
                healthy = await adapter.check_health()
                source_health[name] = {"healthy": healthy}
            except Exception as e:
                source_health[name] = {"healthy": False, "error": str(e)}

        return {
            "status": "healthy" if any(h.get("healthy") for h in source_health.values()) else "degraded",
            "sources": source_health,
            "fallback_manager": self.fallback_manager.get_health_report(),
            "cache_enabled": (await get_cache()).enabled,
        }

    async def shutdown(self):
        log.info("Shutting down orchestrator")
        try:
            await self.browser_pool.stop()
        except Exception as e:
            log.error("Error stopping browser pool", error=str(e))
        try:
            cache = await get_cache()
            await cache.disconnect()
        except Exception as e:
            log.error("Error disconnecting cache", error=str(e))

    async def reset_fallback(self, source: Optional[str] = None):
        if source:
            await self.fallback_manager.reset_source(source)
        else:
            await self.fallback_manager.reset_all()
