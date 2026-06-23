# path: src/models/anime.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EpisodeInfo:
    number: int
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    is_dub: bool = False
    is_filler: bool = False


@dataclass
class AnimeMetadata:
    anilist_id: int
    title: str
    title_english: Optional[str] = None
    title_native: Optional[str] = None
    synopsis: Optional[str] = None
    cover_image: Optional[str] = None
    banner_image: Optional[str] = None
    genres: list[str] = field(default_factory=list)
    total_episodes: Optional[int] = None
    status: Optional[str] = None
    season: Optional[str] = None
    year: Optional[int] = None
    source: str = ""


@dataclass
class AnimeSearchResult:
    anilist_id: int
    title: str
    title_english: Optional[str] = None
    cover_image: Optional[str] = None
    episode_count: Optional[int] = None
    format: Optional[str] = None
    source: str = ""
    relevance: float = 0.0
