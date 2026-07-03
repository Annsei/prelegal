"""In-process rate limiting.

The deployment target is a single container running one uvicorn worker,
so an in-memory sliding window is sufficient — no Redis or shared store.
Counters reset on process restart, which is acceptable: the job here is
to blunt password brute-forcing and LLM-cost abuse, not to be perfect
accounting.

Caveat: keys are the direct client IP. Behind a reverse proxy every
request shares the proxy's IP — wire up X-Forwarded-For handling before
fronting this with one.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record one event for `key`; False if the window is already full."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            q = self._events[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        """Drop all counters. Test-harness hook."""
        with self._lock:
            self._events.clear()


# Login is the brute-force target: 10 attempts/min/IP still lets a fumbling
# human in but caps a dictionary run at ~14k guesses/day. Register is
# stricter (bulk account creation has no legitimate burst). Chat is per-user
# and mainly guards the OpenRouter bill against runaway clients.
LOGIN_LIMITER = SlidingWindowLimiter(10, 60.0)
REGISTER_LIMITER = SlidingWindowLimiter(5, 60.0)
CHAT_LIMITER = SlidingWindowLimiter(20, 60.0)

ALL_LIMITERS = (LOGIN_LIMITER, REGISTER_LIMITER, CHAT_LIMITER)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce(limiter: SlidingWindowLimiter, key: str) -> None:
    """Raise 429 when `key` exceeded the limiter's window.

    PRELEGAL_RATELIMIT_DISABLED=1 turns enforcement off — for test
    suites and load tooling that legitimately hammer endpoints.
    """
    if os.environ.get("PRELEGAL_RATELIMIT_DISABLED") == "1":
        return
    if not limiter.allow(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests — please wait a moment and retry.",
        )
