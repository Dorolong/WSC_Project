import logging
import os
import threading
import time
from collections import deque

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


LOGGER = logging.getLogger("wsc.server")


def _env_bool(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


RATE_LIMIT_ENABLED = _env_bool("WSC_RATELIMIT_ENABLED", "1")
API_PER_MINUTE = _env_int("WSC_RATELIMIT_API_PER_MIN", "300")
RUN_CREATION_PER_HOUR = _env_int("WSC_RATELIMIT_RUN_PER_HOUR", "20")


class SlidingWindowLimiter:
    """In-memory sliding-window limiter.

    This server runs as a single uvicorn worker. If uvicorn --workers is raised
    above 1, each worker will count separately and a shared store such as Redis
    should replace this in-memory limiter.
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = max(int(limit), 0)
        self.window_seconds = int(window_seconds)
        self._events = {}
        self._lock = threading.Lock()
        self._last_cleanup = 0.0

    def check(self, key: str):
        if self.limit <= 0:
            return True, 0

        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window_seconds - now) + 1)
                self._cleanup_unlocked(now)
                return False, retry_after

            events.append(now)
            self._cleanup_unlocked(now)
            return True, 0

    def _cleanup_unlocked(self, now: float):
        if now - self._last_cleanup < 60:
            return
        cutoff = now - self.window_seconds
        stale_keys = []
        for key, events in self._events.items():
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                stale_keys.append(key)
        for key in stale_keys:
            self._events.pop(key, None)
        self._last_cleanup = now


api_limiter = SlidingWindowLimiter(API_PER_MINUTE, 60)
run_creation_limiter = SlidingWindowLimiter(RUN_CREATION_PER_HOUR, 60 * 60)


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not RATE_LIMIT_ENABLED or not request.url.path.startswith("/api/"):
            return await call_next(request)

        key = request.client.host if request.client else "-"
        allowed, retry_after = api_limiter.check(key)
        if allowed:
            return await call_next(request)

        LOGGER.warning(
            "rate limit exceeded scope=api key=%s path=%s retry_after=%s",
            key,
            request.url.path,
            retry_after,
        )
        return JSONResponse(
            status_code=429,
            content={"detail": f"요청이 너무 많아요. {retry_after}초 뒤에 다시 시도해주세요."},
            headers={"Retry-After": str(retry_after)},
        )


def enforce_run_creation_rate(user_id: str | None, path: str):
    if not RATE_LIMIT_ENABLED:
        return

    key = user_id or "_unknown"
    allowed, retry_after = run_creation_limiter.check(key)
    if allowed:
        return

    LOGGER.warning(
        "rate limit exceeded scope=run_creation user_id=%s path=%s retry_after=%s",
        key,
        path,
        retry_after,
    )
    raise HTTPException(
        status_code=429,
        detail=f"실행 요청이 너무 많아요. {retry_after}초 뒤에 다시 시도해주세요.",
        headers={"Retry-After": str(retry_after)},
    )
