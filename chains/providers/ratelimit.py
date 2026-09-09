"""Shared token-bucket rate limiter.

Used by every outbound client (EODHD, SEC EDGAR). Lives on its own so a new
client does not have to import from an unrelated vendor module.
"""
from __future__ import annotations

import threading
import time

_TOKEN_EPSILON = 1e-9


class RateLimiter:
    """Thread-safe token bucket.

    The bucket starts **empty**. A bucket pre-filled to capacity lets the first
    minute issue capacity + rate requests -- twice the configured rate -- which
    is exactly what the first full EODHD backfill did (1,278 sym/min against a
    900 cap). Starting empty means no 60-second window can exceed the rate.

    ``time_fn``/``sleep_fn`` are injectable so tests can drive a virtual clock
    instead of waiting in real time.
    """

    def __init__(
        self,
        rate_per_min: int = 900,
        capacity: int | None = None,
        *,
        time_fn=time.monotonic,
        sleep_fn=time.sleep,
    ):
        if rate_per_min <= 0:
            raise ValueError("rate_per_min must be positive")
        self.rate_per_sec = rate_per_min / 60.0
        self.capacity = float(capacity if capacity is not None else rate_per_min)
        self._time = time_fn
        self._sleep = sleep_fn
        self._tokens = 0.0  # start empty: no opening burst
        self._last = self._time()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1) -> None:
        if tokens > self.capacity:
            raise ValueError("cannot acquire more tokens than the bucket capacity")
        while True:
            with self._lock:
                now = self._time()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._last) * self.rate_per_sec
                )
                self._last = now
                # Epsilon: refilling by exactly the computed wait can land a
                # hair short of the token through float rounding, which would
                # otherwise spin on ever-smaller sleeps.
                if self._tokens >= tokens - _TOKEN_EPSILON:
                    self._tokens = max(0.0, self._tokens - tokens)
                    return
                wait = (tokens - self._tokens) / self.rate_per_sec
            self._sleep(wait)
