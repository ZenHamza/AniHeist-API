<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=0,2,3,6&height=200&section=header&text=AniHeist%20API&fontSize=60&fontAlignY=35&desc=Unified%20Anime%20Streaming%20Scraper&descAlignY=55&animation=fadeIn" width="100%"/>
</p>

<p align="center">
  <a href="https://api.aniheist.com/docs">
    <img src="https://img.shields.io/badge/API-Live-brightgreen?style=for-the-badge&logo=fastapi&logoColor=white" alt="API Status"/>
  </a>
  <a href="https://github.com/ZenHamza/AniHeist-API">
    <img src="https://img.shields.io/github/stars/ZenHamza/AniHeist-API?style=for-the-badge&logo=github&color=gold" alt="Stars"/>
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/Python-3.12+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  </a>
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker"/>
  <img src="https://img.shields.io/badge/License-MIT-purple?style=for-the-badge" alt="License"/>
</p>

<br/>

<div align="center">
  
  ```mermaid
  graph LR
      A[🎬 Frontend] --> B{🌐 api.aniheist.com}
      B --> C[🎯 Miruro Pipe<br/>7 Providers]
      C --> D[✅ ally - wixmp.com]
      C --> E[✅ pewe - anidb.app]
      C --> F[✅ bonk - vibeplayer.site]
      C --> G[⛔ kiwi/bee/moo/hop]
      B --> H[🔄 ReAnime API<br/>flixcloud.cc]
      B --> I[🌍 Playwright<br/>Browser Fallback]
      B --> J[🔒 Proxy Pool<br/>BrightData / Free]
      
      style A fill:#1a1a2e,stroke:#e94560,color:#fff
      style B fill:#16213e,stroke:#0f3460,color:#fff
      style D fill:#1b4332,stroke:#40916c,color:#fff
      style E fill:#1b4332,stroke:#40916c,color:#fff
      style F fill:#1b4332,stroke:#40916c,color:#fff
      style G fill:#4a0e0e,stroke:#e94560,color:#fff
  ```
  
</div>

<br/>

---

## ✨ Features

<table>
<tr>
<td width="33%" align="center">
  <h3>🎯 Triple-Core Engine</h3>
  <p>Miruro pipe API with 7 providers, ReAnime fallback, Playwright browser automation — auto-failover with circuit breaker pattern.</p>
</td>
<td width="33%" align="center">
  <h3>🛡️ Proxy Infrastructure</h3>
  <p>BrightData residential proxies, TheSpeedX free SOCKS pool, sing-box VPN tunnels (VLESS/VMess/Trojan/SS). Rotating pool with health checks.</p>
</td>
<td width="33%" align="center">
  <h3>⚡ Production Ready</h3>
  <p>Redis caching, rate limiting, structured logging, Prometheus metrics, Docker Compose deployment, SSL via Let's Encrypt.</p>
</td>
</tr>
</table>

<br/>

---

## 🚀 Quick Start

### One-Click Deploy

```bash
git clone https://github.com/ZenHamza/AniHeist-API.git
cd AniHeist-API
cp .env.example .env
# Edit .env with your Redis URL, proxy settings, etc.
docker compose up -d --build
```

### API Base

```
https://api.aniheist.com
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/stream?anime_id={id}&episode={n}` | Get stream URL (HLS/MP4) |
| `GET` | `/api/search?q={query}` | Search anime by title |
| `GET` | `/api/anime/{id}` | Get anime details & episodes |
| `GET` | `/api/trending` | Trending anime |
| `GET` | `/api/popular` | Popular anime |
| `GET` | `/api/health` | Service health status |
| `GET` | `/api/proxy/status` | Proxy pool status |
| `GET` | `/api/proxy/hls?url=...` | HLS segment proxy with header injection |

<br/>

<details>
<summary><b>📡 API Response Example</b></summary>

```json
{
  "status": "success",
  "data": {
    "video_url": "https://repackager.wixmp.com/.../master.m3u8",
    "format": "hls",
    "source": "miruro/ally",
    "subtitles": [
      {"lang": "English", "url": "https://.../subs.vtt"}
    ],
    "headers": {
      "Referer": "https://allmanga.to/",
      "Origin": "https://allmanga.to"
    }
  },
  "meta": {
    "response_time_ms": 248.7,
    "cached": false
  }
}
```
</details>

<br/>

---

## 🏗️ Architecture

<p align="center">
  <img src="https://mermaid.ink/img/pako:eNqNVM9v0zAU_ldezqlD_XOUVSBNlYCJMapJIMEB5bkvraXEiWzHXUX57zhJq7XrSntynu_7_nz2e0MVrwUpGNUGUukCVN1B0w2s4UuP19q6jK6YOFcGQ8BQ-6AG_PHzG5bviXZPRSXj3GhtaqVNoT1bS5kLdAm-FNRKJjDnFhB2KILTOihGWV3ESaoNSlI2GoxthVQWCozVHYTgRMWqOtlvR1f8pOj7a7xW7Zwv1t6x9aqdYq2dRFBLqmAdrWJ8q2t2tCn6sqS3wdhGNLFDRjH-yxanpQHjKmS0zK8EN3jE6NczVd2rksY1Zq8Z-4nPXvftl65rhmZoXqTh78PN0GtvH4bJZ_B_H2Wz-Xl6cZ4t5ll2mS0uc_OQb_NVvsqX-SrP8x_5Ol_mdNqscD1_ZPIuPV0dTdF0Np9f0B_68TdKTaVajFpo0FH54IKLRmlNR8N6pMB9RrR_oMkh0QFHdsu8hiOgI2pHS6S7tj1t27tOFD8e-G3HcM-KEWGIFOpl39gRYsR9CD8OmC3RGu8DUvhBQHvtVAtbk-RRJV0QngRrx0oHl2Dz0LAI3sj-KIN2DbiYeHOCTPcMXAjCOifJfydI9cD6gMj-Bmm-A70Pt1YfsnU9MqzhhWxk7bQkRoXvD8SukyA-1QvwqYPPjRut54FmtQwe6kDmd1jLrZ-KqJYCluMh1LSydGgVVtE8JsPG1ag8sBz1c7ceiBRHeTwmkx_UHK8Duw3HkzJqN5TjrlOPg5FtNBUBV8iFXjUxYqyh8OHq2XnFLoW4ce4Iftlpe5Lq_X5YXv1yP3Z7PJN7TvQvMQjTTA?type=svg"/>
</p>

### Source Priority Chain

```
Miruro Pipe API (ally/pewe/bonk)  →  200ms - 1s
        ↓ (fallback if no stream or CDN 403)
ReAnime API (reanime.to)          →  1s - 3s
        ↓ (fallback if API unreachable)
Playwright Browser (miruro.to)    →  3s - 8s
        ↓ (fallback if browser blocked)
Proxy Pool (BrightData/Free)      →  Configurable
```

<br/>

---

## 🔧 Proxy Configuration

### Option 1: BrightData (Residential — Recommended)

```env
BRIGHTDATA_USERNAME=your_username
BRIGHTDATA_PASSWORD=your_password
BRIGHTDATA_HOST=your_host.brightdata.io:22225
```

~$15/month — reliably bypasses Cloudflare CDN blocks.

### Option 2: Free SOCKS/HTTP Pool

```env
USE_SPEEDX_PROXIES=true
SPEEDX_MAX_PER_TYPE=100
```

Fetches ~7000+ live proxies from [TheSpeedX/PROXY-List](https://github.com/TheSpeedX/PROXY-List) (updated daily). Datacenter IPs — may not bypass all Cloudflare CDNs.

### Option 3: VPN Protocol Pool (sing-box)

```env
USE_FREE_PROXY_POOL=true
SING_BOX_BIN=/usr/local/bin/sing-box
```

Requires `sing-box` binary. Tunnels free VLESS/VMess/Trojan/Shadowsocks proxies from [free-vpn-subscriptions](https://github.com/Au1rxx/free-vpn-subscriptions).

### Option 4: Custom Proxy List

```env
PROXY_LIST=["http://user:pass@proxy1:8080","socks5://user:pass@proxy2:1080"]
PROXY_ROTATION_STRATEGY=round_robin
```

<br/>

---

## 🐳 Docker Stack

```yaml
services:
  api:       # FastAPI + Playwright + ReAnime (port 8000/4000)
  redis:     # Redis 7 cache (port 6379)
  nginx:     # Reverse proxy + SSL termination (port 80/443)
```

```bash
# Build & start
docker compose up -d --build

# View logs
docker compose logs -f api

# Restart a service
docker compose up -d --force-recreate api
```

<br/>

---

## 📊 Performance

| Metric | Value |
|--------|-------|
| Avg response time | 200ms - 1s (cached: ~5ms) |
| Cache TTL | 600s (stream), 3600s (metadata) |
| Rate limit | 30 req/min per IP |
| Circuit breaker | 5 failures → 60s cooldown |
| Providers covered | 7 (3 working CDNs) |
| Anime coverage | ~10,000+ titles via AniList |

<br/>

---

## 🛠️ Development

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Start API (dev)
uvicorn src.api:app --reload --host 0.0.0.0 --port 8000

# Start ReAnime API (dev)
uvicorn consumet_api.reanime_api:app --host 0.0.0.0 --port 4000
```

<br/>

---

## 📁 Project Structure

```
AniHeist-API/
├── src/                    # Main API application
│   ├── api.py              # FastAPI endpoints
│   ├── config.py           # Environment configuration
│   ├── orchestrator.py     # Request router
│   ├── fallback_manager.py # Circuit breaker + retry
│   ├── proxy_pool.py       # Proxy rotation (BrightData/free/sing-box)
│   ├── adapters/           # Streaming source adapters
│   │   ├── unified.py      # Master adapter with 3-tier fallback
│   │   ├── miruro.py       # Playwright-based Miruro adapter
│   │   ├── reanime.py      # ReAnime-API adapter
│   │   └── ...
│   ├── cache/              # Redis caching layer
│   ├── middleware/         # Rate limiting, error handling
│   ├── models/            # Pydantic data models
│   └── utils/             # Logger, HTTP client, helpers
├── consumet_api/          # Miruro pipe + ReAnime API
│   ├── miruro_pipe.py     # Direct pipe API (7 providers)
│   ├── reanime_api.py     # ReAnime streaming server
│   └── providers/         # JS provider scrapers
├── docker-compose.yml     # Production stack
├── Dockerfile             # API container
├── nginx.conf             # Reverse proxy config
├── requirements.txt       # Python dependencies
└── .env.example           # Configuration template
```

<br/>

---

## 📜 License

<p align="center">
  <sub>MIT &bull; Built with ❤️ by <a href="https://github.com/ZenHamza">ZenHamza</a></sub>
  <br/>
  <img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=0,2,3,6&height=120&section=footer" width="100%"/>
</p>
