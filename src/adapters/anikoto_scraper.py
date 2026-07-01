import httpx
import re
from typing import Optional
from src.utils.logger import get_logger
from src.models.stream import StreamResult, ParserError

log = get_logger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

SITES = {
    "anikoto": {"base": "https://anikototv.to", "name": "Anikoto"},
    "aniwaves": {"base": "https://aniwaves.ru", "name": "Aniwave"},
}


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


async def _search_site(base: str, keyword: str) -> list[dict]:
    ajax_headers = {**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/"}
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{base}/ajax/anime/search?keyword={keyword}", headers=ajax_headers)
        if r.status_code != 200:
            return []
        data = r.json()
        html = data.get("result", {}).get("html", "")
        results = []
        for m in re.finditer(r'href="[^"]*/watch/([^"]+)"', html):
            path = m.group(1).split("/")[0]
            # aniwaves format: slug-id (death-note-79992)
            # anikoto format: slug only (death-note-fc8mq)
            parts = path.rsplit("-", 1)
            if parts[1].isdigit():
                slug = parts[0]
                show_id = parts[1]
            else:
                slug = path
                show_id = ""
            results.append({"slug": slug, "show_id": show_id, "path": path})
        return results


async def _get_show_id(base: str, slug: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{base}/watch/{slug}", headers=HEADERS)
        if r.status_code != 200:
            return None
        ids = re.findall(r'data-id=["\'](\d+)', r.text)
        return ids[0] if ids else None


async def _get_episode_list(base: str, show_id: str) -> list[dict]:
    ajax_headers = {**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/"}
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{base}/ajax/episode/list/{show_id}", headers=ajax_headers)
        if r.status_code != 200:
            return []
        data = r.json()
        html = data.get("result", "")
        eps = []
        nums = re.findall(r'data-num=["\'](\d+)', html)
        ids = re.findall(r'data-ids=["\']([^"\']+)', html)
        for i in range(len(nums)):
            eps.append({
                "num": int(nums[i]),
                "ids": ids[i] if i < len(ids) else "",
            })
        return eps


async def _get_servers(base: str, server_ids: str, audio: str = "sub") -> list[dict]:
    ajax_headers = {**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/"}
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{base}/ajax/server/list?servers={server_ids}", headers=ajax_headers)
        if r.status_code != 200:
            return []
        data = r.json()
        html = data.get("result", "")
        servers = []
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


async def _resolve_server(base: str, link_id: str) -> Optional[str]:
    ajax_headers = {**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/"}
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        r = await c.get(f"{base}/ajax/server?get={link_id}", headers=ajax_headers)
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("result", {}).get("url", "")


async def _scrape_site(base: str, site_name: str, anilist_id: int, episode: int, dub: bool = False) -> StreamResult:
    title = await _get_anilist_title(anilist_id)
    if not title:
        raise ParserError(f"{site_name}: Could not resolve AniList title")

    results = await _search_site(base, title)
    if not results:
        raise ParserError(f"{site_name}: No results for '{title}'")

    slug = results[0]["slug"]
    show_id = results[0].get("show_id", "")
    if not show_id:
        show_id = await _get_show_id(base, results[0]["path"])
    if not show_id:
        raise ParserError(f"{site_name}: Could not get show ID for {slug}")

    ep_list = await _get_episode_list(base, show_id)
    target = next((e for e in ep_list if e["num"] == episode), None)
    if not target or not target["ids"]:
        raise ParserError(f"{site_name}: Episode {episode} not found")

    audio = "dub" if dub else "sub"
    servers = await _get_servers(base, target["ids"], audio=audio)
    if not servers:
        raise ParserError(f"{site_name}: No servers available")

    video_url = ""
    for server in servers:
        video_url = await _resolve_server(base, server["link_id"])
        if video_url:
            break

    if not video_url:
        raise ParserError(f"{site_name}: Could not resolve any server")

    fmt = "embed" if any(d in video_url for d in ["vidtube", "megaplay", "vidwish"]) else ("hls" if ".m3u8" in video_url else "mp4")
    return StreamResult(
        url=video_url.replace("\\/", "/"),
        source=site_name,
        format=fmt,
        headers={"Referer": f"{base}/", "Origin": f"{base}"},
    )


async def get_anikoto_stream(anilist_id: int, episode: int, dub: bool = False) -> StreamResult:
    return await _scrape_site(SITES["anikoto"]["base"], "anikoto", anilist_id, episode, dub)


async def get_aniwaves_stream(anilist_id: int, episode: int, dub: bool = False) -> StreamResult:
    return await _scrape_site(SITES["aniwaves"]["base"], "aniwaves", anilist_id, episode, dub)
