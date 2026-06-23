# Multi-Source Anime Streaming Scraper — Production Implementation Plan

> **LEGAL DISCLAIMER**: This document is for educational and research purposes only. Web scraping copyrighted content without authorization may violate the Terms of Service of target websites and copyright laws in your jurisdiction. Deploying a public-facing service that streams copyrighted anime without a license carries significant legal risk (DMCA takedowns, lawsuits, criminal liability). **Consult a qualified intellectual property attorney before deploying any production system.** The techniques here are for learning. You assume all liability for any use of this information.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Site Technical Analysis & Adapters](#2-site-technical-analysis--adapters)
3. [Fallback Manager](#3-fallback-manager)
4. [Video Extraction & Processing](#4-video-extraction--processing)
5. [Error Handling & Logging](#5-error-handling--logging)
6. [Security & Anti-Detection](#6-security--anti-detection)
7. [Development Roadmap](#7-development-roadmap)
8. [Testing Strategy](#8-testing-strategy)
9. [Deployment & Maintenance](#9-deployment--maintenance)
10. [Code Structure](#10-code-structure)
11. [API Endpoint Design](#11-api-endpoint-design)
12. [Performance Considerations](#12-performance-considerations)
13. [Frontend Integration](#13-frontend-integration)

---

## 1. Architecture Overview

### High-Level Design

```
┌──────────────────────────────────────────────────────────────┐
│                     USER'S WEBSITE (Frontend)                │
│  Browser ──► Video.js/Plyr Player ◄── HLS/DASH stream       │
└──────────────────────────┬───────────────────────────────────┘
                           │ GET /api/stream?anime=xxx&ep=N
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    YOUR BACKEND API (FastAPI / Express)      │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                 ORCHESTRATOR                          │    │
│  │  - Receives anime ID + episode number                │    │
│  │  - Checks cache (Redis)                              │    │
│  │  - Delegates to FallbackManager                      │    │
│  │  - Returns {video_url, source, subtitles}            │    │
│  └─────────────────────┬────────────────────────────────┘    │
│                        │                                     │
│  ┌─────────────────────▼────────────────────────────────┐    │
│  │              FALLBACK MANAGER                         │    │
│  │  - Priority queue: [AniDB, AniZone, Miruro]          │    │
│  │  - Circuit breaker per source                        │    │
│  │  - Retry with exponential backoff                    │    │
│  │  - Health check cache (TTL: 30s)                     │    │
│  └───────┬───────────────┬───────────────┬──────────────┘    │
│          │               │               │                   │
│  ┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐           │
│  │ AniDBAdapter │ │AniZoneAdptr │ │MiruroAdptr  │           │
│  │ (Playwright) │ │ (curl_cffi) │ │ (Playwright)│           │
│  └───────┬──────┘ └──────┬──────┘ └──────┬──────┘           │
│          │               │               │                   │
│  ┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐           │
│  │ VideoExtract │ │ VideoExtract│ │ VideoExtract│           │
│  │ (.m3u8/.mp4) │ │ (iframe+API)│ │ (.m3u8/.mp4)│           │
│  └──────────────┘ └─────────────┘ └─────────────┘           │
└──────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | Role | Technology |
|-----------|------|------------|
| **Orchestrator** | Main entry point; resolves anime ID to video URL | FastAPI (Python) |
| **FallbackManager** | Priority queue, circuit breaker, retry logic | Custom class |
| **SourceAdapter (x3)** | Per-site scraping logic | Playwright + curl_cffi |
| **VideoExtractor** | Parses HTML/JS to find stream URLs | BeautifulSoup + regex |
| **Cache Layer** | Redis for results + health status | Redis/redis-py |
| **Logger** | Structured JSON logging | structlog / loguru |

### Language Choice: **Python (recommended)**

- **Playwright** (headless browser for JS-heavy sites) has the best Python support
- `curl_cffi` lets you impersonate Chrome TLS fingerprints (critical for Cloudflare)
- Rich async ecosystem (`asyncio`, `httpx`, `aiohttp`)
- Easy to integrate with FastAPI for the backend API
- `beautifulsoup4` + `lxml` for HTML parsing

---

## 2. Site Technical Analysis & Adapters

### 2.1 Source 1 — AniDB (`anidb.app`)

**Technology Stack (from HTML analysis):**
- Laravel (PHP) backend — CSRF tokens in meta tags
- Module-preloaded JavaScript (`app-CcNNqum8.js`)
- Endpoint `/search/suggestions?q=...` returns HTML fragments
- URL pattern: `/anime/{slug}-{id}` (e.g., `/anime/noragami-3819`)
- Uses `<meta name="csrf-token">` — token required for POST
- Cloudflare CDN (likely)

**Scraping Approach: Headless Browser (Playwright)**

AniDB is a React/Laravel hybrid with heavy JS rendering. A simple HTTP client won't work because:
- The anime page content is loaded dynamically via API calls
- Video player is JS-initialized
- CSRF tokens rotate

**Step-by-Step Extraction Logic:**

```python
# pseudocode for anidb_adapter.py

async def get_video_url(self, anime_slug: str, episode: int) -> StreamResult:
    """
    1. Navigate to anime page: https://anidb.app/anime/{slug}
    2. Find the episode list (ul/div with episode buttons)
    3. Click episode N button
    4. Wait for video player to load (<video> or <iframe>)
    5. Extract src attribute or intercept network request
    6. Return the .m3u8 or .mp4 URL
    """
    page = await self.context.new_page()

    # Step 1: Go to anime page
    await page.goto(f"https://anidb.app/anime/{anime_slug}", 
                     wait_until="networkidle", timeout=30000)

    # Step 2: Find and click episode
    episode_selector = f'[data-episode="{episode}"]'  # or similar
    await page.click(episode_selector)
    await page.wait_for_load_state("networkidle")

    # Step 3: Wait for video element
    await page.wait_for_selector("video source, iframe, .player-container", 
                                  timeout=15000)

    # Step 4: Extract via one of these methods
    # Method A: Direct video element
    video_src = await page.eval_on_selector("video source", "el => el.src")

    # Method B: Intercept network requests (MOST RELIABLE)
    # Set up request interception BEFORE navigation, capture .m3u8 URLs
    
    return StreamResult(url=video_src, source="anidb", 
                        subtitles=extracted_subtitles)
```

**Specific Challenges:**
- Cloudflare JS challenge on first visit — solve by using `curl_cffi` for initial request, then pass cookies to Playwright
- CSRF token rotation — extract from `<meta name="csrf-token">` before making any POST requests
- API endpoints may be rate-limited — use random delays (1-3 seconds between requests)

**Libraries:**
- `playwright` (`pip install playwright && playwright install chromium`)
- `curl_cffi` (`pip install curl_cffi`) — for TLS fingerprint impersonation
- `beautifulsoup4`

**Error Handling:**
| Error | Cause | Handler |
|-------|-------|---------|
| `TimeoutError` | Page load >30s | Retry 2x, then raise `SourceTimeoutError` |
| Cloudflare 403 | JS challenge failed | Use curl_cffi session cookies, retry |
| `ElementNotFound` | Site structure changed | Raise `ParserError`, trigger fallback |
| Empty video src | Episode not available | Return `None`, fallback to next source |

---

### 2.2 Source 2 — AniZone (`anizone.to`)

**Technology Stack:**
- **Laravel + Livewire** (PHP) — server-rendered with AJAX interactivity
- **Vidstack** video player library
- URL pattern: `/anime/{base62_id}` (e.g., `/anime/1lbgjbgr`)
- Episode URLs likely: `/anime/{id}/episode/{N}` or similar
- Uses **Swiper.js** for carousels
- Anti-adblock detection (checks if ad iframe is hidden after 2.5s)
- Cloudflare CDN with `cdn-cgi` endpoint
- Embeds content from `animepahe.pw`

**Scraping Approach: HTTP Client with Session (curl_cffi)**

AniZone is server-rendered (Livewire SSR), meaning:
- We can scrape HTML directly without JS execution
- Livewire API endpoints accept JSON payloads
- Faster and lighter than Playwright

**Step-by-Step Extraction Logic:**

```python
# pseudocode for anizone_adapter.py

async def get_video_url(self, anime_id: str, episode: int) -> StreamResult:
    """
    1. Build anime page URL: https://anizone.to/anime/{id}
    2. Fetch HTML, parse episode list
    3. Find episode URL, fetch episode page
    4. Parse for iframe src (likely animepahe.pw embed)
    5. Follow iframe to get actual video URL
    6. Return the .m3u8 or .mp4 URL
    """
    from curl_cffi import requests

    session = requests.Session()
    # Impersonate Chrome 120 to bypass Cloudflare
    session.headers.update({
        "User-Agent": "Mozilla/5.0 ... Chrome/120.0.0.0 ...",
        "Accept": "text/html,application/xhtml+xml,...",
    })

    # Step 1: Get anime page
    resp = session.get(f"https://anizone.to/anime/{anime_id}",
                       impersonate="chrome120")
    soup = BeautifulSoup(resp.text, "lxml")

    # Step 2: Extract CSRF and Livewire components
    csrf_token = soup.find("meta", {"name": "csrf-token"})["content"]

    # Step 3: Find episode links  
    # They are in Livewire component - might need to call Livewire endpoint
    # Livewire endpoint: POST /livewire/update
    # Payload: {"fingerprint": {...}, "serverMemo": {...}, "updates": [...]}

    # Step 4: For video, look for Vidstack player or animepahe iframe
    # Anizone embeds animepahe.pw as iframe
    iframe_src = soup.find("iframe", src=lambda s: s and "animepahe" in s)
    
    if iframe_src:
        # Follow the animepahe embed
        pahe_resp = session.get(iframe_src["src"])
        # Extract m3u8 from animepahe page
        m3u8_url = self._extract_from_animepahe(pahe_resp.text)
        return StreamResult(url=m3u8_url, source="anizone/animepahe")

    # Alternative: Look for Vidstack <media-player> element
    player = soup.find("media-player")
    if player:
        src = player.get("src")
        return StreamResult(url=src, source="anizone")

    raise ParserError("No video source found on AniZone")
```

**Specific Challenges:**
- Livewire component state — may need to send Livewire update requests to trigger episode changes
- animepahe.pw has its own anti-bot protection — may need `curl_cffi` with TLS impersonation
- Ad iframes pollute the DOM — need precise selectors

**Libraries:**
- `curl_cffi` for Cloudflare bypass
- `beautifulsoup4` + `lxml` for HTML parsing
- `re` (regex) for extracting video URLs from embedded JS

**Error Handling:**
| Error | Cause | Handler |
|-------|-------|---------|
| 403 Forbidden | Cloudflare block | Use impersonate="chrome120", retry with proxy |
| Anime not found | Invalid ID | Raise `AnimeNotFoundError`, return 404 to user |
| animepahe embed 404 | Video removed | Trigger fallback |

---

### 2.3 Source 3 — Miruro (`miruro.to`)

**Technology Stack:**
- **React SPA with SSR** — JavaScript-heavy, requires Playwright
- **Multiple built-in providers** with fallback chain (discovered in `__SSR_CONFIG__`)
- Provider order: `kiwi, pewe, bonk, bee, ally, moo, hop, nun, bun, twin, cog, telli`
- Uses **AniList GraphQL API** for metadata (`https://graphql.anilist.co`)
- Proxy layer with segment rotation for certain providers
- Built-in ad monetization (popcash, stake.us)
- Cloudflare with CF Beacon analytics
- Geo-detection (`window.__GEO__="PK"`)

**Key Discovery:** Miruro already implements the exact multi-source fallback pattern we want! The `__SSR_CONFIG__` in the HTML contains:
- `providerOrder` — the fallback chain
- Per-provider capabilities (sub, dub, download, skip_times)
- Parent/child relationships (some providers embed others)
- Proxy configuration (some providers proxy through Miruro's server)
- The `monkey` object (base64-decoded) contains ad config

**Scraping Approach: Playwright + Network Interception**

```python
# pseudocode for miruro_adapter.py

async def get_video_url(self, anilist_id: int, episode: int) -> StreamResult:
    """
    Miruro uses AniList IDs for lookup.
    URL pattern: https://www.miruro.to/watch/{anilist_id}?ep={episode}
    
    Strategy: Use Playwright, intercept all .m3u8 requests, return first match.
    This leverages Miruro's OWN multi-provider fallback!
    """
    page = await self.context.new_page()

    # Collect all .m3u8/.mp4 URLs from network
    captured_urls = []

    async def handle_request(request):
        if '.m3u8' in request.url or '.mp4' in request.url:
            captured_urls.append(request.url)

    page.on("request", handle_request)

    # Navigate to watch page
    await page.goto(
        f"https://www.miruro.to/watch/{anilist_id}?ep={episode}",
        wait_until="networkidle", 
        timeout=60000  # Longer timeout - Miruro tries multiple providers
    )

    # Wait for video to actually start loading
    await page.wait_for_selector("video, iframe[src*='player']", timeout=30000)

    # Return first captured stream URL
    if captured_urls:
        return StreamResult(url=captured_urls[0], source="miruro")

    # Fallback: try to extract from page state
    video_element = await page.query_selector("video source")
    if video_element:
        src = await video_element.get_attribute("src")
        return StreamResult(url=src, source="miruro")

    raise ParserError("No video URL found on Miruro")
```

**Alternative Approach — Reverse-Engineer Miruro's API:**

Miruro likely calls internal APIs to fetch stream URLs. By inspecting network traffic:
1. The page calls an API like `/api/episode/{id}` which returns provider data
2. Each provider has its own resolver endpoint
3. We could call these directly with `curl_cffi`

This would be faster than Playwright but requires reverse-engineering their API auth.

**Specific Challenges:**
- React-based — all content is JS-rendered, Playwright is essential
- Geo-blocking — uses `__GEO__` for region detection, might block some countries
- Ad popups — the `monkey` config shows popup ads on player interaction; need to handle/dismiss
- Rate limiting — Miruro makes many requests across providers, timeout must be generous

**Libraries:**
- `playwright` (essential)
- `playwright-stealth` (optional, patches Playwright for stealth)
- `curl_cffi` (for reverse-engineered API option)

**Error Handling:**
| Error | Cause | Handler |
|-------|-------|---------|
| All providers exhausted | Episode not on any Miruro source | Return `None`, try next top-level source |
| Geo-blocked | Region not supported | Use proxy, or fallback |
| 60s timeout | Miruro tried all providers slowly | Reduce timeout per provider within page |

---

## 3. Fallback Manager

### Design

```python
# fallback_manager.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import asyncio
import time

class SourceStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"    # Some failures, still usable
    DEAD = "dead"             # Too many failures, circuit open

@dataclass
class SourceState:
    name: str
    status: SourceStatus = SourceStatus.HEALTHY
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    circuit_open_until: float = 0.0

class FallbackManager:
    """
    Manages multi-source failover with circuit breaker pattern.
    
    Priority order: anidb -> anizone -> miruro
    """
    
    def __init__(self, config: dict):
        self.sources: list[SourceState] = [
            SourceState(name="anidb"),
            SourceState(name="anizone"),
            SourceState(name="miruro"),
        ]
        self.circuit_breaker_threshold = config.get("circuit_breaker_threshold", 5)
        self.circuit_breaker_timeout = config.get("circuit_breaker_timeout", 60)  # seconds
        self.max_retries_per_source = config.get("max_retries_per_source", 2)
        self.retry_base_delay = config.get("retry_base_delay", 1.0)  # seconds
    
    async def get_stream(self, adapters: dict, **params) -> StreamResult:
        """
        Try sources in priority order. Skip sources with open circuit breakers.
        
        Args:
            adapters: dict of {name: AdapterInstance}
            **params: anime_id, episode, etc.
        
        Returns:
            StreamResult on success
        
        Raises:
            AllSourcesExhaustedError if every source fails
        """
        last_error = None

        for source_state in self.sources:
            if not self._is_source_available(source_state):
                continue

            adapter = adapters[source_state.name]
            
            for attempt in range(self.max_retries_per_source):
                try:
                    delay = self.retry_base_delay * (2 ** attempt)  # exponential backoff
                    await asyncio.sleep(delay)
                    
                    result = await asyncio.wait_for(
                        adapter.get_video_url(**params),
                        timeout=30.0  # per-source timeout
                    )
                    
                    if result and result.url:
                        self._mark_success(source_state)
                        return result
                
                except asyncio.TimeoutError:
                    last_error = TimeoutError(f"{source_state.name} timed out")
                
                except Exception as e:
                    last_error = e

                self._mark_failure(source_state)

        raise AllSourcesExhaustedError(
            f"All sources failed. Last error: {last_error}"
        )

    def _is_source_available(self, source: SourceState) -> bool:
        """Check if circuit breaker is closed and source is usable."""
        if source.status == SourceStatus.DEAD:
            if time.time() > source.circuit_open_until:
                # Circuit breaker timeout expired, try again (half-open)
                source.status = SourceStatus.DEGRADED
                return True
            return False
        return True

    def _mark_failure(self, source: SourceState):
        source.failure_count += 1
        source.last_failure_time = time.time()
        
        if source.failure_count >= self.circuit_breaker_threshold:
            source.status = SourceStatus.DEAD
            source.circuit_open_until = time.time() + self.circuit_breaker_timeout

    def _mark_success(self, source: SourceState):
        source.failure_count = 0
        source.last_success_time = time.time()
        source.status = SourceStatus.HEALTHY

    def get_health_report(self) -> dict:
        """Return health status of all sources (for monitoring endpoint)."""
        return {
            s.name: {
                "status": s.status.value,
                "failure_count": s.failure_count,
                "last_success": s.last_success_time,
            }
            for s in self.sources
        }
```

### Retry Strategy

| Condition | Action |
|-----------|--------|
| First attempt fails (HTTP 5xx, timeout) | Retry after 1s |
| Second attempt fails | Retry after 2s |
| Third attempt fails | Mark source degraded, try next |
| Source fails 5x in 60s | Circuit breaker: mark DEAD, skip for 60s |
| Circuit timeout expires | Try source once (half-open), re-close if fails |

### Caching

```python
# Cache successful results in Redis (TTL: 10 minutes)
# Key: "stream:{source}:{anime_id}:{episode}"
# Value: JSON with video_url, subtitles, expires_at
```

---

## 4. Video Extraction & Processing

### Supported Formats

| Format | Extension | Typical Source |
|--------|-----------|----------------|
| HLS (HTTP Live Streaming) | `.m3u8` | Most sources |
| MPEG-DASH | `.mpd` | Some modern sources |
| Progressive MP4 | `.mp4` | Direct download links |

### Extraction Methods

**Method 1: Network Request Interception (Recommended)**

```python
# In Playwright, intercept ALL requests before navigation
# This catches .m3u8 URLs regardless of how the player loads them

captured_streams = []

page.on("request", lambda req: (
    captured_streams.append(req.url) 
    if any(ext in req.url for ext in ['.m3u8', '.mpd', '.mp4']) 
    else None
))

await page.goto(episode_url)
await asyncio.sleep(3)  # Let player initialize

# Filter for actual video streams (not ad segments)
video_url = next((url for url in captured_streams 
                  if self._is_video_stream(url)), None)
```

**Method 2: DOM Element Extraction**

```python
# For sites that set src directly on <video> or <iframe>

video_src = await page.evaluate("""
    () => {
        const video = document.querySelector('video');
        if (video && video.src) return video.src;
        const source = document.querySelector('video source');
        if (source) return source.src;
        const iframe = document.querySelector('iframe[src*="player"]');
        if (iframe) return iframe.src;
        return null;
    }
""")
```

**Method 3: JS Variable Extraction (for Miruro)**

```python
# Miruro stores stream data in React state / JS variables
# Extract from __SSR_CONFIG__ or window.__INITIAL_STATE__

stream_data = await page.evaluate("""
    () => {
        const config = window.__SSR_CONFIG__;
        return config ? config.streaming : null;
    }
""")
```

### URL Validation

```python
async def validate_stream_url(url: str) -> bool:
    """HEAD request to check if stream is accessible."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.head(url, timeout=10)
            return resp.status_code == 200
    except Exception:
        return False
```

### Subtitle Extraction

```python
# Look for <track> elements with .vtt or .srt sources
subtitles = await page.evaluate("""
    () => {
        const tracks = document.querySelectorAll('track');
        return Array.from(tracks).map(t => ({
            lang: t.srclang || 'en',
            label: t.label || '',
            url: t.src
        }));
    }
""")
```

### Response Format

```python
@dataclass
class StreamResult:
    url: str                          # .m3u8 or .mp4 URL
    source: str                       # "anidb", "anizone", "miruro"
    format: str = "hls"              # "hls", "dash", "mp4"
    subtitles: list[dict] = None     # [{lang, url, label}]
    thumbnails: str = None           # VTT thumbnail URL (if available)
    headers: dict = None             # Required headers (Referer, Origin)
    fallback_used: bool = False      # Was primary source unavailable?

class AllSourcesExhaustedError(Exception):
    def __init__(self, message: str):
        self.status_code = 502
        super().__init__(message)
```

---

## 5. Error Handling & Logging

### Error Hierarchy

```python
class ScraperError(Exception):
    """Base exception for all scraper errors."""
    pass

class SourceTimeoutError(ScraperError):
    """Source took too long to respond."""
    pass

class CloudflareBlockError(ScraperError):
    """Cloudflare JS challenge / 403."""
    pass

class ParserError(ScraperError):
    """HTML/JSON structure changed, parsing failed."""
    pass

class AnimeNotFoundError(ScraperError):
    """Anime ID not found on this source."""
    status_code = 404

class EpisodeNotFoundError(ScraperError):
    """Episode not available."""
    status_code = 404

class AllSourcesExhaustedError(ScraperError):
    """Every source in the fallback chain failed."""
    status_code = 502
```

### Logging Configuration (structlog)

```python
# logger.py
import structlog
import logging

def setup_logging(log_level: str = "INFO"):
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),  # Pretty local; JSONRenderer for prod
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(format="%(message)s", level=log_level)

log = structlog.get_logger()
```

### What to Log

| Event | Level | Fields |
|-------|-------|--------|
| Stream request received | INFO | anime_id, episode, user_ip |
| Adapter attempt started | DEBUG | source, attempt_number |
| Stream URL found | INFO | source, latency_ms |
| Source failed | WARNING | source, error_type, attempt |
| Circuit breaker opened | ERROR | source, failure_count |
| All sources exhausted | CRITICAL | anime_id, episode, all_errors |
| Parser structure change | ERROR | source, expected_selector, html_snippet |
| Cloudflare block detected | WARNING | source, status_code |

### Monitoring

- **Health endpoint**: `GET /api/health` returns per-source status
- **Prometheus metrics**: request count, latency histogram, error rate per source
- **Alerting**: When a source is DEAD for >5 minutes, trigger notification (Discord webhook, email)

---

## 6. Security & Anti-Detection

### Cloudflare Bypass Strategy

Cloudflare is the primary anti-bot protection used by all three sites. Here's how to handle each level:

| Challenge Level | Detection Method | Solution |
|-----------------|-----------------|----------|
| **No challenge** | Normal HTTP | Standard requests |
| **JS Challenge (5s)** | `__cf_chl_*` cookies | `curl_cffi` with `impersonate="chrome120"` |
| **Turnstile** | iframe captcha | Playwright + manual solve (or paid API) |
| **WAF block** | 403 by IP | Rotate residential proxies |

```python
# Using curl_cffi for Cloudflare bypass
from curl_cffi import requests

def get_with_cf_bypass(url: str) -> requests.Response:
    """Make request with Chrome TLS fingerprint to bypass CF JS challenge."""
    return requests.get(
        url,
        impersonate="chrome120",  # Mimics Chrome 120 TLS handshake
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30,
    )
```

### Playwright Stealth

```python
# Use playwright-stealth to patch navigator.webdriver, etc.
# pip install playwright-stealth

from playwright_stealth import stealth_sync, StealthConfig

# Apply stealth patches
await stealth_sync(page, StealthConfig(
    navigator_languages=True,
    navigator_vendor=True,
    navigator_plugins=True,
    webdriver=True,       # Hides navigator.webdriver = true
    chrome_runtime=True,  # Fakes chrome.runtime
    hairline=True,        # Fixes element size detection
))
```

### Proxy Rotation

```python
# config.py
PROXY_LIST = [
    "http://user:pass@proxy1:8080",
    "http://user:pass@proxy2:8080",
    # Rotate residential/datacenter proxies
]

# In Playwright
browser = await playwright.chromium.launch(
    proxy={"server": random.choice(PROXY_LIST)}
)
```

**Recommended proxy services for this use case:**
- BrightData (residential rotating) — best for Cloudflare
- Webshare — affordable datacenter proxies
- ScrapingBee/ScraperAPI — managed API (handles CF for you, but pricey)

### Rate Limiting

```python
import asyncio
import random

class RateLimiter:
    """Prevent IP bans by adding delays between requests."""
    
    def __init__(self, min_delay: float = 1.0, max_delay: float = 3.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
    
    async def wait(self):
        delay = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(delay)
```

### Ethical Guidelines

- Add a reasonable `User-Agent` identifying your service
- Respect `robots.txt` (though streaming sites rarely have one)
- Don't re-stream their video — pass the original URL to the user (reduces your bandwidth liability)
- Cache results aggressively to minimize re-scraping
- If a site contacts you to stop, comply immediately

---

## 7. Development Roadmap

### Phase 1: Single-Source Prototype (AniDB) — Week 1-2

**Goal**: Get one source working end-to-end.

- [ ] Set up project structure (FastAPI + Playwright + Redis)
- [ ] Implement AniDB adapter with Playwright
- [ ] Build video URL extraction (network interception)
- [ ] Create simple API endpoint (`GET /api/stream`)
- [ ] Add basic error handling and logging
- [ ] Test with 10+ different anime/episodes
- [ ] Write unit tests for AniDB adapter

**Deliverable**: Working API that returns AniDB video URLs

### Phase 2: Add AniZone — Week 3

**Goal**: Add second source, verify it works independently.

- [ ] Implement AniZone adapter with `curl_cffi`
- [ ] Handle animepahe.pw embed extraction
- [ ] Test with 10+ anime/episodes
- [ ] Identify CSRF/Livewire interaction pattern
- [ ] Write unit tests for AniZone adapter

**Deliverable**: AniZone adapter returns video URLs

### Phase 3: Add Miruro — Week 4

**Goal**: Add third source, leveraging its built-in provider chain.

- [ ] Implement Miruro adapter with Playwright + network interception
- [ ] Handle Miruro's multi-provider page load time
- [ ] Test with 10+ anime/episodes
- [ ] Evaluate reverse-engineering their API vs Playwright
- [ ] Write unit tests for Miruro adapter

**Deliverable**: Miruro adapter returns video URLs

### Phase 4: Integration & Fallback — Week 5

**Goal**: Wire everything together with intelligent failover.

- [ ] Implement FallbackManager (circuit breaker, retries, health check)
- [ ] Implement Orchestrator (unified anime ID resolution)
- [ ] Add Redis caching layer
- [ ] Integration tests (simulate failures)
- [ ] Add `/api/health` monitoring endpoint

**Deliverable**: Full fallback system working

### Phase 5: Hardening & Production — Week 6-7

**Goal**: Make it production-ready.

- [ ] Add proxy rotation
- [ ] Add structured logging (structlog)
- [ ] Add Prometheus metrics
- [ ] Load test with concurrent requests
- [ ] Write Dockerfile and docker-compose
- [ ] Deploy to VPS
- [ ] Set up monitoring/alerting
- [ ] Documentation

**Deliverable**: Production-deployed system

---

## 8. Testing Strategy

### Unit Tests (per adapter)

```python
# tests/adapters/test_anidb.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_anidb_extracts_video_url():
    """Verify AniDB adapter correctly parses video URL from page."""
    adapter = AniDBAdapter()
    
    with patch.object(adapter, "_get_page") as mock_page:
        mock_page.goto = AsyncMock()
        mock_page.eval_on_selector = AsyncMock(
            return_value="https://stream.example.com/video.m3u8"
        )
        
        result = await adapter.get_video_url("noragami-3819", 1)
        assert result.url == "https://stream.example.com/video.m3u8"
        assert result.source == "anidb"

@pytest.mark.asyncio
async def test_anidb_handles_timeout():
    """AniDB adapter should raise SourceTimeoutError on timeout."""
    adapter = AniDBAdapter()
    
    with patch.object(adapter, "_get_page") as mock_page:
        mock_page.goto = AsyncMock(side_effect=asyncio.TimeoutError())
        
        with pytest.raises(SourceTimeoutError):
            await adapter.get_video_url("naruto-10", 1)
```

### Integration Tests (fallback chain)

```python
# tests/test_fallback.py

@pytest.mark.asyncio
async def test_fallback_to_secondary_when_primary_fails():
    """When AniDB fails, system should try AniZone."""
    manager = FallbackManager(config={})
    adapters = {
        "anidb": MockAniDBAdapter(should_fail=True),
        "anizone": MockAniZoneAdapter(stream_url="https://anizone.example.com/vid.m3u8"),
        "miruro": MockMiruroAdapter(stream_url=None),
    }
    
    result = await manager.get_stream(adapters, anime_id="test", episode=1)
    
    assert result.source == "anizone"
    assert result.fallback_used == True

@pytest.mark.asyncio
async def test_all_sources_exhausted_raises_error():
    """When all sources fail, raise AllSourcesExhaustedError."""
    manager = FallbackManager(config={})
    adapters = {
        "anidb": MockAniDBAdapter(should_fail=True),
        "anizone": MockAniZoneAdapter(should_fail=True),
        "miruro": MockMiruroAdapter(should_fail=True),
    }
    
    with pytest.raises(AllSourcesExhaustedError, match="All sources failed"):
        await manager.get_stream(adapters, anime_id="test", episode=1)

@pytest.mark.asyncio
async def test_circuit_breaker_skips_dead_source():
    """After threshold failures, source should be skipped."""
    manager = FallbackManager(config={
        "circuit_breaker_threshold": 2,
        "circuit_breaker_timeout": 60,
    })
    
    # Fail 3 times (exceeds threshold of 2)
    adapters_failing = {
        "anidb": MockAniDBAdapter(should_fail=True),
        "anizone": MockAniZoneAdapter(stream_url="https://ok.com/v.m3u8"),
    }
    
    await manager.get_stream(adapters_failing, anime_id="t", episode=1)
    await manager.get_stream(adapters_failing, anime_id="t2", episode=1)
    await manager.get_stream(adapters_failing, anime_id="t3", episode=1)
    
    # AniDB should now be DEAD
    health = manager.get_health_report()
    assert health["anidb"]["status"] == "dead"
    assert health["anizone"]["status"] == "healthy"
```

### Performance Testing

```python
# artillery.yml - load test configuration
config:
  target: "http://localhost:8000"
  phases:
    - duration: 60
      arrivalRate: 5  # 5 requests per second

scenarios:
  - name: "Stream 10 anime concurrently"
    flow:
      - get:
          url: "/api/stream?anime_id={{ $randomChoice('1','2','3','...') }}&episode=1"
```

### Simulated Failure Tests

Use `pytest` with `vcrpy` or `responses` to replay recorded HTTP interactions and verify error handling:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,expected_error", [
    (403, CloudflareBlockError),
    (404, AnimeNotFoundError),
    (500, ScraperError),
    (502, ScraperError),
    (503, ScraperError),
])
async def test_adapter_handles_http_errors(status_code, expected_error):
    """Adapter should raise appropriate error for each HTTP status."""
    ...
```

---

## 9. Deployment & Maintenance

### Recommended Infrastructure

```
┌────────────────────────────────────┐
│  VPS (Hetzner / DigitalOcean)      │
│  4 vCPU, 8GB RAM, SSD              │
│                                    │
│  ┌──────────────────────────────┐  │
│  │  Docker Compose              │  │
│  │                              │  │
│  │  ┌────────┐  ┌──────────┐   │  │
│  │  │FastAPI │  │  Redis    │   │  │
│  │  │(scraper│  │  (cache)  │   │  │
│  │  │ + API) │  └──────────┘   │  │
│  │  └────────┘                  │  │
│  │  ┌────────┐  ┌──────────┐   │  │
│  │  │Nginx   │  │Prometheus│   │  │
│  │  │(proxy) │  │+ Grafana │   │  │
│  │  └────────┘  └──────────┘   │  │
│  └──────────────────────────────┘  │
└────────────────────────────────────┘
```

### Docker Setup

```dockerfile
# Dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    wget gnupg curl \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright + Chromium
RUN pip install playwright && playwright install --with-deps chromium

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY tests/ ./tests/

EXPOSE 8000
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379
      - LOG_LEVEL=INFO
    depends_on:
      - redis
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - api

volumes:
  redis_data:
```

### Maintenance Strategy

| Concern | Solution |
|---------|----------|
| **Site changes break parser** | Monitoring + e2e tests that run every 30min; alert on failure |
| **Source goes offline permanently** | Quick-swap adapter config, add new source |
| **Cloudflare upgrades protection** | Update `curl_cffi`; maintain proxy pool |
| **Anime ID mapping** | Build ID-mapping database across sources (AniList ID is canonical) |

### Monitoring Dashboard

- **Grafana dashboard** with panels for:
  - Request rate & latency (p50/p95/p99)
  - Success rate per source (AniDB %, AniZone %, Miruro %)
  - Circuit breaker status per source
  - Cache hit rate
  - Error distribution pie chart

---

## 10. Code Structure

```
anime-scraper/
├── src/
│   ├── __init__.py
│   ├── api.py                  # FastAPI application
│   ├── config.py               # Configuration (env vars, defaults)
│   ├── orchestrator.py         # Main entry point, coordinates everything
│   ├── fallback_manager.py     # Circuit breaker, retry, priority queue
│   │
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract BaseAdapter class
│   │   ├── anidb.py            # AniDB adapter (Playwright)
│   │   ├── anizone.py          # AniZone adapter (curl_cffi)
│   │   └── miruro.py           # Miruro adapter (Playwright)
│   │
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── video.py            # Generic video URL extraction utilities
│   │   ├── subtitles.py        # Subtitle (VTT/SRT) extraction
│   │   └── network.py          # Network interception helpers
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── stream.py           # StreamResult dataclass + exceptions
│   │   └── anime.py            # Anime metadata model
│   │
│   ├── cache/
│   │   ├── __init__.py
│   │   └── redis_cache.py      # Redis caching layer
│   │
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── rate_limit.py       # API rate limiting
│   │   └── error_handler.py    # Global exception -> HTTP response
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py           # structlog configuration
│       ├── http_client.py      # curl_cffi wrapper with retry
│       └── proxy.py            # Proxy pool rotation
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Shared fixtures (mock browser, mock Redis)
│   ├── adapters/
│   │   ├── test_anidb.py
│   │   ├── test_anizone.py
│   │   └── test_miruro.py
│   ├── test_fallback_manager.py
│   ├── test_orchestrator.py
│   ├── test_api.py
│   └── test_cache.py
│
├── scripts/
│   └── health_check.py         # Cron script to verify sources are alive
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

### Key Interfaces

```python
# adapters/base.py
from abc import ABC, abstractmethod
from ..models.stream import StreamResult

class BaseAdapter(ABC):
    """Every source adapter must implement this interface."""
    
    @abstractmethod
    async def get_video_url(self, anime_id: str, episode: int) -> StreamResult:
        """
        Extract the video stream URL for a given anime episode.
        
        Args:
            anime_id: Source-specific anime identifier
            episode: Episode number (1-indexed)
        
        Returns:
            StreamResult with video URL and metadata
        
        Raises:
            AnimeNotFoundError: Anime doesn't exist on this source
            EpisodeNotFoundError: Episode not available
            SourceTimeoutError: Request timed out
            CloudflareBlockError: Anti-bot protection blocked us
            ParserError: Site structure changed
        """
        ...

    @abstractmethod
    async def search(self, query: str) -> list[dict]:
        """Search for anime on this source. Returns list of {id, title, thumbnail}."""
        ...

    @abstractmethod
    async def check_health(self) -> bool:
        """Quick health check — is the source reachable?"""
        ...
```

---

## 11. API Endpoint Design

### Main Endpoint

```
GET /api/stream?anime_id={anilist_id}&episode={number}
```

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anime_id` | int | Yes | AniList anime ID (canonical identifier) |
| `episode` | int | Yes | Episode number (1-indexed) |
| `dub` | bool | No | Prefer dubbed version (default: false) |
| `quality` | str | No | Preferred quality: "360p","480p","720p","1080p" |

**Success Response (200):**

```json
{
  "status": "success",
  "data": {
    "video_url": "https://kiwi-cdn.example.com/streams/abc123/playlist.m3u8",
    "format": "hls",
    "source": "miruro",
    "subtitles": [
      {
        "lang": "en",
        "label": "English",
        "url": "https://subs.example.com/en.vtt"
      },
      {
        "lang": "ja",
        "label": "Japanese (CC)",
        "url": null
      }
    ],
    "thumbnails": null,
    "headers": {
      "Referer": "https://www.miruro.to/",
      "Origin": "https://www.miruro.to"
    },
    "fallback_used": true,
    "fallback_attempts": [
      {"source": "anidb", "error": "timeout"},
      {"source": "anizone", "error": "episode_not_found"}
    ]
  },
  "meta": {
    "response_time_ms": 2340,
    "cached": false
  }
}
```

**Anime Not Found (404):**

```json
{
  "status": "error",
  "error": {
    "code": "ANIME_NOT_FOUND",
    "message": "Anime with AniList ID 999999 not found on any source"
  }
}
```

**All Sources Exhausted (502):**

```json
{
  "status": "error",
  "error": {
    "code": "ALL_SOURCES_FAILED",
    "message": "Could not retrieve stream from any source",
    "details": {
      "anidb": "Cloudflare block (403)",
      "anizone": "Connection timeout (30s)",
      "miruro": "Parser error: video element not found"
    }
  }
}
```

### Additional Endpoints

```
GET  /api/health              # Source health status
GET  /api/search?q={query}    # Search across all sources (unified results)
GET  /api/anime/{id}           # Get anime metadata (synopsis, cover, episodes)
```

### Rate Limiting

```python
# Using slowapi (FastAPI-compatible)
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/stream")
@limiter.limit("30/minute")  # 30 requests per minute per IP
async def get_stream(request: Request, anime_id: int, episode: int):
    ...
```

---

## 12. Performance Considerations

### Caching Strategy

```
┌──────────┐    ┌──────────────┐    ┌─────────────┐
│ Request  │───►│ Check Redis  │───►│ Return cached│
│ arrives  │    │ (5ms)        │HIT │ result       │
└──────────┘    └──────┬───────┘    └─────────────┘
                       │MISS
                       ▼
              ┌────────────────┐
              │ Scrape source  │
              │ (2-30 seconds) │
              └───────┬────────┘
                      │
                      ▼
              ┌────────────────┐
              │ Store in Redis │
              │ (TTL: 10 min)  │
              └───────┬────────┘
                      │
                      ▼
              ┌────────────────┐
              │ Return result  │
              └────────────────┘
```

**Redis key patterns:**
```
stream:v2:{anilist_id}:{episode}       → {video_url, source, subtitles, expires}
source_health:{source_name}            → {status, last_check}
rate_limit:{ip_address}                → {request_count, window_start}
```

**TTL strategy:**
- Video URLs: 10 minutes (stream URLs typically expire in 1-2 hours)
- Health checks: 30 seconds
- Search results: 5 minutes
- Anime metadata: 1 hour

### Concurrency

```python
# FastAPI runs async — handles concurrent requests natively
# Key: Limit concurrent Playwright browser instances

import asyncio

class BrowserPool:
    """Pool of reusable browser instances to avoid launch overhead."""
    
    def __init__(self, max_browsers: int = 3):
        self.semaphore = asyncio.Semaphore(max_browsers)
        self.browsers: list = []
    
    async def acquire(self):
        await self.semaphore.acquire()
        # Reuse or create browser
    
    async def release(self, browser):
        # Return browser to pool
        self.semaphore.release()
```

### Timeout Hierarchy

```
Total request timeout:            45 seconds
  ├── AniDB scrape timeout:       30 seconds
  │   ├── Page navigation:        15 seconds
  │   └── Video element wait:     10 seconds
  ├── AniZone scrape timeout:     20 seconds
  └── Miruro scrape timeout:      40 seconds (longer — tries multiple providers)
```

### Memory Management

- Playwright Chromium: ~300-500MB per instance
- Use a browser pool with max 3 concurrent browsers
- Restart browsers after 100 pages to prevent memory leaks
- Redis: 256MB is plenty for caching

---

## 13. Frontend Integration

### Video Player Options

| Player | Pros | Cons | Best For |
|--------|------|------|----------|
| **Video.js** | Mature, plugins, HLS support | Heavy (200KB+) | Production sites |
| **Plyr** | Beautiful UI, lightweight | Limited plugin ecosystem | Quick setup |
| **hls.js** | Lightweight, just HLS | No UI (BYO controls) | Custom player |

**Recommended: Video.js + videojs-contrib-hls**

### Integration Code

```javascript
// Frontend: Call your API, then initialize player

async function loadAnimeEpisode(animeId, episode) {
  const player = document.getElementById('player');
  player.innerHTML = '<div class="loading">Finding stream...</div>';

  try {
    const response = await fetch(
      `/api/stream?anime_id=${animeId}&episode=${episode}`
    );
    const data = await response.json();

    if (data.status === 'success') {
      initVideoPlayer(data.data);
      
      // Show source indicator (optional)
      if (data.data.fallback_used) {
        console.log(`Fallback used. Stream from: ${data.data.source}`);
      }
    } else {
      player.innerHTML = `<div class="error">${data.error.message}</div>`;
    }
  } catch (error) {
    player.innerHTML = '<div class="error">Network error. Please retry.</div>';
  }
}

function initVideoPlayer(streamData) {
  const playerElement = document.getElementById('player');
  
  const video = document.createElement('video');
  video.id = 'anime-video';
  video.className = 'video-js vjs-default-skin vjs-big-play-centered';
  video.controls = true;
  video.preload = 'auto';
  video.crossOrigin = 'anonymous';
  
  // Add Referer header via a proxy if needed
  // Some CDNs require specific Referer to serve content
  video.src = streamData.video_url;
  
  // Add subtitles
  if (streamData.subtitles) {
    streamData.subtitles.forEach(sub => {
      const track = document.createElement('track');
      track.kind = 'subtitles';
      track.label = sub.label;
      track.srclang = sub.lang;
      track.src = sub.url;
      video.appendChild(track);
    });
  }
  
  playerElement.innerHTML = '';
  playerElement.appendChild(video);
  
  videojs(video, {
    fluid: true,
    playbackRates: [0.5, 1, 1.25, 1.5, 2],
    html5: {
      hls: {
        overrideNative: true,  // Use hls.js for HLS playback
      },
      nativeTextTracks: true,
    },
  });
}
```

### CORS Handling

Some video CDNs block cross-origin requests. Solutions:

1. **Proxy HLS segments through your server** (bandwidth-heavy, not recommended)
2. **Set CORS headers** via the video CDN (if the source allows `crossorigin="anonymous"`)
3. **Use `<video>` with `crossorigin="anonymous"`** — works for most HLS streams
4. **Serve video URL directly** — HLS .m3u8 files typically don't check Referer for segment requests

### HTML Template

```html
<!-- Stream page -->
<div class="video-container">
  <div id="player" class="video-js-container"></div>
  
  <div id="source-indicator" class="source-badge" style="display:none">
    Stream via <span id="source-name"></span>
  </div>
</div>

<script src="https://vjs.zencdn.net/8.10.0/video.min.js"></script>
<link href="https://vjs.zencdn.net/8.10.0/video-js.css" rel="stylesheet" />
```

---

## Appendix A: Anime ID Mapping

Since each source uses different ID systems, you need a mapping layer:

| Source | ID Format | Example | How to Resolve |
|--------|-----------|---------|----------------|
| **AniList (canonical)** | Numeric | `21` (One Piece) | Your canonical ID |
| AniDB | `{slug}-{numeric}` | `one-piece-21` | Search by title, derive slug |
| AniZone | Base62 hash | `1lbgjbgr` | Search by title, or maintain mapping DB |
| Miruro | AniList numeric | `21` | Same as canonical — no mapping needed |

**Strategy**: Use AniList as the canonical ID system. Build a mapping table in Redis/Postgres:

```sql
CREATE TABLE anime_mappings (
    anilist_id INTEGER PRIMARY KEY,
    anidb_slug VARCHAR(255),
    anizone_id VARCHAR(20),
    miruro_id INTEGER  -- same as anilist_id
);
```

Populate this by searching each source by title and storing the found ID.

---

## Appendix B: Dependency List (requirements.txt)

```
# Web framework
fastapi==0.115.0
uvicorn[standard]==0.30.0

# Browser automation
playwright==1.47.0

# HTTP clients (with TLS impersonation)
curl_cffi==0.7.0
httpx==0.27.0

# HTML parsing
beautifulsoup4==4.12.3
lxml==5.3.0

# Caching
redis==5.1.0
hiredis==2.4.0

# Logging
structlog==24.4.0

# Rate limiting
slowapi==0.1.9

# Monitoring
prometheus-client==0.20.0

# Config
pydantic==2.9.0
pydantic-settings==2.5.0
python-dotenv==1.0.1

# Testing
pytest==8.3.0
pytest-asyncio==0.24.0
pytest-mock==3.14.0
vcrpy==6.0.0
```

---

## Appendix C: Quick-Start Commands

```bash
# 1. Clone and setup
git clone <your-repo>
cd anime-scraper
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium

# 2. Configure
cp .env.example .env
# Edit .env with your Redis URL, proxy settings

# 3. Run Redis
docker run -d -p 6379:6379 redis:7-alpine

# 4. Run API
uvicorn src.api:app --reload --port 8000

# 5. Test
curl "http://localhost:8000/api/stream?anime_id=21&episode=1"

# 6. Health check
curl "http://localhost:8000/api/health"

# 7. Run tests
pytest tests/ -v

# 8. Production deploy
docker-compose up -d
```

---

*End of plan. Save this file as `PLAN.md` in your project root.*
