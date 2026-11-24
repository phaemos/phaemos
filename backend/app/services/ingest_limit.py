"""
Ingest limit - how fast one device may post readings.

A healthy node posts at its reporting interval, which the firmware clamps to 2 seconds at the fastest. That is 30 posts
a minute and a retry after the node's own 2 second timeout or a short catch-up from the edge gateway adds a few more.
The limit is 60 a minute for each device, twice the fastest healthy rate, so no healthy node meets it. It stops a
device key in a tight loop (a stolen key or a firmware fault) from writing a reading every few milliseconds and
filling the disk: the most it can write is one a second.

A refused post answers 429 with a Retry-After header in seconds, which the firmware can treat as "slow down". The
count is a sliding window in this process, which is right for the one uvicorn process the Dockerfile starts. It is
keyed on the device id and never holds the API key.
"""

import math
import threading
import time
from collections import defaultdict, deque

from app.errors import ApiError, Code, rate_limit_headers

# posts a device may make in one window
MAX_POSTS = 60
WINDOW_SECONDS = 60

_lock = threading.Lock()
_recent: dict[str, deque] = defaultdict(deque)


def check(device_id) -> None:
    """Count a post for the device or raise 429 with Retry-After when it has made too many in the window."""
    key = str(device_id)
    now = time.monotonic()
    with _lock:
        recent = _recent[key]
        while recent and now - recent[0] >= WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= MAX_POSTS:
            wait = max(1, math.ceil(WINDOW_SECONDS - (now - recent[0])))
            raise ApiError(
                429, Code.DEVICE_RATE_LIMITED, f"Too many readings from this device. Wait {wait} seconds.",
                headers=rate_limit_headers(MAX_POSTS, wait),
            )
        recent.append(now)
        if len(_recent) > 5000:
            # forget devices that have been quiet for a whole window, so the table cannot grow with every device ever seen
            for stale in [k for k, q in _recent.items() if not q or now - q[-1] >= WINDOW_SECONDS]:
                del _recent[stale]


# the batch route is counted in readings and not in requests, with its own window apart from the single route's;
# one hub's four nodes at 5 seconds post 48 readings a minute. An outage of an hour leaves 2,880 to send and a day 69,120. At 1,200
# readings a minute for one device (twelve full batches) an hour clears in 2.4 minutes and a day in 58, while the single route
# carries the live readings beside it. The site as a whole may take 6,000 readings a minute, which is about 4 ms of database time per
# reading at the very most (0.4 s of each second), so a whole site draining at once is slowed to a fifth each and no more: fifty hubs
# take 120 readings a minute each and an hour's backlog then clears in 24 minutes
BATCH_ITEMS_PER_DEVICE = 1200
BATCH_ITEMS_ALL = 6000
_batch_devices: dict[str, deque] = defaultdict(deque)
_batch_all: deque = deque()


def _count(window: deque) -> int:
    return sum(n for _, n in window)


def _expire(window: deque, now: float) -> None:
    while window and now - window[0][0] >= WINDOW_SECONDS:
        window.popleft()


def check_batch(device_id, items: int) -> None:
    """Count items readings for the device and the site or raise 429 with Retry-After when either allowance would pass its limit."""
    key = str(device_id)
    now = time.monotonic()
    with _lock:
        mine = _batch_devices[key]
        _expire(mine, now)
        _expire(_batch_all, now)
        for window, limit, what in ((mine, BATCH_ITEMS_PER_DEVICE, "this device"), (_batch_all, BATCH_ITEMS_ALL, "this site")):
            if _count(window) + items > limit:
                # the wait is until enough of the window has left for these readings to fit
                freed, wait = 0, WINDOW_SECONDS
                for stamp, n in window:
                    freed += n
                    if _count(window) - freed + items <= limit:
                        wait = max(1, math.ceil(WINDOW_SECONDS - (now - stamp)))
                        break
                raise ApiError(
                    429, Code.DEVICE_RATE_LIMITED, f"Too many batched readings from {what}. Wait {wait} seconds.",
                    headers=rate_limit_headers(limit, wait),
                )
        mine.append((now, items))
        _batch_all.append((now, items))
        if len(_batch_devices) > 5000:
            for stale in [k for k, q in _batch_devices.items() if not q or now - q[-1][0] >= WINDOW_SECONDS]:
                del _batch_devices[stale]


_named: dict[tuple[str, str], deque] = defaultdict(deque)


def check_named(device_id, name: str, maximum: int, window: float = WINDOW_SECONDS) -> None:
    """
    A per-device allowance for the other device-key routes (the firmware check and download), counted per machine and never per
    address: fifty hubs behind one address after a power cut each have their own. 429 with Retry-After and the X-RateLimit headers.
    """
    key = (str(device_id), name)
    now = time.monotonic()
    with _lock:
        recent = _named[key]
        while recent and now - recent[0] >= window:
            recent.popleft()
        if len(recent) >= maximum:
            wait = max(1, math.ceil(window - (now - recent[0])))
            raise ApiError(
                429, Code.DEVICE_RATE_LIMITED, f"Too many {name} requests from this device. Wait {wait} seconds.",
                headers=rate_limit_headers(maximum, wait),
            )
        recent.append(now)
        if len(_named) > 5000:
            for stale in [k for k, q in _named.items() if not q or now - q[-1] >= window]:
                del _named[stale]


def reset() -> None:
    """Forget every count. For tests."""
    with _lock:
        _named.clear()
        _recent.clear()
        _batch_devices.clear()
        _batch_all.clear()
