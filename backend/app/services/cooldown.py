"""
Cooldown - repeat windows and daily caps for notifications.

Redis holds the keys so every API worker shares them. If Redis cannot be
reached the keys live in this process instead, so a Redis outage never turns
into a text message on every reading.
"""

import functools
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from app.config import settings

_log = logging.getLogger(__name__)

# after one failed Redis call every call uses process memory for this long without trying Redis. A Redis host that
# accepts no packets would otherwise cost the socket timeout on every call and a breached rule makes several calls
# on the telemetry request, which a node waits only a couple of seconds for
REDIS_RETRY_AFTER_S = 30
# monotonic time before which Redis is not tried
_redis_down_until = 0.0

# key -> expiry on the monotonic clock
_local: dict[str, float] = {}
# daily key -> (count, expiry as a UTC timestamp)
_local_daily: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()


@functools.lru_cache(maxsize=1)
def _client():
    # imported lazily so the module loads even when redis is absent.
    import redis

    return redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)


def _redis_usable() -> bool:
    return time.monotonic() >= _redis_down_until


def _redis_failed() -> None:
    global _redis_down_until
    _redis_down_until = time.monotonic() + REDIS_RETRY_AFTER_S


def _acquire_local(key: str, seconds: int) -> bool:
    now = time.monotonic()
    with _lock:
        for stale in [k for k, expires in _local.items() if expires <= now]:
            del _local[stale]
        if key in _local:
            return False
        _local[key] = now + seconds
        return True


def acquire(key: str, seconds: int) -> bool:
    """True when the caller may notify now. False when the key is still cooling down."""
    if _redis_usable():
        try:
            # SET NX EX is atomic, so two workers cannot both pass.
            return bool(_client().set(key, "1", nx=True, ex=seconds))
        except Exception as exc:
            _redis_failed()
            _log.warning("cooldown store unavailable (%s): using process memory", type(exc).__name__)
    return _acquire_local(key, seconds)


def release(key: str) -> None:
    """Free a key early, so a send that failed can be tried again on the next reading."""
    with _lock:
        _local.pop(key, None)
    if not _redis_usable():
        return
    try:
        _client().delete(key)
    except Exception as exc:
        _redis_failed()
        _log.warning("cooldown store unavailable (%s): key left to expire", type(exc).__name__)


def shorten(key: str, seconds: int) -> None:
    """
    Cut a key's remaining life to `seconds`, so a send that failed is tried again after a short wait and not at once
    on the next reading and not only after the whole window. One dead endpoint is then tried once a minute.
    """
    with _lock:
        _local[key] = time.monotonic() + seconds
    if not _redis_usable():
        return
    try:
        _client().expire(key, seconds)
    except Exception as exc:
        _redis_failed()
        _log.warning("cooldown store unavailable (%s): key left to expire", type(exc).__name__)


def extend(key: str, seconds: int) -> None:
    """Set a key's remaining life to `seconds`: the hour once a send has gone through. The same step as shorten."""
    shorten(key, seconds)


def _end_of_utc_day(now: datetime) -> datetime:
    return datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)


def take_daily(channel: str, cap: int, amount: int = 1, now: datetime | None = None) -> bool:
    """Count amount sends against the channel's cap for the current UTC day.

    False when the cap is reached. The first refusal of a day logs one warning.
    """
    now = now or datetime.now(timezone.utc)
    key = f"phaemos:alert-daily:{channel}:{now:%Y%m%d}"
    expires = _end_of_utc_day(now)
    total = None
    if _redis_usable():
        try:
            client = _client()
            total = int(client.incrby(key, amount))
            # the key lives until the day ends, so the count starts again at midnight UTC
            client.expireat(key, int(expires.timestamp()))
        except Exception as exc:
            _redis_failed()
            _log.warning("cooldown store unavailable (%s): using process memory", type(exc).__name__)
            total = None
    if total is None:
        with _lock:
            for stale in [k for k, (_, exp) in _local_daily.items() if exp <= now.timestamp()]:
                del _local_daily[stale]
            total = _local_daily.get(key, (0, 0.0))[0] + amount
            _local_daily[key] = (total, expires.timestamp())
    if total <= cap:
        return True
    if total - amount <= cap:
        # logged only on the first refusal, so a stuck rule does not fill the log
        _log.warning("daily %s alert cap of %s reached: further alerts are skipped until midnight UTC", channel, cap)
    return False


def _daily_key(channel: str, now: datetime) -> str:
    return f"phaemos:alert-daily:{channel}:{now:%Y%m%d}"


def daily_used(channel: str, now: datetime | None = None) -> int:
    """How many messages the channel has had accepted today (UTC), without counting anything."""
    now = now or datetime.now(timezone.utc)
    key = _daily_key(channel, now)
    if _redis_usable():
        try:
            return int(_client().get(key) or 0)
        except Exception as exc:
            _redis_failed()
            _log.warning("cooldown store unavailable (%s): using process memory", type(exc).__name__)
    with _lock:
        return _local_daily.get(key, (0, 0.0))[0]


def count_daily(channel: str, amount: int = 1, now: datetime | None = None) -> int:
    """
    Count amount messages that the vendor accepted against today's total for the channel and return the new total.

    The count is taken after the send and not before, so a vendor outage that fails every send cannot use up the day.
    """
    now = now or datetime.now(timezone.utc)
    key = _daily_key(channel, now)
    expires = _end_of_utc_day(now)
    if _redis_usable():
        try:
            client = _client()
            total = int(client.incrby(key, amount))
            client.expireat(key, int(expires.timestamp()))
            return total
        except Exception as exc:
            _redis_failed()
            _log.warning("cooldown store unavailable (%s): using process memory", type(exc).__name__)
    with _lock:
        for stale in [k for k, (_, exp) in _local_daily.items() if exp <= now.timestamp()]:
            del _local_daily[stale]
        total = _local_daily.get(key, (0, 0.0))[0] + amount
        _local_daily[key] = (total, expires.timestamp())
        return total


def reserve_daily(channel: str, amount: int, cap: int, now: datetime | None = None) -> bool:
    """
    Reserve amount messages of today's cap before a send, atomically. False when that would pass the cap.

    The increment is one Redis INCRBY (or one locked step in memory) and a reservation that would pass the cap is taken
    straight back, so sends that are in flight at the same moment cannot each see room and together pass it. A send
    that then fails gives its reservation back with give_back_daily.
    """
    total = count_daily(channel, amount, now)
    if total > cap:
        give_back_daily(channel, amount, now)
        return False
    return True


def give_back_daily(channel: str, amount: int, now: datetime | None = None) -> None:
    """Return a reservation, for a send that failed or was dropped."""
    now = now or datetime.now(timezone.utc)
    key = _daily_key(channel, now)
    if _redis_usable():
        try:
            _client().decrby(key, amount)
            return
        except Exception as exc:
            _redis_failed()
            _log.warning("cooldown store unavailable (%s): using process memory", type(exc).__name__)
    with _lock:
        count, expires = _local_daily.get(key, (0, 0.0))
        _local_daily[key] = (max(0, count - amount), expires)
