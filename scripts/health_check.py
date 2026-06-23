# path: scripts/health_check.py
"""
Health check script for cron-based monitoring of all sources.

Usage:
    python scripts/health_check.py

Exit codes:
    0 - All sources healthy
    1 - One or more sources degraded
    2 - Critical failure (all sources down)
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.orchestrator import Orchestrator
from src.utils.logger import setup_logging, get_logger

setup_logging(log_level="INFO", json_output=True)
log = get_logger("health_check")


async def main():
    orchestrator = Orchestrator()
    try:
        await orchestrator.initialize()
        health = await orchestrator.get_health()

        all_healthy = all(
            s.get("healthy", False)
            for s in health.get("sources", {}).values()
        )
        any_healthy = any(
            s.get("healthy", False)
            for s in health.get("sources", {}).values()
        )

        log.info(
            "Health check completed",
            status=health.get("status"),
            sources=health.get("sources"),
            fallback=health.get("fallback_manager"),
        )

        if all_healthy:
            sys.exit(0)
        elif any_healthy:
            sys.exit(1)
        else:
            sys.exit(2)

    finally:
        await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
