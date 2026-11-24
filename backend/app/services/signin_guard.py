"""
Slowing down password guessing without letting a stranger lock anyone out.

The old rule locked an account for 15 minutes after five wrong passwords, so anyone who knew an address could keep
that person out for ever. A failure is now counted against where it came from and delays that place only.

| What is counted                  | Window | Threshold | What happens                                                        |
| -------------------------------- | ------ | --------- | ------------------------------------------------------------------- |
| failures for one account from    | 15 min | 5         | that source waits 30 s, then 60 s, 120 s and so on up to 15 minutes |
| one source (an IPv6 /64)         |        |           | after its last failure. Other sources are not affected at all       |
| failures for one account from    | 1 hour | 30        | attempts from a browser that has not signed in to this account     |
| every source together            |        |           | before are let through one every 10 seconds. A browser that has     |
|                                  |        |           | signed in before (its signed cookie) is not slowed and an admin    |
|                                  |        |           | account is never slowed this way. The owner is emailed once a day.  |

An unknown address is counted exactly like a known one (it is keyed by a hash of the address), so neither the delay,
the status nor the text says whether an account exists. A correct password is never refused for the number of wrong
ones. What a stranger with many addresses can still do: guess at one try every 10 seconds per account (about 8,600 a
day) against a password that has to survive that, at the cost of being seen by the owner's email. Admin accounts are
not slowed account-wide, so a stranger cannot slow an admin down at all and rely on the per-source delay, the per
address rate limit, two-step sign-in and the alert to the owner.
"""

import hashlib
import math
import time
from contextvars import ContextVar
from fastapi import HTTPException

from app.errors import ApiError, Code
from app.config import settings

# where the current request came from, set by the middleware for every request. "unknown" outside a request
current_source: ContextVar[str] = ContextVar("current_source", default="unknown")

PAIR_WINDOW = 15 * 60
PAIR_FREE = 5            # failures from one source before it is delayed
PAIR_BASE_DELAY = 30     # seconds, doubling each further failure
PAIR_MAX_DELAY = 15 * 60
ACCOUNT_WINDOW = 60 * 60
ACCOUNT_THRESHOLD = 30   # failures from all sources in an hour before untrusted browsers are slowed
ACCOUNT_SLOT = 10        # seconds between attempts from an untrusted browser once it is slowed
NOTIFY_EVERY = 24 * 60 * 60

# the clock, so tests can move it
_now = time.time


class _Memory:
    """Counters in this process. Used when Redis is not reachable and in tests."""

    def __init__(self):
        self.values: dict[str, tuple[float, float]] = {}

    def _live(self, key):
        item = self.values.get(key)
        if item is None:
            return None
        if item[1] <= _now():
            del self.values[key]
            return None
        return item

    def incr(self, key, ttl):
        item = self._live(key)
        count = (item[0] if item else 0) + 1
        self.values[key] = (count, item[1] if item else _now() + ttl)
        return int(count)

    def get(self, key):
        item = self._live(key)
        return item[0] if item else None

    def set(self, key, value, ttl):
        self.values[key] = (value, _now() + ttl)

    def set_nx(self, key, ttl):
        if self._live(key):
            return False
        self.values[key] = (1, _now() + ttl)
        return True

    def delete(self, *keys):
        for k in keys:
            self.values.pop(k, None)


_memory = _Memory()
_redis = None
_redis_down_until = 0.0
memory_only = False   # tests set this so counters never leak between runs through a shared Redis


def _client():
    global _redis, _redis_down_until
    if memory_only or _now() < _redis_down_until:
        return None
    if _redis is None:
        try:
            import redis
            _redis = redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
        except Exception:  # noqa: BLE001
            _redis_down_until = _now() + 30
            return None
    return _redis


class _Store:
    """Redis when it answers, this process's memory when it does not. A failure never blocks a sign-in."""

    prefix = "phaemos:signin:"

    def _try(self, redis_call, memory_call):
        global _redis_down_until
        client = _client()
        if client is not None:
            try:
                return redis_call(client)
            except Exception as exc:  # noqa: BLE001
                _redis_down_until = _now() + 30
                import logging
                logging.getLogger(__name__).warning("sign-in counters fell back to memory because Redis failed (%s)", type(exc).__name__)
        return memory_call()

    def incr(self, key, ttl):
        k = self.prefix + key

        def via_redis(c):
            count = c.incr(k)
            if count == 1:
                c.expire(k, ttl)
            return int(count)
        return self._try(via_redis, lambda: _memory.incr(k, ttl))

    def get(self, key):
        k = self.prefix + key
        return self._try(lambda c: (lambda v: float(v) if v is not None else None)(c.get(k)), lambda: _memory.get(k))

    def set(self, key, value, ttl):
        k = self.prefix + key
        return self._try(lambda c: c.set(k, value, ex=max(1, int(ttl))), lambda: _memory.set(k, value, ttl))

    def set_nx(self, key, ttl):
        k = self.prefix + key
        return self._try(lambda c: bool(c.set(k, 1, nx=True, ex=max(1, int(ttl)))), lambda: _memory.set_nx(k, ttl))

    def delete(self, *keys):
        ks = [self.prefix + k for k in keys]
        return self._try(lambda c: c.delete(*ks), lambda: _memory.delete(*ks))


store = _Store()


def reset() -> None:
    """Forget every count. For tests."""
    _memory.values.clear()


def account_key(user_id=None, email: str | None = None) -> str:
    """The key counts are kept under. A known account by its id, an unknown address by a hash of it, in one shape."""
    if user_id is not None:
        return "a:" + hashlib.sha256(str(user_id).encode()).hexdigest()[:32]
    return "a:" + hashlib.sha256((email or "").strip().lower().encode()).hexdigest()[:32]


def _delay_for(failures: int) -> int:
    if failures < PAIR_FREE:
        return 0
    return min(PAIR_BASE_DELAY * 2 ** (failures - PAIR_FREE), PAIR_MAX_DELAY)


def _refuse(seconds: float, where: str) -> HTTPException:
    wait = max(1, math.ceil(seconds))
    return ApiError(429, Code.SIGN_IN_SLOWED, f"Too many failed attempts {where}. Try again in {wait} seconds.", headers={"Retry-After": str(wait)})


def check(key: str, admin: bool = False, trusted_browser: bool = False, source: str | None = None) -> None:
    """Raise 429 when this source must wait or when the account is being guessed at and this browser is not known."""
    source = source or current_source.get()
    until = store.get(f"pair:{key}:{source}:until")
    if until is not None and until > _now():
        raise _refuse(until - _now(), "from here")
    if admin or trusted_browser:
        return
    failures = store.get(f"acct:{key}") or 0
    if failures >= ACCOUNT_THRESHOLD and not store.set_nx(f"slot:{key}", ACCOUNT_SLOT):
        raise _refuse(ACCOUNT_SLOT, "on this account")


def record_failure(key: str, source: str | None = None) -> int:
    """Count a wrong password or code. Returns the failures for this account across every source in the window."""
    source = source or current_source.get()
    pair = store.incr(f"pair:{key}:{source}", PAIR_WINDOW)
    delay = _delay_for(pair)
    if delay:
        store.set(f"pair:{key}:{source}:until", _now() + delay, delay + 1)
    return store.incr(f"acct:{key}", ACCOUNT_WINDOW)


def record_success(key: str, source: str | None = None) -> None:
    """A right password clears this source's count. The account-wide count is left to run out, so a stranger who
    happens to guess right does not erase the evidence."""
    source = source or current_source.get()
    store.delete(f"pair:{key}:{source}", f"pair:{key}:{source}:until")


def should_notify(key: str) -> bool:
    """True the first time in a day that this account is past the threshold, so the owner is mailed at most once a day."""
    return store.set_nx(f"notified:{key}", NOTIFY_EVERY)


def over_threshold(failures: int) -> bool:
    return failures >= ACCOUNT_THRESHOLD


def proof_rate_ok(key: str, per_minute: int = 20) -> bool:
    """A cap on how often one admin account may present a fresh proof, so the proof routes are not a bcrypt oracle."""
    return store.incr(f"proof:{key}:{int(_now() // 60)}", 90) <= per_minute
