"""
Notify pool - the threads that make the vendor calls, apart from the ones that answer requests.

A send (email, text, Discord, a webhook) can wait for its whole timeout. When those waits ran on the request threads, about
forty machines alerting at once against an endpoint that hangs held every thread for seconds and stalled the API,
ingest and the status check included. Sends now go to this small pool. The request thread only hands a job over, which
takes microseconds, so ingest and GET /status never wait on a notification.

Sizes and why. 8 worker threads: a healthy send takes a fraction of a second, so 8 workers clear dozens of alerts a
second and 8 hung endpoints (5 second timeout each) still leave none of the request threads busy. A queue of 200 jobs:
forty machines alerting at once make about 160 sends (up to four channels each), so 200 holds a full burst with
room to spare and a longer outage fills it instead of growing without bound.

When the queue is full the oldest job that is not critical is dropped, counted and logged. A critical job is never
dropped: it is also taken before any other job, so a critical text does not wait behind a hung webhook that was queued
first. A dropped job runs its undo, which gives back a daily-cap reservation. Its repeat window is left to run out.
"""

import logging
import threading
from collections import deque

logger = logging.getLogger(__name__)

WORKERS = 8
QUEUE_LIMIT = 200

_lock = threading.Condition()
_critical: deque = deque()
_normal: deque = deque()
_threads: list[threading.Thread] = []
# jobs dropped because the queue was full, for the log and for a test
dropped_total = 0
_last_logged = float("-inf")
# a test sets this so a submitted job runs at once in the caller's thread
run_inline = False


def _queued() -> int:
    return len(_critical) + len(_normal)


def _log_drop() -> None:
    global _last_logged
    import time

    now = time.monotonic()
    # one line a minute, so a long outage does not fill the log
    if now - _last_logged >= 60:
        _last_logged = now
        logger.warning("the notification queue is full: %d notifications dropped so far", dropped_total)


def _worker() -> None:
    while True:
        with _lock:
            while not _critical and not _normal:
                _lock.wait()
            job = (_critical or _normal).popleft()
        try:
            job[0]()
        except Exception as exc:  # noqa: BLE001
            logger.warning("a notification job failed (%s)", type(exc).__name__)


def _ensure_workers() -> None:
    while len(_threads) < WORKERS:
        thread = threading.Thread(target=_worker, name=f"notify-{len(_threads)}", daemon=True)
        _threads.append(thread)
        thread.start()


def submit(job, critical: bool = False, undo=None) -> bool:
    """
    Hand a job to the pool. Returns False when it was dropped.

    `undo` runs when the job is dropped. A critical job is always accepted.
    """
    global dropped_total
    if run_inline:
        job()
        return True
    dropped = []
    with _lock:
        _ensure_workers()
        if _queued() >= QUEUE_LIMIT:
            if _normal:
                dropped.append(_normal.popleft())
            elif not critical:
                # the queue is all critical jobs and this one is not, so it is the one that is refused
                dropped.append((job, undo))
                job = None
        if job is not None:
            (_critical if critical else _normal).append((job, undo))
            _lock.notify()
        dropped_total += len(dropped)
    for _, drop_undo in dropped:
        if drop_undo is not None:
            try:
                drop_undo()
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not undo a dropped notification (%s)", type(exc).__name__)
    if dropped:
        _log_drop()
    return job is not None


def reset() -> None:
    """Empty the queue and the count. For tests."""
    global dropped_total, _last_logged
    with _lock:
        _last_logged = float("-inf")
        _critical.clear()
        _normal.clear()
        dropped_total = 0
