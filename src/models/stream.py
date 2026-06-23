# path: src/models/stream.py
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class StreamStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class FallbackAttempt:
    source: str
    error: str
    latency_ms: float = 0.0


@dataclass
class StreamResult:
    url: str
    source: str
    format: str = "hls"
    subtitles: Optional[list[dict]] = None
    thumbnails: Optional[str] = None
    headers: Optional[dict] = None
    fallback_used: bool = False
    from_cache: bool = False
    fallback_attempts: Optional[list[FallbackAttempt]] = None

    def __post_init__(self):
        if self.subtitles is None:
            self.subtitles = []
        if self.headers is None:
            self.headers = {}
        if self.fallback_attempts is None:
            self.fallback_attempts = []


class ScraperError(Exception):
    status_code: int = 500

    def __init__(self, message: str, status_code: int = 500):
        self.status_code = status_code
        super().__init__(message)


class SourceTimeoutError(ScraperError):
    def __init__(self, message: str = "Source request timed out"):
        super().__init__(message, status_code=504)


class CloudflareBlockError(ScraperError):
    def __init__(self, message: str = "Blocked by Cloudflare anti-bot protection"):
        super().__init__(message, status_code=403)


class ParserError(ScraperError):
    def __init__(self, message: str = "Failed to parse source response"):
        super().__init__(message, status_code=502)


class AnimeNotFoundError(ScraperError):
    def __init__(self, message: str = "Anime not found on this source"):
        super().__init__(message, status_code=404)


class EpisodeNotFoundError(ScraperError):
    def __init__(self, message: str = "Episode not available on this source"):
        super().__init__(message, status_code=404)


class AllSourcesExhaustedError(ScraperError):
    def __init__(self, message: str = "All sources failed to provide a stream"):
        super().__init__(message, status_code=502)


class ValidationError(ScraperError):
    def __init__(self, message: str = "Invalid request parameters"):
        super().__init__(message, status_code=422)


class BrowserPoolExhaustedError(ScraperError):
    def __init__(self, message: str = "All browser instances are busy"):
        super().__init__(message, status_code=503)
