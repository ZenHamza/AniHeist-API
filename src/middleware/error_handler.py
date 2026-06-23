# path: src/middleware/error_handler.py
import traceback
from typing import Union

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.models.stream import (
    ScraperError,
    SourceTimeoutError,
    CloudflareBlockError,
    ParserError,
    AnimeNotFoundError,
    EpisodeNotFoundError,
    AllSourcesExhaustedError,
    ValidationError,
    BrowserPoolExhaustedError,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

ERROR_STATUS_CODES = {
    SourceTimeoutError: 504,
    CloudflareBlockError: 503,
    ParserError: 502,
    AnimeNotFoundError: 404,
    EpisodeNotFoundError: 404,
    AllSourcesExhaustedError: 502,
    ValidationError: 422,
    BrowserPoolExhaustedError: 503,
}


class ErrorHandlerMiddleware:
    """Global exception handler mapping scraper errors to HTTP responses."""

    def __init__(self, app: FastAPI):
        self.app = app
        self._register_handlers()

    def _register_handlers(self):
        @self.app.exception_handler(ScraperError)
        async def scraper_error_handler(request: Request, exc: ScraperError):
            status_code = ERROR_STATUS_CODES.get(type(exc), exc.status_code)
            error_type = type(exc).__name__

            log.error(
                "Scraper error",
                error_type=error_type,
                message=str(exc),
                status_code=status_code,
                path=str(request.url.path),
            )

            return JSONResponse(
                status_code=status_code,
                content={
                    "status": "error",
                    "error": {
                        "code": error_type.upper(),
                        "message": str(exc),
                    },
                },
            )

        @self.app.exception_handler(AllSourcesExhaustedError)
        async def all_sources_exhausted_handler(request: Request, exc: AllSourcesExhaustedError):
            log.critical(
                "All sources exhausted",
                message=str(exc),
                path=str(request.url.path),
            )

            return JSONResponse(
                status_code=502,
                content={
                    "status": "error",
                    "error": {
                        "code": "ALL_SOURCES_FAILED",
                        "message": "Could not retrieve stream from any source",
                        "details": {},
                    },
                },
            )

        @self.app.exception_handler(Exception)
        async def generic_error_handler(request: Request, exc: Exception):
            log.error(
                "Unhandled exception",
                error_type=type(exc).__name__,
                message=str(exc),
                path=str(request.url.path),
                traceback=traceback.format_exc(),
            )

            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "An unexpected error occurred",
                    },
                },
            )


def setup_error_handlers(app: FastAPI):
    ErrorHandlerMiddleware(app)
