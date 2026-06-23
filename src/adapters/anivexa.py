# path: src/adapters/anivexa.py
"""
Adapter for the Anivexa-API deployed on Vercel Edge.
Provides 7 providers with subtitle support.
"""
from typing import Optional
import httpx

from src.adapters.base import BaseAdapter
from src.models.stream import StreamResult, ParserError, AnimeNotFoundError
from src.utils.logger import get_logger

log = get_logger(__name__)

# Set this to your Vercel deployment URL
ANIVEXA_API = "https://api-anivexa.vercel.app"


class AnivexaAdapter(BaseAdapter):
    def __init__(self, api_url: str = ANIVEXA_API):
        super().__init__()
        self.api_url = api_url

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        anilist_id = int(anime_id) if anime_id.isdigit() else 0
        category = "dub" if kwargs.get("dub") else "sub"

        # First get episodes to find provider IDs
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.api_url}/episodes/{anilist_id}")
                if r.status_code != 200:
                    raise AnimeNotFoundError(f"Anivexa: {r.status_code}")
                data = r.json()
        except Exception as e:
            raise ParserError(f"Anivexa episodes failed: {e}")

        providers = data.get("providers", {})
        
        # Try providers in order: reanime (has English subs), anikoto, animepahe
        for pname in ["reanime", "anikoto", "animepahe", "allmanga", "animegg", "anineko", "anidbapp"]:
            pdata = providers.get(pname)
            if not pdata:
                continue
            eps = pdata.get("episodes", {}).get(category, [])
            if not eps:
                eps = pdata.get("episodes", {}).get("sub", [])
            if not eps:
                continue
            
            # Find the matching episode
            target = None
            for ep in eps:
                if ep.get("number") == episode:
                    target = ep
                    break
            if not target:
                target = eps[episode - 1] if episode <= len(eps) else eps[-1]
            
            ep_id = target.get("id", "")
            if not ep_id:
                continue

            log.info("Trying Anivexa provider", provider=pname, episode=episode)
            try:
                async with httpx.AsyncClient(timeout=20) as c:
                    r = await c.get(f"{self.api_url}/watch/{pname}/{anilist_id}/{category}/{ep_id}")
                    if r.status_code == 200:
                        stream_data = r.json()
                        sources = stream_data.get("sources", [])
                        if sources:
                            url = sources[0].get("url", "")
                            if url:
                                subs = stream_data.get("subtitles", [])
                                sub_list = []
                                for s in subs:
                                    sub_list.append({
                                        "lang": s.get("lang", s.get("language", "en")),
                                        "label": s.get("label", s.get("language", "English")),
                                        "url": s.get("file", s.get("url", "")),
                                    })
                                log.info("Anivexa stream found", provider=pname, url=url[:60])
                                return StreamResult(
                                    url=url,
                                    source=f"anivexa/{pname}",
                                    format="hls",
                                    subtitles=sub_list,
                                    headers={"Referer": "https://reanime.to/"},
                                )
            except Exception as e:
                log.warning("Anivexa provider failed", provider=pname, error=str(e))
                continue

        raise ParserError("No Anivexa provider returned a stream")

    async def search(self, query: str) -> list[dict]:
        return []

    async def check_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.api_url}/")
                return r.status_code == 200
        except Exception:
            return False
