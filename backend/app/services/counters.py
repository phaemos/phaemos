"""
Fixed-window counters for the default limits, in Redis when it answers and in this process's memory when it does not.

A failure of Redis never blocks a request: the counter falls back to memory, one warning is logged for each outage and Redis
is tried again after 30 seconds. In development the counters are in memory only, so a test run is the same with or without a
Redis. With several workers the memory fallback counts per worker, which is the cost of staying up.
"""

import logging
import time

from app.config import settings

logger = logging.getLogger(__name__)
_now = time.time
RETRY_REDIS_AFTER = 30


class Counters:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self._memory: dict[str, tuple[int, float]] = {}
        self._client = None
        self._down_until = 0.0
        self._warned = False

    def _redis(self):
        if settings.is_development or _now() < self._down_until:
            return None
        if self._client is None:
            try:
                import redis

                self._client = redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
            except Exception as exc:  # noqa: BLE001
                self._failed(exc)
                return None
        return self._client

    def _failed(self, exc: Exception) -> None:
        self._down_until = _now() + RETRY_REDIS_AFTER
        self._client = None
        if not self._warned:
            # one line for each outage and none for each request
            self._warned = True
            logger.warning("rate limit counters fell back to memory because Redis failed (%s)", type(exc).__name__)

    def incr(self, key: str, ttl: int) -> int:
        """Add one to the counter and return it. The counter lasts `ttl` seconds from its first use."""
        full = self.prefix + key
        client = self._redis()
        if client is not None:
            try:
                count = int(client.incr(full))
                if count == 1:
                    client.expire(full, max(1, int(ttl)))
                if self._warned:
                    logger.warning("rate limit counters are back in Redis")
                    self._warned = False
                return count
            except Exception as exc:  # noqa: BLE001
                self._failed(exc)
        count, expires = self._memory.get(full, (0, 0.0))
        if expires <= _now():
            count, expires = 0, _now() + ttl
        self._memory[full] = (count + 1, expires)
        if len(self._memory) > 50_000:
            # bounded: drop what has expired and everything if that was not enough
            self._memory = {k: v for k, v in self._memory.items() if v[1] > _now()} if len(self._memory) < 100_000 else {}
        return count + 1

    def reset(self) -> None:
        self._memory.clear()
        client = self._redis()
        if client is not None:
            try:
                keys = list(client.scan_iter(match=self.prefix + "*", count=500))
                if keys:
                    client.delete(*keys)
            except Exception as exc:  # noqa: BLE001
                self._failed(exc)
