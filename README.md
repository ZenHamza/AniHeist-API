# path: README.md
# Anime Stream Scraper

Multi-source anime streaming scraper backend API with intelligent fallback, circuit breaker pattern, and caching. Supports three sources (AniDB, AniZone, Miruro) with automatic failover.

## Architecture

```
User Request → FastAPI → Orchestrator → FallbackManager → Adapters → Sources
                                ↓
                            Redis Cache
```

- **AniDB**: Playwright headless browser (JS-rendered React/Laravel)
- **AniZone**: curl_cffi with Chrome TLS impersonation (server-rendered Livewire)
- **Miruro**: Playwright with network interception (React SPA with multi-provider fallback)

## Quick Start

### Prerequisites

- Python 3.12+
- Redis 7+ (or Docker)
- Playwright browsers

### Local Development

```bash
# Clone and setup
git clone <repo-url>
cd anime-scraper
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Playwright browser
playwright install --with-deps chromium

# Configure environment
cp .env.example .env
# Edit .env as needed

# Start Redis (if not running)
docker run -d -p 6379:6379 redis:7-alpine

# Run API
uvicorn src.api:app --reload --port 8000

# Test it
curl "http://localhost:8000/api/stream?anime_id=21&episode=1"
curl "http://localhost:8000/api/health"
```

### Docker Deployment

```bash
docker-compose up -d --build
```

This starts:
- `api` - FastAPI application (2 workers, 2GB RAM limit)
- `redis` - Cache (256MB RAM limit, persistent storage)
- `nginx` - Reverse proxy with rate limiting

## API Endpoints

### GET /api/stream

Main endpoint to retrieve a video stream URL.

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anime_id` | int | Yes | AniList anime ID |
| `episode` | int | Yes | Episode number (1-indexed) |
| `dub` | bool | No | Prefer dubbed version |
| `quality` | str | No | Preferred quality (360p, 480p, 720p, 1080p) |

**Success Response (200):**

```json
{
  "status": "success",
  "data": {
    "video_url": "https://cdn.example.com/stream/playlist.m3u8",
    "format": "hls",
    "source": "miruro",
    "subtitles": [
      {"lang": "en", "label": "English", "url": "https://subs.example.com/en.vtt"}
    ],
    "thumbnails": null,
    "headers": {"Referer": "https://www.miruro.to/", "Origin": "https://www.miruro.to"},
    "fallback_used": false,
    "fallback_attempts": []
  },
  "meta": {"response_time_ms": 2340, "cached": false}
}
```

**Error Responses:**
- `404` - Anime or episode not found
- `502` - All sources exhausted
- `422` - Invalid parameters
- `504` - Source timeout

### GET /api/health

Check source health status.

### GET /api/search?q={query}

Search anime across all sources.

### POST /api/fallback/reset?source=anidb

Reset circuit breaker state for a source (or all if source omitted).

## Configuration

All configuration via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `MAX_BROWSERS` | `3` | Max concurrent Playwright browsers |
| `LOG_LEVEL` | `INFO` | Logging level |
| `RATE_LIMIT_PER_MINUTE` | `30` | API rate limit per IP |
| `CIRCUIT_BREAKER_THRESHOLD` | `5` | Failures before circuit opens |
| `CIRCUIT_BREAKER_TIMEOUT` | `60` | Seconds circuit stays open |
| `TOTAL_REQUEST_TIMEOUT` | `45` | Total request timeout in seconds |
| `PER_SOURCE_TIMEOUT` | `30` | Per-source timeout in seconds |

## Testing

```bash
pytest tests/ -v --asyncio-mode=auto
```

## Deployment

### VPS Requirements

- 4 CPU cores, 8GB RAM, 100GB SSD
- Docker and Docker Compose installed
- Domain name with DNS pointing to server IP

### Production Setup

```bash
# Clone and build
git clone <repo-url>
cd anime-scraper

# Configure for production
cp .env.example .env
# Edit .env with production values, proxy list, etc.

# Deploy with Docker
docker-compose up -d --build

# Set up SSL with Let's Encrypt
docker run --rm -v /etc/letsencrypt:/etc/letsencrypt \
    -v /var/www/html:/var/www/html \
    certbot/certbot certonly --webroot \
    -w /var/www/html -d your-domain.com

# View logs
docker-compose logs -f api
```

### System Resource Limits

| Container | CPU Limit | Memory Limit |
|-----------|-----------|--------------|
| api | 2 cores | 2GB |
| redis | 0.5 cores | 256MB |
| nginx | 0.5 cores | 128MB |

## Monitoring

- **Health endpoint**: `GET /api/health`
- **Cron script**: `python scripts/health_check.py` (run every 5 minutes)
- **Docker healthchecks**: Built-in container health monitoring
- **Nginx access/error logs**: In-container logging

## Legal Disclaimer

This software is for educational and research purposes only. Web scraping copyrighted content
without authorization may violate the Terms of Service of target websites and copyright laws
in your jurisdiction. The authors assume no liability for any use of this software.
