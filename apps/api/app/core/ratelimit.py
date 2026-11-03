"""Per-agent rate limit for the Edge intake routes (known gap: "ingestão sem rate-limit por agente").

A token bucket per (tenant, Edge) held IN THIS PROCESS: the API runs as one uvicorn process (compose), so the bucket is the whole truth; with more processes each would allow its own
budget (the limit would multiply by the process count: a bound, not a bypass). A restart refills every bucket, which is the safe side for a data intake the Edge redelivers
(429 is `Retry` to the Edge: the spool keeps the batch and sends it again later). The proxy's per-IP `limit_req` stays in front; this one is about a single agent that is authenticated but
misbehaves (loop, clock jump, replay storm) and would otherwise monopolise the database for everyone else.
"""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

MAX_KEYS = 10_000   # a bucket per (tenant, Edge): thousands of agents are already far beyond what one API process serves; past this, idle buckets are dropped first


class TokenBucketLimiter:
    def __init__(self, *, burst: int, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        if burst < 1 or per_minute < 1:
            raise ValueError("burst and per_minute must be >= 1")
        self.burst = float(burst)
        self.rate = per_minute / 60.0   # tokens per second
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}   # key -> (tokens, last seen)

    def take(self, key: str) -> float:
        """0.0 if the call may proceed (one token spent); otherwise the seconds until a token exists. Never raises."""
        now = self._clock()
        with self._lock:
            tokens, seen = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - seen) * self.rate)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                self._trim(now)
                return 0.0
            self._buckets[key] = (tokens, now)
            self._trim(now)
            return (1.0 - tokens) / self.rate

    def _trim(self, now: float) -> None:
        if len(self._buckets) <= MAX_KEYS:
            return
        # a bucket idle long enough to be full again carries no information: dropping it changes nothing
        full_after = self.burst / self.rate
        for k in [k for k, (_, seen) in self._buckets.items() if now - seen >= full_after]:
            del self._buckets[k]
        if len(self._buckets) > MAX_KEYS:   # still too many, all recently active: forget the least recently seen (they refill for free: the safe side)
            for k, _ in sorted(self._buckets.items(), key=lambda kv: kv[1][1])[: len(self._buckets) - MAX_KEYS]:
                del self._buckets[k]

    def retry_after(self, wait: float) -> int:
        return max(1, math.ceil(wait))
