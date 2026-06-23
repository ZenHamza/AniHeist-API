from typing import Optional
import httpx

from src.adapters.base import BaseAdapter
from src.models.stream import StreamResult, ParserError
from src.utils.logger import get_logger

log = get_logger(__name__)

REANIME_BASE = "http://localhost:4000"


class ReAnimeAdapter(BaseAdapter):
    _client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20)
        return self._client

    async def _anilist_title(self, anilist_id: int) -> str:
        q = """query ($id: Int) { Media(id: $id, type: ANIME) { title { romaji english } } }"""
        client = await self._get_client()
        try:
            r = await client.post(
                "https://graphql.anilist.co",
                json={"query": q, "variables": {"id": anilist_id}},
                timeout=10,
            )
            if r.status_code == 200:
                t = r.json().get("data", {}).get("Media", {}).get("title", {})
                return t.get("english") or t.get("romaji") or ""
        except Exception:
            pass
        return ""

    async def _resolve_slug(self, anime_id: str) -> str:
        anilist_id = int(anime_id)
        title = await self._anilist_title(anilist_id)
        if not title:
            raise ParserError(f"ReAnime: cannot resolve AniList ID {anime_id}")

        client = await self._get_client()
        try:
            r = await client.get(f"{REANIME_BASE}/search", params={"q": title, "limit": 25})
        except httpx.ConnectError:
            raise ParserError("ReAnime-API not running on port 4000")
        if r.status_code != 200:
            raise ParserError(f"ReAnime search failed: {r.status_code}")

        data = r.json()
        items = data if isinstance(data, list) else data.get("results") or data.get("data") or []

        # First pass: match by anilist_id
        for item in items:
            for key in ("anilist", "anilist_id", "anilistId"):
                if str(item.get(key, "")) == anime_id:
                    slug = item.get("slug", "")
                    if slug:
                        log.info("ReAnime slug resolved by anilist_id", slug=slug, anime_id=anime_id)
                        return slug

        # Second pass: match by title keywords
        title_lower = title.lower()
        title_words = set(title_lower.split())
        for item in items:
            raw = item.get("title", "")
            item_title = raw.lower() if isinstance(raw, str) else ""
            if item_title and len(title_words & set(item_title.split())) >= 2:
                slug = item.get("slug", "")
                if slug:
                    log.info("ReAnime slug resolved by title", slug=slug, title=raw)
                    return slug

        raise ParserError(f"ReAnime: no slug found for '{title}'")

    async def get_video_url(self, anime_id: str, episode: int, **kwargs) -> StreamResult:
        slug = anime_id
        if slug.isdigit():
            slug = await self._resolve_slug(anime_id)

        client = await self._get_client()
        try:
            r = await client.get(
                f"{REANIME_BASE}/servers/{slug}/{episode}",
                params={"anilist_id": int(anime_id) if anime_id.isdigit() else None}
            )
            if r.status_code != 200:
                raise ParserError(f"ReAnime servers: {r.status_code}")

            data = r.json()
            servers = data.get("sub", [])
            if not servers:
                servers = data.get("dub", [])
            if not servers:
                raise ParserError("No servers available")

            for server in servers:
                link = server.get("dataLink", "")
                if not link:
                    continue

                r2 = await client.get(
                    f"{REANIME_BASE}/stream/from-link",
                    params={"link": link}
                )
                if r2.status_code == 200:
                    stream_data = r2.json()
                    url = stream_data.get("url")
                    if url:
                        subs = stream_data.get("subtitles", [])
                        sub_list = []
                        for s in subs:
                            sub_list.append({
                                "lang": s.get("language", "en"),
                                "label": s.get("language", "English"),
                                "url": s.get("url", ""),
                            })
                        log.info("ReAnime stream found", url=url[:60], subs=len(sub_list))
                        return StreamResult(
                            url=url,
                            source="reanime",
                            format="hls",
                            subtitles=sub_list,
                            headers={"Referer": "https://reanime.to/"},
                        )

            raise ParserError("No working server found")
        except httpx.ConnectError:
            raise ParserError("ReAnime-API not running")

    async def search(self, query: str) -> list[dict]:
        try:
            client = await self._get_client()
            r = await client.get(f"{REANIME_BASE}/search", params={"q": query, "limit": 10})
            if r.status_code == 200:
                data = r.json()
                results = []
                for item in data if isinstance(data, list) else data.get("results", []):
                    results.append({
                        "id": item.get("slug", ""),
                        "title": item.get("title", ""),
                        "source": "reanime",
                    })
                return results
        except Exception:
            pass
        return []

    async def check_health(self) -> bool:
        try:
            client = await self._get_client()
            r = await client.get(f"{REANIME_BASE}/")
            return r.status_code == 200
        except Exception:
            return False
