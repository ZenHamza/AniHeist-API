"""
Proxy pool with sing-box integration for bypassing Cloudflare CDN blocks.
Supports:
- HTTP/SOCKS5 proxies from config
- HTTP/SOCKS4/SOCKS5 from TheSpeedX/PROXY-List (free, updated daily)
- VLESS/VMess/Trojan/Shadowsocks proxies via sing-box tunnels
- Automatic proxy testing against target URLs
- Round-robin rotation
"""
import asyncio
import json
import os
import random
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx
import yaml

from src.config import settings
from src.utils.logger import get_logger

log = get_logger(__name__)

SING_BOX_BIN = os.environ.get("SING_BOX_BIN", "sing-box")
FREE_PROXY_DIR = os.environ.get("FREE_PROXY_DIR", "/home/kali/Desktop/free-vpn-subscriptions/output")

# TheSpeedX/PROXY-List — free HTTP/SOCKS4/SOCKS5 proxies, updated daily
PROXY_LIST_URLS = {
    "http": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "socks4": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
    "socks5": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
}


@dataclass
class ProxyNode:
    address: str
    protocol: str
    port: int
    name: str = ""
    socks_port: int = 0
    process: subprocess.Popen = None


class ProxyPool:
    def __init__(self):
        self.nodes: list[ProxyNode] = []
        self._index = 0
        self._lock = asyncio.Lock()

    async def load_from_config(self):
        """Load HTTP/SOCKS5 proxies from settings."""
        for proxy_url in settings.proxy_list:
            self.nodes.append(ProxyNode(
                address=proxy_url,
                protocol="http",
                port=0,
                name=f"config-{len(self.nodes)}",
            ))

        # Check for BrightData
        if settings.brightdata_username and settings.brightdata_password and settings.brightdata_host:
            proxy_url = f"http://{settings.brightdata_username}:{settings.brightdata_password}@{settings.brightdata_host}"
            self.nodes.append(ProxyNode(
                address=proxy_url,
                protocol="http",
                name="brightdata",
            ))

        log.info("Loaded proxies from config", count=len(self.nodes))

    async def load_from_speedx_list(self, max_per_type: int = 100):
        """Fetch free HTTP/SOCKS proxies from TheSpeedX/PROXY-List (updated daily)."""
        async with httpx.AsyncClient(timeout=15) as client:
            for ptype, url in PROXY_LIST_URLS.items():
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    proxies = [p.strip() for p in resp.text.strip().split("\n") if p.strip()]
                    random.shuffle(proxies)
                    for proxy in proxies[:max_per_type]:
                        self.nodes.append(ProxyNode(
                            address=f"{ptype}://{proxy}",
                            protocol=ptype,
                            port=0,
                            name=f"speedx-{ptype}-{proxy}",
                        ))
                    log.info(f"Loaded {len(proxies[:max_per_type])} {ptype} proxies from TheSpeedX")
                except Exception as e:
                    log.warning(f"Failed to fetch {ptype} proxies", error=str(e))

    async def load_from_free_pool(self, max_nodes: int = 50):
        """Load VPN protocol proxies from free-vpn-subscriptions and tunnel via sing-box."""
        clash_file = os.path.join(FREE_PROXY_DIR, "clash.yaml")
        if not os.path.exists(clash_file):
            log.warning("Free proxy pool not found", path=clash_file)
            return

        with open(clash_file) as f:
            data = yaml.safe_load(f)

        proxies = data.get("proxies", [])
        random.shuffle(proxies)

        started = 0
        for proxy in proxies[:max_nodes]:
            try:
                node = await self._start_singbox_tunnel(proxy)
                if node:
                    self.nodes.append(node)
                    started += 1
            except Exception as e:
                log.debug("Failed to start sing-box tunnel", error=str(e))

        log.info("Started sing-box tunnels", count=started, total=len(proxies[:max_nodes]))

    async def _start_singbox_tunnel(self, proxy: dict) -> Optional[ProxyNode]:
        """Start a sing-box SOCKS5 tunnel for a VPN protocol proxy."""
        ptype = proxy.get("type", "")
        if ptype not in ("ss", "vmess", "vless", "trojan", "hysteria2"):
            return None

        port = random.randint(30000, 31000)
        tag = proxy.get("name", f"proxy-{port}").replace(" ", "_")[:32]

        outbound = self._build_outbound(proxy, tag)
        if not outbound:
            return None

        config = {
            "log": {"level": "error", "output": "/dev/null"},
            "inbounds": [{
                "type": "socks",
                "tag": f"socks-{tag}",
                "listen": "127.0.0.1",
                "listen_port": port,
            }],
            "outbounds": [
                outbound,
                {"type": "direct", "tag": "direct"},
            ],
            "route": {
                "rules": [{"inbound": [f"socks-{tag}"], "outbound": tag}],
                "auto_detect_interface": True,
            },
        }

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(config, tmp)
        tmp.close()

        try:
            proc = await asyncio.create_subprocess_exec(
                SING_BOX_BIN, "run", "-c", tmp.name,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await asyncio.sleep(2)

            if proc.returncode is not None and proc.returncode != 0:
                os.unlink(tmp.name)
                return None

            log.debug("Sing-box tunnel started", tag=tag, port=port)
            return ProxyNode(
                address=f"socks5://127.0.0.1:{port}",
                protocol="socks5",
                port=port,
                name=tag,
                socks_port=port,
                process=proc,
            )
        except Exception:
            os.unlink(tmp.name)
            return None

    def _build_outbound(self, proxy: dict, tag: str) -> Optional[dict]:
        ptype = proxy.get("type")
        server = proxy.get("server")
        port = proxy.get("port")

        if ptype == "ss":
            return {
                "type": "shadowsocks",
                "tag": tag,
                "server": server,
                "server_port": port,
                "method": proxy.get("cipher", "aes-128-gcm"),
                "password": proxy.get("password", ""),
            }
        elif ptype == "vmess":
            return {
                "type": "vmess",
                "tag": tag,
                "server": server,
                "server_port": port,
                "uuid": proxy.get("uuid", ""),
                "encryption": proxy.get("cipher", "auto"),
                "alter_id": proxy.get("alterId", 0),
                "security": proxy.get("cipher", "auto"),
            }
        elif ptype == "vless":
            out = {
                "type": "vless",
                "tag": tag,
                "server": server,
                "server_port": port,
                "uuid": proxy.get("uuid", ""),
                "flow": proxy.get("flow", ""),
            }
            if proxy.get("tls", False):
                out["tls"] = {"enabled": True, "server_name": proxy.get("servername", server)}
            return out
        elif ptype == "trojan":
            out = {
                "type": "trojan",
                "tag": tag,
                "server": server,
                "server_port": port,
                "password": proxy.get("password", ""),
            }
            if proxy.get("tls", False):
                out["tls"] = {"enabled": True, "server_name": proxy.get("sni", server)}
            return out
        elif ptype == "hysteria2":
            return {
                "type": "hysteria2",
                "tag": tag,
                "server": server,
                "server_port": port,
                "password": proxy.get("password", ""),
                "tls": {"enabled": True, "server_name": proxy.get("sni", server)},
            }
        return None

    def get_proxy_url(self) -> Optional[str]:
        if not self.nodes:
            return settings.get_proxy() or None
        node = self.nodes[self._index % len(self.nodes)]
        self._index += 1
        return node.address

    async def find_working_for_url(self, target_url: str, max_tests: int = 30) -> Optional[str]:
        """Quick-test proxies against target URL, return first working one."""
        import random
        candidates = random.sample(self.nodes, min(max_tests, len(self.nodes)))
        for node in candidates:
            if await self.test_node(node, target_url):
                return node.address
        return None

    async def get_http_client(self, timeout: int = 15) -> httpx.AsyncClient:
        proxy_url = self.get_proxy_url()
        if proxy_url and proxy_url.startswith(("socks5", "socks4")):
            from httpx_socks import AsyncProxyTransport
            transport = AsyncProxyTransport.from_url(proxy_url)
            return httpx.AsyncClient(transport=transport, timeout=timeout)
        return httpx.AsyncClient(timeout=timeout, proxy=proxy_url)

    async def _make_client(self, node: ProxyNode, timeout: int):
        if node.protocol in ("socks5", "socks4"):
            from httpx_socks import AsyncProxyTransport
            transport = AsyncProxyTransport.from_url(node.address)
            return httpx.AsyncClient(transport=transport, timeout=timeout)
        proxy_url = node.address if node.protocol == "http" else None
        return httpx.AsyncClient(timeout=timeout, proxy=proxy_url)

    async def test_node(self, node: ProxyNode, target_url: str, timeout: int = 10) -> bool:
        try:
            async with await self._make_client(node, timeout) as client:
                resp = await client.get(target_url, follow_redirects=True)
                return resp.status_code == 200
        except Exception:
            return False

    async def find_working(self, target_url: str, max_tests: int = 20) -> Optional[str]:
        for node in self.nodes[:max_tests]:
            if await self.test_node(node, target_url):
                return node.address
        return None

    async def shutdown_all(self):
        for node in self.nodes:
            if node.process:
                try:
                    node.process.kill()
                    await asyncio.sleep(0.1)
                except Exception:
                    pass
        self.nodes.clear()


_proxy_pool_instance: Optional[ProxyPool] = None


async def get_proxy_pool() -> ProxyPool:
    global _proxy_pool_instance
    if _proxy_pool_instance is None:
        pool = ProxyPool()
        await pool.load_from_config()

        use_speedx = os.environ.get("USE_SPEEDX_PROXIES", "false").lower() == "true"
        if use_speedx:
            max_proxies = int(os.environ.get("SPEEDX_MAX_PER_TYPE", "100"))
            await pool.load_from_speedx_list(max_per_type=max_proxies)

        use_free_vpn = os.environ.get("USE_FREE_PROXY_POOL", "false").lower() == "true"
        if use_free_vpn:
            await pool.load_from_free_pool()

        _proxy_pool_instance = pool
    return _proxy_pool_instance


async def get_proxy_for_url(url: str) -> Optional[str]:
    pool = await get_proxy_pool()
    return pool.get_proxy_url()
