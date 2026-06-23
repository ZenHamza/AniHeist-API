# path: consumet_api/miruro_pipe.py
"""
Direct interface to Miruro's internal pipe API.
No Playwright needed — just HTTP requests with base64 encoding.
"""
import base64
import gzip
import json
from typing import Optional
import httpx

from src.utils.logger import get_logger
from src.models.stream import StreamResult, ParserError, AnimeNotFoundError
from src.cache.redis_cache import get_cache

log = get_logger(__name__)

PIPE_URL = "https://www.miruro.tv/api/secure/pipe"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.miruro.tv/",
    "Accept": "*/*",
}

# Shared httpx client for connection reuse
_client: Optional[httpx.AsyncClient] = None

async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=15, headers=HEADERS)
    return _client

# Provider priority order — working CDNs first, Cloudflare-blocked last
# Working: ally (wixmp.com), pewe (anidb.app), bonk (vibeplayer.site)
# Blocked: kiwi (uwucdn.top), bee (nekostream.site), moo (animegg.org), hop
PROVIDER_ORDER = ["ally", "pewe", "bonk", "kiwi", "bee", "moo", "hop"]


def _encode(payload: dict) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(data: str) -> dict:
    padded = data + "=" * (4 - len(data) % 4)
    compressed = base64.urlsafe_b64decode(padded)
    return json.loads(gzip.decompress(compressed).decode("utf-8"))


async def _call_pipe(payload: dict, timeout: int = 15) -> dict:
    """Call the Miruro pipe API with an encoded payload."""
    encoded = _encode(payload)
    url = f"{PIPE_URL}?e={encoded}"
    client = await _get_client()
    try:
        resp = await client.get(url, timeout=timeout)
        if resp.status_code != 200:
            log.warning("Pipe API HTTP error", status=resp.status_code, body=resp.text[:200])
            return {}
        return _decode(resp.text)
    except Exception as e:
        log.warning("Pipe API error", error=str(e))
        return {}


class MiruroPipe:
    """
    Interface to Miruro's internal streaming pipe API.
    Provides episodes and stream URLs without Playwright.
    """

    def __init__(self):
        self._episode_cache: dict[int, dict] = {}

    async def get_episodes(self, anilist_id: int) -> dict:
        """Get episode data with provider info from Miruro pipe."""
        if anilist_id in self._episode_cache:
            return self._episode_cache[anilist_id]

        cache = await get_cache()
        cached = await cache.get_anime_meta(f"pipe_ep_{anilist_id}")
        if cached:
            self._episode_cache[anilist_id] = cached
            return cached

        payload = {
            "path": "episodes",
            "method": "GET",
            "query": {"anilistId": anilist_id},
            "body": None,
            "version": "0.1.0",
        }
        data = await _call_pipe(payload, timeout=20)
        if not data or "providers" not in data:
            raise AnimeNotFoundError(f"Anime ID {anilist_id} not found on Miruro pipe")

        self._episode_cache[anilist_id] = data
        try:
            import json as _j
            await cache._set_json(f"anime_meta:pipe_ep_{anilist_id}", data, 3600)
        except:
            pass
        return data

    async def get_stream(
        self,
        anilist_id: int,
        episode: int,
        category: str = "sub",
        preferred_providers: Optional[list[str]] = None,
    ) -> StreamResult:
        """
        Get a stream URL from Miruro pipe.
        Tries providers in order until one returns streams.
        """
        ep_data = await self.get_episodes(anilist_id)
        providers = ep_data.get("providers", {})

        order = preferred_providers or PROVIDER_ORDER
        last_error = ""

        for pname in order:
            pdata = providers.get(pname)
            if not pdata:
                continue

            ep_list = pdata.get("episodes", {}).get(category, [])
            if not ep_list:
                # Try the other category
                other = "dub" if category == "sub" else "sub"
                ep_list = pdata.get("episodes", {}).get(other, [])

            if not ep_list:
                continue

            # Find the matching episode
            target = None
            for ep in ep_list:
                if ep.get("number") == episode:
                    target = ep
                    break
            if not target:
                target = ep_list[episode - 1] if episode <= len(ep_list) else ep_list[-1]

            ep_id = target.get("id", "")
            if not ep_id:
                continue

            log.info("Trying Miruro provider", provider=pname, episode=episode)

            payload = {
                "path": "sources",
                "method": "GET",
                "query": {
                    "episodeId": ep_id,
                    "provider": pname,
                    "category": category,
                    "anilistId": anilist_id,
                },
                "body": None,
                "version": "0.1.0",
            }

            data = await _call_pipe(payload, timeout=15)
            streams = data.get("streams", [])
            headers = data.get("headers", {})

            if streams:
                # Pick the best stream (highest quality HLS first)
                best = self._pick_best_stream(streams)
                if best:
                    log.info(
                        "Miruro pipe stream found",
                        provider=pname,
                        quality=best.get("quality", "N/A"),
                        url=best["url"][:60],
                    )
                    # Use the stream's referer, fall back to provider default
                    stream_referer = best.get("referer") or f"https://{pname}.to/"
                    stream_headers = {
                        "Referer": stream_referer,
                        "Origin": stream_referer.rstrip("/"),
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    }
                    # Quick CDN accessibility check — skip if blocked
                    fmt = "hls" if best.get("type") == "hls" else "mp4"
                    try:
                        cdn_check = await _get_client()
                        head = await cdn_check.head(best["url"], headers=stream_headers, follow_redirects=True, timeout=5)
                        if head.status_code in (403, 401, 451):
                            log.warning("CDN blocked, skipping provider", provider=pname, status=head.status_code)
                            last_error = f"{pname}: CDN blocked ({head.status_code})"
                            continue
                    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError):
                        log.warning("CDN unreachable, skipping provider", provider=pname)
                        last_error = f"{pname}: CDN unreachable"
                        continue
                    except Exception:
                        # If HEAD fails, still try — some CDNs reject HEAD but accept GET
                        pass
                    return StreamResult(
                        url=best["url"],
                        source=f"miruro/{pname}",
                        format=fmt,
                        headers=stream_headers,
                    )

            last_error = f"{pname}: no streams"

        raise ParserError(f"No stream from any Miruro provider. Last: {last_error}")

    def _pick_best_stream(self, streams: list[dict]) -> Optional[dict]:
        """Pick the best stream — prefer HLS, highest quality."""
        # Sort: HLS > MP4 > embed, highest quality first
        quality_order = {"1080p": 3, "720p": 2, "480p": 1, "360p": 0}
        type_order = {"hls": 2, "mp4": 1, "embed": 0}

        def sort_key(s):
            q = quality_order.get(s.get("quality", ""), -1)
            t = type_order.get(s.get("type", ""), -1)
            return (t, q)

        sorted_streams = sorted(streams, key=sort_key, reverse=True)
        for s in sorted_streams:
            url = s.get("url", "")
            stype = s.get("type", "")
            if url and stype != "embed":
                return s
        # Fallback: return first embed
        return sorted_streams[0] if sorted_streams else None

    async def get_providers_for_anime(self, anilist_id: int) -> list[dict]:
        """Get list of available providers for an anime."""
        data = await self.get_episodes(anilist_id)
        providers = data.get("providers", {})
        result = []
        for pname, pdata in providers.items():
            meta = pdata.get("meta", {})
            eps = pdata.get("episodes", {})
            total_sub = len(eps.get("sub", []))
            total_dub = len(eps.get("dub", []))
            if total_sub > 0 or total_dub > 0:
                result.append({
                    "name": pname,
                    "title": meta.get("title"),
                    "episodes": {"sub": total_sub, "dub": total_dub},
                })
        return result
