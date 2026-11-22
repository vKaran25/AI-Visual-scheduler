"""In-process sliding-window limits for sign-in and sign-up.

State lives in this API process. Run one API process (render.yaml does) or move the counters to a shared
store before scaling out. Limits are checked before any password hashing, so floods are cheap to reject.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import TRUST_PROXY_HEADERS

SWEEP_THRESHOLD = 10_000


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        events = self._events.get(key)
        if events is None:
            return
        while events and now - events[0] > self.window:
            events.popleft()
        if not events:
            del self._events[key]

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            events = self._events.get(key)
            return bool(events) and len(events) >= self.limit

    def record(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._events) > SWEEP_THRESHOLD:
                for stale in list(self._events):
                    self._prune(stale, now)
            self._prune(key, now)
            self._events[key].append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


# Failed sign-ins are counted per account (stops guessing one password) and per client address.
SIGN_IN_FAILURES_PER_ACCOUNT = SlidingWindow(limit=5, window_seconds=15 * 60)
SIGN_IN_FAILURES_PER_CLIENT = SlidingWindow(limit=50, window_seconds=15 * 60)
SIGN_UPS_PER_CLIENT = SlidingWindow(limit=10, window_seconds=60 * 60)

ALL_LIMITS = (SIGN_IN_FAILURES_PER_ACCOUNT, SIGN_IN_FAILURES_PER_CLIENT, SIGN_UPS_PER_CLIENT)
SIGN_IN_LOCKED_MESSAGE = "Too many sign-in attempts. Wait a few minutes and try again."
SIGN_UP_LIMITED_MESSAGE = "Too many sign-up attempts from this network. Try again later."


def client_address(request: Request) -> str:
    """The address to limit by.

    Behind a trusted proxy (TRUST_PROXY_HEADERS=true) the proxy appends the real client to
    X-Forwarded-For, so the last entry is the one to use. Without a proxy the socket peer is used.
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        last_hop = forwarded.rsplit(",", 1)[-1].strip()
        if last_hop:
            return last_hop
    return request.client.host if request.client else "unknown"
