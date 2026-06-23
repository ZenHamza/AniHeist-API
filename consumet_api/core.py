# path: consumet_api/core.py
"""
Consumet-compatible API wrapper.
Aggregates multiple providers and provides a unified interface.
"""
from typing import Optional

from src.utils.http_client import HttpClientPool
from src.utils.logger import get_logger
from src.models.stream import StreamResult, StreamResult, ParserError

from consumet_api.animepahe import AnimePahe
from consumet_api.pulsar import Pulsar

log = get_logger(__name__)


class ConsumetAPI:
    """
    Unified Consumet-style API for multiple anime streaming providers.
    Mirrors the pattern used by Anivexa's graphql-kurovexa backend.
    """

    def __init__(self, http_pool: Optional[HttpClientPool] = None):
        self.http_pool = http_pool or HttpClientPool(max_sessions=10)
        self.providers = {
            "animepahe": AnimePahe(http_pool=self.http_pool),
            "pulsar": Pulsar(http_pool=self.http_pool),
        }

    async def get_episodes(self, anilist_id: str) -> dict:
        """
        Get episode list from all providers.
        Returns dict of provider_name -> episode data.
        """
        return {}

    async def get_stream(
        self,
        provider: str,
        anilist_id: str,
        episode: int,
        audio: str = "sub",
        provider_id: Optional[str] = None,
    ) -> StreamResult:
        """
        Get a stream URL from a specific provider.
        
        Args:
            provider: Provider name (animepahe, pulsar)
            anilist_id: AniList anime ID
            episode: Episode number
            audio: Audio type (sub/dub)
            provider_id: Provider-specific ID (for animepahe)
        
        Returns:
            StreamResult with video URL
        """
        adapter = self.providers.get(provider)
        if not adapter:
            raise ParserError(f"Unknown provider: {provider}")

        url = None
        if provider == "animepahe":
            if not provider_id:
                raise ParserError("animepahe requires provider_id")
            url = await adapter.get_stream_url(provider_id, episode)
        elif provider == "pulsar":
            url = await adapter.get_stream_url(anilist_id, episode, audio)

        if not url:
            raise ParserError(f"{provider} returned no stream URL")

        return StreamResult(
            url=url,
            source=f"consumet/{provider}",
            format="hls" if ".m3u8" in url.lower() else "mp4",
            headers={"Referer": "https://animepahe.pw/" if provider == "animepahe" else "https://megaplay.buzz/"},
        )

    async def try_providers(
        self,
        anilist_id: str,
        episode: int,
        provider_id: Optional[str] = None,
        audio: str = "sub",
    ) -> StreamResult:
        """
        Try providers in order until one returns a stream.
        Order: animepahe, pulsar
        """
        last_error = None

        if provider_id:
            try:
                return await self.get_stream("animepahe", anilist_id, episode, audio, provider_id)
            except Exception as e:
                last_error = e
                log.warning("animepahe failed", error=str(e))

        try:
            return await self.get_stream("pulsar", anilist_id, episode, audio)
        except Exception as e:
            last_error = e
            log.warning("pulsar failed", error=str(e))

        raise ParserError(f"All consumet providers failed. Last: {last_error}")
