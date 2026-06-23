# path: src/extractors/video.py
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

from src.utils.logger import get_logger

log = get_logger(__name__)

VIDEO_EXTENSIONS = {".m3u8", ".mpd", ".mp4", ".webm", ".avi", ".mkv", ".ts"}
STREAM_PATTERNS = [
    re.compile(r'(https?://[^\s"\'<>]+\.(?:m3u8|mpd|mp4)(?:\?[^\s"\'<>]*)?)'),
    re.compile(r'"file"\s*:\s*"([^"]+\.(?:m3u8|mp4|mpd)[^"]*)"'),
    re.compile(r'"src"\s*:\s*"([^"]+\.(?:m3u8|mp4|mpd)[^"]*)"'),
    re.compile(r"'file'\s*:\s*'([^']+\.(?:m3u8|mp4|mpd)[^']*)'"),
    re.compile(r"'(?:url|src)'\s*:\s*'([^']+\.(?:m3u8|mp4)[^']*)'"),
    re.compile(r'data-video-src="([^"]+)"'),
    re.compile(r'<source[^>]+src="([^"]+\.(?:m3u8|mp4))"'),
    re.compile(r"playlist_url\s*=\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]"),
]


class VideoExtractor:
    """Generic video URL extraction from HTML/JS content."""

    @staticmethod
    def extract_from_html(html: str) -> list[str]:
        urls: list[str] = []
        for pattern in STREAM_PATTERNS:
            matches = pattern.findall(html)
            urls.extend(matches)
        seen = set()
        unique = []
        for url in urls:
            if url not in seen and VideoExtractor.is_video_url(url):
                seen.add(url)
                unique.append(url)
        return unique

    @staticmethod
    def is_video_url(url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        path = parsed.path.lower()
        return any(ext in path for ext in VIDEO_EXTENSIONS)

    @staticmethod
    def is_playlist(url: str) -> bool:
        return ".m3u8" in url.lower() or ".mpd" in url.lower()

    @staticmethod
    def clean_url(url: str) -> str:
        url = url.strip().strip('"').strip("'")
        if url.startswith("//"):
            url = "https:" + url
        return url


class VideoQuality:
    """Parse video quality from URL or filename."""

    QUALITY_PATTERNS = [
        re.compile(r'(\d{3,4})[pP]'),
        re.compile(r'(\d{3,4})x\d{3,4}'),
        re.compile(r'_\d{3,4}[pP]_'),
    ]

    @staticmethod
    def detect_quality(url: str) -> Optional[str]:
        for pattern in VideoQuality.QUALITY_PATTERNS:
            match = pattern.search(url)
            if match:
                return match.group(1) + "p"
        return None

    @staticmethod
    def prefer_quality(urls: list[str], preferred: Optional[str]) -> Optional[str]:
        if not urls:
            return None
        if not preferred:
            return urls[0]
        for url in urls:
            q = VideoQuality.detect_quality(url)
            if q == preferred:
                return url
        return urls[0]
