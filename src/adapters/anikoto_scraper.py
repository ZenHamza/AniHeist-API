import httpx
import re
import json
from typing import Optional
from src.utils.logger import get_logger
from src.models.stream import StreamResult, ParserError

log = get_logger(__name__)

ANIKOTO = "https://anikototv.to"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
AJAX_HEADERS = {**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": f"{ANIKOTO}/"}


async def _get_anilist_title(anilist_id: int) -> str:
    async with httpx.AsyncClient(timeout=10) as c:
        q = """
        query ($id: Int) {
            Media(id: $id, type: ANIME) {
                title { romaji english }
            }
        }
        """
        r = await c.post("https://graphql.anilist.co",
            json={"query": q, "variables": {"id": anilist_id}},
            headers={"Accept": "application/json", "Content-Type": "application/json"})
        if r.status_code == 200:
            m = r.json().get("data", {}).get("Media", {})
            t = m.get("title", {})
            return t.get("english") or t.get("romaji") or ""
    return ""


async def _search_anikoto(keyword: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{ANIKOTO}/ajax/anime/search?keyword={keyword}", headers=AJAX_HEADERS)
        if r.status_code != 200:
            return []
        data = r.json()
        html = data.get("result", {}).get("html", "")
        results = []
        for m in re.finditer(r'href="https://anikototv\.to/watch/([^"]+)"[^>]*>\s*([^<]+)', html):
            slug = m.group(1).split("/")[0]
            title = m.group(2).strip()
            results.append({"slug": slug, "title": title})
        return results


async def _get_show_id(slug: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{ANIKOTO}/watch/{slug}", headers=HEADERS)
        if r.status_code != 200:
            return None
        ids = re.findall(r'data-id=["\'](\d+)', r.text)
        return ids[0] if ids else None


async def _get_episode_list(show_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{ANIKOTO}/ajax/episode/list/{show_id}", headers=AJAX_HEADERS)
        if r.status_code != 200:
            return []
        data = r.json()
        html = data.get("result", "")
        eps = []
        nums = re.findall(r'data-num=["\'](\d+)', html)
        ids = re.findall(r'data-ids=["\']([^"\']+)', html)
        ep_ids = re.findall(r'data-id=["\'](\d+)', html)
        for i in range(len(nums)):
            eps.append({
                "num": int(nums[i]),
                "ids": ids[i] if i < len(ids) else "",
                "ep_id": ep_ids[i] if i < len(ep_ids) else "",
            })
        return eps


async def _get_servers(server_ids: str, audio: str = "sub") -> list[dict]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{ANIKOTO}/ajax/server/list?servers={server_ids}", headers=AJAX_HEADERS)
        if r.status_code != 200:
            return []
        data = r.json()
        html = data.get("result", "")
        servers = []
        # Split into audio type sections, pick the right one
        sections = re.split(r'<div class="type" data-type="(sub|dub)">', html)
        in_target = False
        for piece in sections:
            if piece in ("sub", "dub"):
                in_target = (piece == audio)
            elif in_target:
                for m in re.finditer(r'data-link-id="([^"]+)"', piece):
                    servers.append({"link_id": m.group(1)})
                break
        return servers


async def _resolve_server(link_id: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{ANIKOTO}/ajax/server?get={link_id}", headers=AJAX_HEADERS)
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("result", {}).get("url", "")


async def get_anikoto_stream(anilist_id: int, episode: int, dub: bool = False) -> StreamResult:
    title = await _get_anilist_title(anilist_id)
    if not title:
        raise ParserError("Anikoto: Could not resolve AniList title")

    results = await _search_anikoto(title)
    if not results:
        raise ParserError(f"Anikoto: No results for '{title}'")

    slug = results[0]["slug"]
    show_id = await _get_show_id(slug)
    if not show_id:
        raise ParserError(f"Anikoto: Could not get show ID for {slug}")

    ep_list = await _get_episode_list(show_id)
    target = next((e for e in ep_list if e["num"] == episode), None)
    if not target or not target["ids"]:
        raise ParserError(f"Anikoto: Episode {episode} not found")

    audio = "dub" if dub else "sub"
    servers = await _get_servers(target["ids"], audio=audio)
    if not servers:
        raise ParserError("Anikoto: No servers available")

    video_url = ""
    for server in servers:
        video_url = await _resolve_server(server["link_id"])
        if video_url:
            break

    if not video_url:
        raise ParserError("Anikoto: Could not resolve any server")

    fmt = "hls" if ".m3u8" in video_url else "mp4"
    return StreamResult(
        url=video_url.replace("\\/", "/"),
        source="anikoto",
        format=fmt,
        headers={"Referer": f"{ANIKOTO}/", "Origin": f"{ANIKOTO}"},
    )
