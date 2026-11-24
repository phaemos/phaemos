"""
A tighter limit for the reads that hold a database connection for a long time: the CSV export and
the bucketed history. The general limit allows 600 requests a minute and the connection pool holds
15 connections, so a handful of people could otherwise hold every connection and make the rest of
the API wait for 30 seconds and fail.

    with heavy_read(user.id, "export"):
        ... the database work ...

Each person gets a rate (per minute) and a number of reads running at once per kind and the whole
process gets a ceiling on how many run at once. A refused read answers 429 straight away, without
waiting for a slot.
"""

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

from app.errors import ApiError, Code, rate_limit_headers

# per person, per minute
RATES = {"export": 6, "bucket": 60}
# at once, per person and in total
MAX_AT_ONCE_PER_USER = 2
MAX_AT_ONCE_TOTAL = 6

_lock = threading.Lock()
_recent: dict[tuple[str, str], deque] = defaultdict(deque)
_running_by_user: dict[str, int] = defaultdict(int)
_running_total = 0


def _refuse(detail: str, limit: int) -> ApiError:
    return ApiError(429, Code.READ_BUSY, detail, headers=rate_limit_headers(limit, 10))


@contextmanager
def heavy_read(user_id, kind: str):
    global _running_total
    who = str(user_id)
    now = time.monotonic()
    with _lock:
        recent = _recent[(who, kind)]
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= RATES[kind]:
            raise _refuse(f"Too many {kind} requests. Wait a minute and try again.", RATES[kind])
        if _running_by_user.get(who, 0) >= MAX_AT_ONCE_PER_USER or _running_total >= MAX_AT_ONCE_TOTAL:
            raise _refuse("Too many large reads are running. Try again in a few seconds.", MAX_AT_ONCE_PER_USER)
        recent.append(now)
        _running_by_user[who] += 1
        _running_total += 1
    try:
        yield
    finally:
        with _lock:
            _running_by_user[who] -= 1
            if _running_by_user[who] <= 0:
                _running_by_user.pop(who, None)
            _running_total -= 1


def reset() -> None:
    """Forget everything. For tests."""
    global _running_total
    with _lock:
        _recent.clear()
        _running_by_user.clear()
        _running_total = 0
