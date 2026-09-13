"""Logging + request-ID middleware (Stage 0).

- stdlib logging configured once via setup_logging()
- RequestIDMiddleware adds X-Request-ID, logs method/path/status/duration
- Never log secrets (no headers/body logging here by design)
"""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_configured = False


def setup_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] [req=%(request_id)s] %(message)s"
        if False
        else "%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # Quiet noisy reload watchers slightly in dev
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    _configured = True


logger = logging.getLogger("app")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception("request failed method=%s path=%s req=%s %.1fms", request.method, request.url.path, request_id, elapsed_ms)
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request method=%s path=%s status=%s req=%s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
            elapsed_ms,
        )
        return response
