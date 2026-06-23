# path: src/utils/anilist.py
"""
AniList GraphQL API wrapper — provides anime metadata, search, episodes, trending.
Used by the API to enrich responses without requiring a database.
"""

from typing import Optional
import httpx

from src.utils.logger import get_logger

log = get_logger(__name__)

ANILIST_API = "https://graphql.anilist.co"
TIMEOUT = 15

ANIME_METADATA_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english native }
    description
    coverImage { large color }
    bannerImage
    genres
    episodes
    duration
    status
    season
    seasonYear
    averageScore
    format
    studios { nodes { name } }
    startDate { year month day }
    endDate { year month day }
    nextAiringEpisode { episode airingAt }
    trailer { site id }
    tags { name rank }
  }
}
"""

SEARCH_QUERY = """
query ($search: String, $page: Int) {
  Page(page: $page, perPage: 25) {
    media(search: $search, type: ANIME) {
      id
      title { romaji english }
      coverImage { large }
      episodes
      format
      averageScore
      seasonYear
      status
    }
  }
}
"""

EPISODES_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english }
    episodes
    status
    nextAiringEpisode { episode airingAt }
    streamingEpisodes { title thumbnail url site }
    airingSchedule(notYetAired: false, perPage: 50) {
      nodes { episode airingAt }
    }
  }
}
"""

TRENDING_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(sort: TRENDING_DESC, type: ANIME) {
      id
      title { romaji english }
      coverImage { large }
      episodes
      format
      averageScore
      seasonYear
      genres
      status
      description
    }
  }
}
"""

POPULAR_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(sort: POPULARITY_DESC, type: ANIME) {
      id
      title { romaji english }
      coverImage { large }
      episodes
      format
      averageScore
      seasonYear
      genres
      status
    }
  }
}
"""


async def _query(query: str, variables: dict) -> Optional[dict]:
    """Execute a GraphQL query against AniList."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                ANILIST_API,
                json={"query": query, "variables": variables},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data")
            elif resp.status_code == 404:
                return None
            else:
                log.warning("AniList API error", status=resp.status_code, variables=variables)
                return None
    except Exception as e:
        log.warning("AniList request failed", error=str(e), variables=variables)
        return None


async def get_anime_metadata(anime_id: int) -> Optional[dict]:
    """Fetch full metadata for an anime by AniList ID."""
    data = await _query(ANIME_METADATA_QUERY, {"id": anime_id})
    if not data:
        return None

    media = data.get("Media")
    if not media:
        return None

    title = media.get("title", {})
    return {
        "anilist_id": media["id"],
        "title": {
            "romaji": title.get("romaji"),
            "english": title.get("english"),
            "native": title.get("native"),
        },
        "description": media.get("description", ""),
        "cover_image": media.get("coverImage", {}).get("large"),
        "cover_color": media.get("coverImage", {}).get("color"),
        "banner_image": media.get("bannerImage"),
        "genres": media.get("genres", []),
        "episodes": media.get("episodes"),
        "duration": media.get("duration"),
        "status": media.get("status"),
        "season": media.get("season"),
        "season_year": media.get("seasonYear"),
        "score": media.get("averageScore"),
        "format": media.get("format"),
        "studio": (media.get("studios", {}).get("nodes") or [{}])[0].get("name"),
        "start_date": media.get("startDate"),
        "end_date": media.get("endDate"),
        "next_airing": media.get("nextAiringEpisode"),
        "trailer": media.get("trailer"),
        "tags": [t["name"] for t in (media.get("tags") or []) if t.get("rank", 0) > 60],
    }


async def search_anime(query: str, page: int = 1) -> list[dict]:
    """Search anime by title."""
    data = await _query(SEARCH_QUERY, {"search": query, "page": page})
    if not data:
        return []

    results = []
    for media in data.get("Page", {}).get("media", []):
        title = media.get("title", {})
        results.append({
            "id": media["id"],
            "title": title.get("english") or title.get("romaji") or "",
            "native_title": title.get("native"),
            "cover_image": media.get("coverImage", {}).get("large"),
            "episodes": media.get("episodes"),
            "format": media.get("format"),
            "score": media.get("averageScore"),
            "year": media.get("seasonYear"),
            "status": media.get("status"),
        })
    return results


async def get_episodes(anime_id: int) -> dict:
    """Get episode list for an anime."""
    data = await _query(EPISODES_QUERY, {"id": anime_id})
    if not data:
        return {"id": anime_id, "episodes": [], "total": 0}

    media = data.get("Media", {})
    total = media.get("episodes") or 0
    streaming = media.get("streamingEpisodes") or []
    schedule = media.get("airingSchedule", {}).get("nodes") or []

    ep_list = []
    if total > 0:
        ep_list = [{"number": i + 1, "title": None, "aired": True} for i in range(total)]

    for s_ep in streaming:
        num = ep_list.index({"number": s_ep.get("title")}) if False else None

    # Override with schedule info
    for s in schedule:
        ep_num = s.get("episode")
        for ep in ep_list:
            if ep["number"] == ep_num:
                ep["airing_at"] = s.get("airingAt")
                break

    return {
        "id": anime_id,
        "total": total,
        "episodes": ep_list,
        "next_airing": media.get("nextAiringEpisode"),
        "status": media.get("status"),
    }


async def get_trending(page: int = 1, per_page: int = 20) -> list[dict]:
    """Get trending anime."""
    data = await _query(TRENDING_QUERY, {"page": page, "perPage": per_page})
    if not data:
        return []
    return _format_media_list(data.get("Page", {}).get("media", []))


async def get_popular(page: int = 1, per_page: int = 20) -> list[dict]:
    """Get most popular anime."""
    data = await _query(POPULAR_QUERY, {"page": page, "perPage": per_page})
    if not data:
        return []
    return _format_media_list(data.get("Page", {}).get("media", []))


def _format_media_list(media_list: list) -> list[dict]:
    results = []
    for media in media_list:
        title = media.get("title", {})
        desc = media.get("description", "") or ""
        # Strip HTML tags from description
        import re
        desc_clean = re.sub(r"<[^>]+>", "", desc)[:300]
        results.append({
            "id": media["id"],
            "title": title.get("english") or title.get("romaji") or "",
            "cover_image": media.get("coverImage", {}).get("large"),
            "episodes": media.get("episodes"),
            "format": media.get("format"),
            "score": media.get("averageScore"),
            "year": media.get("seasonYear"),
            "genres": media.get("genres", []),
            "status": media.get("status"),
            "description": desc_clean,
        })
    return results
