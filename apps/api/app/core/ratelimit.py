"""Per-agent rate limit for the Edge intake routes (known gap: "ingestão sem rate-limit por agente").

A token bucket per (tenant, Edge) held IN THIS PROCESS: the API runs as one uvicorn process (compose), so the bucket is the whole truth; with more processes each would allow its own
budget (the limit would multiply by the process count: a bound, not a bypass). A restart refills every bucket (the Edge redelivers what it was told to wait for)
(429 is `Retry` to the Edge: the spool keeps the batch and sends it again later). The proxy's per-IP `limit_req` stays in front; this one is about a single agent that is authenticated but
misbehaves (loop, clock jump, replay storm) and would otherwise monopolise the database for everyone else.
"""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

# One bucket per (tenant, Edge): the keys are authenticated Edges, so thousands are already far beyond what one API process serves. Full-again buckets are dropped, ACTIVE ones never.
MAX_KEYS = 10_000


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
            if key not in self._buckets and len(self._buckets) >= MAX_KEYS:
                self._drop_idle(now)
                if len(self._buckets) >= MAX_KEYS:
                    return 1.0   # table full of agents that are all still inside their window: a NEW identity waits; an active bucket is never evicted (that would hand out a free burst)
            tokens, seen = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - seen) * self.rate)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return 0.0
            self._buckets[key] = (tokens, now)
            return (1.0 - tokens) / self.rate

    def _drop_idle(self, now: float) -> None:
        # a bucket that has REFILLED to the burst by now carries no information: dropping it changes nothing for that agent. Judged by the tokens it would hold now, not by when it was last
        # touched (a call that spends a token leaves it below the burst; a refused one cannot happen on a full bucket), so a sparse caller cannot pin its slot forever
        for k in [k for k, (tokens, seen) in self._buckets.items() if tokens + (now - seen) * self.rate >= self.burst]:
            del self._buckets[k]

    def retry_after(self, wait: float) -> int:
        return max(1, math.ceil(wait))
