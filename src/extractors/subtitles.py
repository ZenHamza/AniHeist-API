# path: src/extractors/subtitles.py
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class SubtitleExtractor:
    """Extracts subtitle tracks from HTML or player elements."""

    @staticmethod
    def extract_from_html(soup: BeautifulSoup, base_url: Optional[str] = None) -> list[dict]:
        subtitles = []

        track_elements = soup.find_all("track")
        for track in track_elements:
            src = track.get("src")
            if not src:
                continue
            sub = {
                "lang": track.get("srclang", "en") or "en",
                "label": track.get("label", "") or "",
                "url": urljoin(base_url, src) if base_url else src,
            }
            sub["url"] = sub["url"].strip()
            if sub["url"]:
                subtitles.append(sub)

        sub_links = soup.find_all("a", href=re.compile(r"\.(vtt|srt|ass|ssa)$", re.I))
        for link in sub_links:
            href = link.get("href")
            if not href:
                continue
            full_url = urljoin(base_url, href) if base_url else href
            subtitles.append({
                "lang": link.get("data-lang", "en") or "en",
                "label": link.get("data-label", link.text.strip()) or link.text.strip(),
                "url": full_url.strip(),
            })

        return subtitles

    @staticmethod
    def extract_from_js(js_content: str, base_url: Optional[str] = None) -> list[dict]:
        subtitles = []

        pattern = re.compile(
            r'(?:subtitle|subs|track|texttrack)[^:]*:\s*\{[^}]*'
            r'(?:src|url|file)\s*[:=]\s*["\']([^"\']+\.(?:vtt|srt))["\'][^}]*'
            r'(?:lang|language|srclang)\s*[:=]\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        for match in pattern.finditer(js_content):
            url, lang = match.groups()
            full_url = urljoin(base_url, url) if base_url else url
            subtitles.append({
                "lang": lang.lower() if lang else "en",
                "label": lang.upper() if lang else "English",
                "url": full_url.strip(),
            })

        return subtitles

    @staticmethod
    def extract_from_player_api(api_response: dict) -> list[dict]:
        subtitles = []
        tracks = api_response.get("tracks") or api_response.get("subtitles") or []
        for track in tracks:
            url = track.get("url") or track.get("src") or track.get("file") or ""
            if not url:
                continue
            subtitles.append({
                "lang": track.get("lang") or track.get("srclang") or track.get("language", "en"),
                "label": track.get("label") or track.get("name", ""),
                "url": url.strip(),
            })
        return subtitles
