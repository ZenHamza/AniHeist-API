# path: src/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import json
import random


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = "Anime Stream Scraper"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"
    json_logging: bool = False

    redis_url: str = "redis://localhost:6379/0"
    redis_stream_ttl: int = 600
    redis_health_ttl: int = 30
    redis_search_ttl: int = 300
    redis_anime_ttl: int = 3600

    max_browsers: int = 3
    max_browser_pages: int = 100
    browser_restart_after: int = 50
    playwright_timeout: int = 30000
    navigation_timeout: int = 15000
    element_wait_timeout: int = 10000

    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60
    max_retries_per_source: int = 2
    retry_base_delay: float = 1.0
    per_source_timeout: float = 30.0
    total_request_timeout: float = 45.0

    rate_limit_per_minute: int = 30

    proxy_list: list[str] = []
    proxy_rotation_strategy: str = "round_robin"
    brightdata_username: str = ""
    brightdata_password: str = ""
    brightdata_host: str = ""

    anidb_base_url: str = "https://anidb.app"
    anizone_base_url: str = "https://anizone.to"
    miruro_base_url: str = "https://www.miruro.to"

    cors_origins: list[str] = ["*"]
    api_prefix: str = "/api"

    # Internal proxy rotation state
    _proxy_index: int = 0

    def get_proxy(self) -> Optional[str]:
        """Get the next proxy URL from the pool, or None if no proxies configured."""
        if self.brightdata_username and self.brightdata_password and self.brightdata_host:
            return f"http://{self.brightdata_username}:{self.brightdata_password}@{self.brightdata_host}"
        if not self.proxy_list:
            return None
        if self.proxy_rotation_strategy == "round_robin":
            proxy = self.proxy_list[self._proxy_index % len(self.proxy_list)]
            self._proxy_index += 1
            return proxy
        return random.choice(self.proxy_list)

    def model_post_init(self, __context):
        if isinstance(self.proxy_list, str):
            try:
                self.proxy_list = json.loads(self.proxy_list)
            except (json.JSONDecodeError, TypeError):
                self.proxy_list = []


settings = Settings()
