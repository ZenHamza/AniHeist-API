# path: src/utils/proxy.py
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProxyConfig:
    proxies: list[str] = field(default_factory=list)
    rotation_strategy: str = "round_robin"  # round_robin, random, sticky
    current_index: int = 0
    sticky_session: Optional[str] = None


class ProxyPool:
    """Manages proxy rotation for requests."""

    def __init__(self, config: Optional[ProxyConfig] = None):
        self.config = config or ProxyConfig()
        self._sticky_map: dict[str, str] = {}

    def get_proxy(self, session_id: Optional[str] = None) -> Optional[str]:
        if not self.config.proxies:
            return None

        if self.config.rotation_strategy == "sticky" and session_id:
            if session_id in self._sticky_map:
                return self._sticky_map[session_id]
            proxy = self._round_robin_next()
            self._sticky_map[session_id] = proxy
            return proxy

        if self.config.rotation_strategy == "random":
            return random.choice(self.config.proxies)

        return self._round_robin_next()

    def _round_robin_next(self) -> str:
        proxy = self.config.proxies[self.config.current_index]
        self.config.current_index = (self.config.current_index + 1) % len(self.config.proxies)
        return proxy

    def add_proxy(self, proxy: str):
        if proxy not in self.config.proxies:
            self.config.proxies.append(proxy)

    def remove_proxy(self, proxy: str):
        if proxy in self.config.proxies:
            self.config.proxies.remove(proxy)

    @property
    def count(self) -> int:
        return len(self.config.proxies)

    def health_check(self, proxy: str) -> bool:
        return True
