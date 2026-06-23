# path: src/middleware/rate_limit.py
from typing import Optional

from fastapi import Request, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded

from src.config import settings
from src.utils.logger import get_logger

log = get_logger(__name__)


class RateLimitMiddleware:
    def __init__(self, app, limit_per_minute: Optional[int] = None):
        self.limit = limit_per_minute or settings.rate_limit_per_minute
        self.limiter = Limiter(
            key_func=get_remote_address,
            default_limits=[f"{self.limit}/minute"],
            storage_uri="memory://",
        )
        app.state.limiter = self.limiter
        app.add_exception_handler(RateLimitExceeded, self._rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)

    @staticmethod
    async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        log.warning("Rate limit exceeded", ip=get_remote_address(request))
        raise HTTPException(
            status_code=429,
            detail={
                "status": "error",
                "error": {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit exceeded. {exc.detail}",
                },
            },
        )


rate_limiter = Limiter(key_func=get_remote_address)
