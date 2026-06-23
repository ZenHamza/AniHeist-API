# path: src/fallback_manager.py
import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.models.stream import (
    StreamResult,
    FallbackAttempt,
    AllSourcesExhaustedError,
    ScraperError,
)
from src.utils.logger import get_logger
from src.config import settings

log = get_logger(__name__)


class SourceStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"


@dataclass
class SourceState:
    name: str
    status: SourceStatus = SourceStatus.HEALTHY
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    circuit_open_until: float = 0.0
    total_requests: int = 0
    total_failures: int = 0
    avg_response_time: float = 0.0


class FallbackManager:
    """
    Manages multi-source failover with circuit breaker pattern.

    Priority order: anidb -> anizone -> miruro
    Circuit breaker: after N consecutive failures, source is marked DEAD for T seconds.
    Retry: exponential backoff per source.
    """

    def __init__(self, config: Optional[dict] = None, source_order: Optional[list[str]] = None):
        cfg = config or {}
        if source_order is None:
            source_order = cfg.get("source_order", ["unified"])
        self.sources: list[SourceState] = [
            SourceState(name=name) for name in source_order
        ]
        self.circuit_breaker_threshold = cfg.get(
            "circuit_breaker_threshold", settings.circuit_breaker_threshold
        )
        self.circuit_breaker_timeout = cfg.get(
            "circuit_breaker_timeout", settings.circuit_breaker_timeout
        )
        self.max_retries_per_source = cfg.get(
            "max_retries_per_source", settings.max_retries_per_source
        )
        self.retry_base_delay = cfg.get(
            "retry_base_delay", settings.retry_base_delay
        )
        self.per_source_timeout = cfg.get(
            "per_source_timeout", settings.per_source_timeout
        )
        self.log = log

    async def get_stream(
        self, adapters: dict, anime_id: str, episode: int, **kwargs
    ) -> StreamResult:
        """
        Try sources in priority order. Skip sources with open circuit breakers.

        Args:
            adapters: dict of {name: AdapterInstance}
            anime_id: Source-specific anime identifier
            episode: Episode number

        Returns:
            StreamResult on success

        Raises:
            AllSourcesExhaustedError if every source fails
        """
        last_error: Optional[Exception] = None
        fallback_attempts: list[FallbackAttempt] = []
        total_start = time.monotonic()

        for source_state in self.sources:
            source_name = source_state.name
            adapter = adapters.get(source_name)
            if not adapter:
                self.log.warning("Adapter not found for source", source=source_name)
                continue

            if not self._is_source_available(source_state):
                self.log.info(
                    "Skipping source (circuit breaker open)",
                    source=source_name,
                    until=source_state.circuit_open_until,
                )
                continue

            for attempt in range(self.max_retries_per_source + 1):
                if time.monotonic() - total_start > settings.total_request_timeout:
                    raise AllSourcesExhaustedError(
                        f"Total request timeout ({settings.total_request_timeout}s) exceeded. "
                        f"Last error: {last_error}"
                    )

                source_state.total_requests += 1
                attempt_start = time.monotonic()
                try:
                    delay = self.retry_base_delay * (2**attempt)
                    if attempt > 0:
                        actual_delay = min(delay, 5.0)
                        self.log.debug(
                            "Retrying source with backoff",
                            source=source_name,
                            attempt=attempt + 1,
                            delay=actual_delay,
                        )
                        await asyncio.sleep(actual_delay)

                    result = await asyncio.wait_for(
                        adapter.get_video_url(
                            anime_id=anime_id, episode=episode, **kwargs
                        ),
                        timeout=self.per_source_timeout,
                    )

                    if result and result.url:
                        latency = (time.monotonic() - attempt_start) * 1000
                        source_state.last_success_time = time.time()
                        source_state.avg_response_time = (
                            source_state.avg_response_time * 0.9 + latency * 0.1
                            if source_state.avg_response_time
                            else latency
                        )
                        result.fallback_used = len(fallback_attempts) > 0
                        result.fallback_attempts = fallback_attempts
                        self._mark_success(source_state)
                        self.log.info(
                            "Stream found",
                            source=source_name,
                            latency_ms=round(latency, 1),
                            episode=episode,
                            fallback_used=result.fallback_used,
                        )
                        return result

                    if result is None:
                        raise ScraperError(f"{source_name} returned empty result")

                except asyncio.TimeoutError:
                    latency = (time.monotonic() - attempt_start) * 1000
                    err_msg = f"{source_name} timed out ({self.per_source_timeout}s)"
                    self._mark_failure(source_state)
                    last_error = TimeoutError(err_msg)
                    self.log.warning(
                        "Source timeout",
                        source=source_name,
                        attempt=attempt + 1,
                        latency_ms=round(latency, 1),
                    )
                    if attempt == self.max_retries_per_source:
                        fallback_attempts.append(
                            FallbackAttempt(
                                source=source_name,
                                error="timeout",
                                latency_ms=round(latency, 1),
                            )
                        )

                except ScraperError as e:
                    latency = (time.monotonic() - attempt_start) * 1000
                    self._mark_failure(source_state)
                    last_error = e
                    error_type = type(e).__name__
                    self.log.warning(
                        "Source error",
                        source=source_name,
                        error=error_type,
                        message=str(e),
                        attempt=attempt + 1,
                    )
                    if attempt == self.max_retries_per_source:
                        fallback_attempts.append(
                            FallbackAttempt(
                                source=source_name,
                                error=error_type,
                                latency_ms=round(latency, 1),
                            )
                        )

                except Exception as e:
                    latency = (time.monotonic() - attempt_start) * 1000
                    self._mark_failure(source_state)
                    last_error = e
                    self.log.error(
                        "Unexpected source error",
                        source=source_name,
                        error=str(e),
                        attempt=attempt + 1,
                    )
                    if attempt == self.max_retries_per_source:
                        fallback_attempts.append(
                            FallbackAttempt(
                                source=source_name,
                                error=type(e).__name__,
                                latency_ms=round(latency, 1),
                            )
                        )

        total_latency = (time.monotonic() - total_start) * 1000
        raise AllSourcesExhaustedError(
            f"All sources failed after {round(total_latency, 1)}ms. "
            f"Last error: {last_error}"
        )

    def _is_source_available(self, source: SourceState) -> bool:
        if source.status == SourceStatus.DEAD:
            if time.time() > source.circuit_open_until:
                source.status = SourceStatus.DEGRADED
                self.log.info(
                    "Circuit breaker half-open, retrying source", source=source.name
                )
                return True
            return False
        return True

    def _mark_failure(self, source: SourceState):
        source.failure_count += 1
        source.total_failures += 1
        source.last_failure_time = time.time()

        if source.failure_count >= self.circuit_breaker_threshold:
            was_dead = source.status == SourceStatus.DEAD
            source.status = SourceStatus.DEAD
            source.circuit_open_until = time.time() + self.circuit_breaker_timeout
            if not was_dead:
                self.log.error(
                    "Circuit breaker opened for source",
                    source=source.name,
                    failure_count=source.failure_count,
                    circuit_timeout=self.circuit_breaker_timeout,
                )

    def _mark_success(self, source: SourceState):
        source.failure_count = 0
        source.last_success_time = time.time()
        source.status = SourceStatus.HEALTHY

    def get_health_report(self) -> dict:
        return {
            s.name: {
                "status": s.status.value,
                "failure_count": s.failure_count,
                "total_requests": s.total_requests,
                "total_failures": s.total_failures,
                "last_success": s.last_success_time,
                "last_failure": s.last_failure_time,
                "circuit_open_until": s.circuit_open_until,
                "avg_response_time_ms": round(s.avg_response_time, 1) if s.avg_response_time else None,
            }
            for s in self.sources
        }

    async def reset_source(self, source_name: str):
        for s in self.sources:
            if s.name == source_name:
                s.status = SourceStatus.HEALTHY
                s.failure_count = 0
                s.circuit_open_until = 0.0
                self.log.info("Source state reset", source=source_name)
                return

    async def reset_all(self):
        for s in self.sources:
            s.status = SourceStatus.HEALTHY
            s.failure_count = 0
            s.circuit_open_until = 0.0
        self.log.info("All source states reset")
