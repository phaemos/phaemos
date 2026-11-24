"""
Training data for the anomaly model: which readings may teach it and how many of them are read.

A model learns what normal looks like, so a reading may only teach it when the machine was plausibly normal and the
reading is trustworthy. A reading is refused when it was taken in a maintenance window (the machine was being worked
on) or carries a sensor fault, a rejected value or a dropped value (the reading itself is suspect) or sits beside a gap
in the posts longer than the liveness sweep's "late" limit (the node's link was failing). A reading taken while a
machine alert was open is refused only when a person stands behind that alert: a threshold rule (a limit a person set)
or a model alert a person has confirmed as a real fault (alerts.fault_confirmed). The model's own unconfirmed alert does
not refuse anything: if it did, a machine whose normal had really changed (a warmer room, a new product) would keep its
alert open, never be retrained on the new normal and never clear. How far a retrain may move a machine's normal is
bounded instead (services/ml_service.py).

Rows are chosen in SQL, never loaded and filtered in Python:

- the window is the last WINDOW_DAYS days of one machine;
- the clean rows of a machine are split by time into three parts. The oldest FIT_FRACTION fits the model, thinned to at
  most MAX_FIT_ROWS rows by taking the first row of each time bucket so the fit split covers its span evenly. The next
  VALIDATION_FRACTION sets every boundary and every threshold. The newest TEST_FRACTION is touched by nothing that is
  tuned: it only gives the false alert figure that is reported and the champion and challenger comparison. Both held-out
  parts are kept at the posting rate (never more than MAX_HELDOUT_ROWS each), because the alert decision needs real runs
  of consecutive readings to be replayed through;
- the posting interval is the one the machine really shows (the median gap between its readings in the window) when it
  differs from the device record by more than INTERVAL_TOLERANCE, so a node that posts six times slower than its record
  is neither refused as a failing link nor measured on the wrong clock;
- one machine is read at a time in its own short transaction with a statement timeout, so training never holds a
  transaction open across the whole fleet.

Memory bound: one machine at a time holds at most (MAX_FIT_ROWS + 2 x MAX_HELDOUT_ROWS) rows of len(SENSOR_COLS) float64
values, which is 80,000 x 23 x 8 bytes = 14.7 MB. The pooled node type and general sets are capped by POOL_FIT_ROWS and
POOL_HELDOUT_ROWS, which is another 180,000 x 23 x 8 bytes = 33 MB per pool, so a fleet of any size trains in well under
250 MB on top of the application.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import text

from app.models.device import Device
from app.db import SessionLocal
from app.services.model_evaluation import MIN_HELDOUT_ROWS

logger = logging.getLogger(__name__)

# every numeric sensor column a node can send. A model uses the ones its machine really reports, since a field a
# node never has would otherwise read as a constant 0 and skew its normal envelope.
SENSOR_COLS = [
    "temperature", "humidity", "pressure", "vibration_x", "vibration_y", "vibration_z",
    "gyro_x", "gyro_y", "gyro_z", "bus_voltage", "current_ma", "power_mw", "ir_temperature",
    "distance_mm", "gas_level", "shaft_angle", "shaft_rpm", "sound_level", "light_level",
    "contact_temp", "moisture_level", "fft_peak_hz", "vib_magnitude",
]

# the model's columns: every sensor column and, last, the site's ambient reference. ambient_ref is not a telemetry column: it
# is the air temperature another node in the same place reported (the device's ambient_source_id), the latest one at most
# AMBIENT_MAX_AGE_S old at the reading's time, joined in here for training and by the scorer live
AMBIENT_REF = "ambient_ref"
MODEL_COLS = SENSOR_COLS + [AMBIENT_REF]
AMBIENT_MAX_AGE_S = 300.0

# how far back training reads. Two weeks holds two full weekly cycles of a plant and is recent enough that a
# machine's slow drift since last month is not taught as normal
WINDOW_DAYS = 14
# the shares of a machine's clean span, oldest first: fit, validation (every threshold is set on it) and test (only
# reported). A fifth each for validation and test gives each about 2.8 days of a fortnight
VALIDATION_FRACTION = 0.2
TEST_FRACTION = 0.2
HELDOUT_FRACTION = VALIDATION_FRACTION + TEST_FRACTION
FIT_FRACTION = 1.0 - HELDOUT_FRACTION
# at most this many clean rows of one machine are fitted, taken evenly in time. 20,000 rows is 28 hours at one a
# minute, enough for a forest of 256-row trees, which bounds the memory and the fit time
MAX_FIT_ROWS = 20_000
# at most this many of the newest clean rows of each held-out part (validation and test) of one machine, at the full
# posting rate. 30,000 rows is 42 hours at 5 s. It bounds the replay time and the memory
MAX_HELDOUT_ROWS = 30_000
# a node type model and the general model each pool the machines' fit rows up to POOL_FIT_ROWS, shared equally between
# the machines so that one machine cannot dominate. The held-out parts come from at most POOL_HELD_MACHINES machines,
# chosen evenly through the fleet, each with an equal share of POOL_HELDOUT_ROWS consecutive readings. Taking every
# machine's share would leave each one too few consecutive readings to inject a fault into once a node type has a few
# hundred machines
POOL_FIT_ROWS = 60_000
POOL_HELDOUT_ROWS = 60_000
POOL_HELD_MACHINES = 12
# the shortest test part whose false alert figure is reported at all. A day covers a daily cycle once. With no false alert
# in a day the 95 per cent upper bound is still 21 a week, which is why the figure is always given with its bound
MIN_TEST_HOURS = 24.0
# the device record's interval is replaced by the observed one when they differ by more than this factor
INTERVAL_TOLERANCE = 1.5
# a machine or node type needs this many hours of clean readings, over a span of at least as many hours, to be
# modelled. A day covers a whole daily cycle once
MIN_CLEAN_HOURS = 24.0
MIN_SPAN_HOURS = 24.0
# a machine also needs enough clean readings that its validation part is at least MIN_HELDOUT_ROWS (see
# services/model_evaluation.py) and enough hours that its test part is at least MIN_TEST_HOURS. A 5 s node needs five
# days for the second and a node that posts once a minute about a week for the first
MIN_CLEAN_ROWS = int(MIN_HELDOUT_ROWS / VALIDATION_FRACTION)
# a gap between two posts longer than this many intervals means the link was late. It is the liveness sweep's own
# "late" limit (services/liveness_service.py)
LATE_GAP_INTERVALS = 4
# one statement may run this long. It stops a slow query from holding a transaction open
STATEMENT_TIMEOUT_MS = 60_000

# the reasons a row is refused, in the order they are tried. The text is what an operator reads
REFUSAL_REASONS = {
    "maintenance": "taken during a maintenance window",
    "sensor_fault": "carried a sensor fault, a rejected value or a dropped value",
    "machine_alert": "taken while a rule alert or a model alert a person confirmed as a fault was open",
    "link": "taken next to a gap in the posts longer than the late limit",
}


@dataclass
class MachineData:
    """
    One machine's clean readings, already split by time. Columns follow MODEL_COLS and missing values are NaN.

    fit is the thinned fit split. val and test are the validation and test parts at the posting rate. held and
    held_times are the two held-out parts together (validation then test), for code that wants every held-out reading.
    """

    device_id: str
    name: str
    node_type: str | None
    interval_s: float
    fit: np.ndarray
    val: np.ndarray
    val_times: np.ndarray
    test: np.ndarray = field(default_factory=lambda: np.empty((0, len(MODEL_COLS))))
    test_times: np.ndarray = field(default_factory=lambda: np.empty(0))
    # all clean rows in the window, counted in SQL, before the sampling
    clean_rows: int = 0
    clean_hours: float = 0.0
    span_hours: float = 0.0
    refused: dict = field(default_factory=dict)
    total_rows: int = 0
    # the epoch time of each fit row, for the change detector's smoothed view of the other sensors
    fit_times: np.ndarray = field(default_factory=lambda: np.empty(0))
    # the interval of the device record, when the observed one replaced it (None when they agree)
    recorded_interval_s: float | None = None

    @property
    def held(self) -> np.ndarray:
        if not len(self.test):
            return self.val
        return np.vstack([self.val, self.test]) if len(self.val) else self.test

    @property
    def held_times(self) -> np.ndarray:
        return np.concatenate([self.val_times, self.test_times])

    @property
    def test_hours(self) -> float:
        return _part_hours(self.test_times, self.interval_s)

    @property
    def enough(self) -> bool:
        return (
            self.clean_hours >= MIN_CLEAN_HOURS and self.span_hours >= MIN_SPAN_HOURS
            and self.clean_rows >= MIN_CLEAN_ROWS and self.test_hours >= MIN_TEST_HOURS
        )

    @property
    def hours_needed(self) -> float:
        return hours_needed(self.interval_s)


def _part_hours(times: np.ndarray, interval_s: float) -> float:
    """Hours a held-out part covers: its readings at their interval, never more than its span."""
    if len(times) < 2:
        return 0.0
    return min(len(times) * float(interval_s), float(times[-1] - times[0]) + float(interval_s)) / 3600.0


def hours_needed(interval_s: float) -> float:
    """
    Hours of clean readings a machine needs: enough for MIN_CLEAN_ROWS readings and for a test part of MIN_TEST_HOURS.

    The test part is the newest TEST_FRACTION, so the second is MIN_TEST_HOURS / TEST_FRACTION: five days.
    """
    return max(MIN_CLEAN_HOURS, MIN_CLEAN_ROWS * float(interval_s) / 3600.0, MIN_TEST_HOURS / TEST_FRACTION)


def observed_interval(times: np.ndarray, recorded_s: float) -> float:
    """
    The posting interval a machine really shows: the median gap between consecutive readings.

    The record's interval stands when the two agree within INTERVAL_TOLERANCE or when there are too few readings to say.
    """
    recorded_s = float(max(1.0, recorded_s or 5.0))
    if len(times) < 50:
        return recorded_s
    gaps = np.diff(np.asarray(times, dtype=float))
    gaps = gaps[gaps > 0]
    if len(gaps) < 50:
        return recorded_s
    seen = float(np.median(gaps))
    if recorded_s / INTERVAL_TOLERANCE <= seen <= recorded_s * INTERVAL_TOLERANCE:
        return recorded_s
    return float(min(max(round(seen, 1), 1.0), 86_400.0))


def thin_evenly(array: np.ndarray, cap: int) -> np.ndarray:
    """At most cap rows of array, spaced evenly through it and keeping its order."""
    if cap <= 0:
        return array[:0]
    if len(array) <= cap:
        return array
    index = np.linspace(0, len(array) - 1, cap).round().astype(int)
    return array[index]


def thin_latest(array: np.ndarray, cap: int) -> np.ndarray:
    """The newest cap rows of array. It is for held-out rows, which must stay consecutive."""
    return array[-cap:] if cap > 0 else array[:0]


def clean_hours(clean_rows: int, interval_s: float, span_s: float) -> float:
    """Hours of clean readings: the rows at their posting interval, never more than the span they sit in."""
    return min(clean_rows * interval_s, span_s) / 3600.0


def fit_bucket_s(span_s: float, interval_s: float, cap: int) -> float:
    """The width of the time bucket that leaves at most cap fit rows over span_s. Never under one interval."""
    return max(float(interval_s), float(np.ceil(span_s / max(cap, 1))), 1.0)


def split_points(first: float, last: float) -> tuple[float, float]:
    """The epoch times where validation and test begin, for a clean span from first to last."""
    span = last - first
    return first + FIT_FRACTION * span, first + (FIT_FRACTION + VALIDATION_FRACTION) * span


def join_reference(times: np.ndarray, ref_times: np.ndarray | None, ref_values: np.ndarray | None) -> np.ndarray:
    """The site reference at each time: the latest reference reading at or before it, at most AMBIENT_MAX_AGE_S old."""
    out = np.full(len(times), np.nan)
    if ref_times is None or not len(ref_times) or not len(times):
        return out
    order = np.argsort(ref_times)
    ref_times, ref_values = np.asarray(ref_times, dtype=float)[order], np.asarray(ref_values, dtype=float)[order]
    at = np.searchsorted(ref_times, times, side="right") - 1
    ok = at >= 0
    age = np.where(ok, times - ref_times[np.clip(at, 0, None)], np.inf)
    good = ok & (age <= AMBIENT_MAX_AGE_S)
    out[good] = ref_values[at[good]]
    return out


def _with_reference(times: np.ndarray, X: np.ndarray, ref_times=None, ref_values=None) -> np.ndarray:
    """X widened to MODEL_COLS: the sensor columns as they are and the site reference joined in (NaN without one)."""
    if X.shape[1] == len(MODEL_COLS):
        return X
    return np.column_stack([X, join_reference(times, ref_times, ref_values)])


def select_from_arrays(
    times: np.ndarray, X: np.ndarray, reasons: np.ndarray, interval_s: float,
    device_id: str = "", name: str = "", node_type: str | None = None, ref_times=None, ref_values=None,
) -> MachineData:
    """
    The same selection as load_machine does in SQL, for readings already in memory (the evaluation's simulation).

    times are epoch seconds in order, X is (n, len(SENSOR_COLS)) or (n, len(MODEL_COLS)) and reasons holds a key of
    REFUSAL_REASONS or "" for each row. interval_s is the device record's interval: the observed one replaces it as
    load_machine does. ref_times and ref_values are the site reference's readings, when the machine has one.
    """
    X = _with_reference(times, X, ref_times, ref_values)
    recorded = float(interval_s)
    interval_s = observed_interval(times, recorded)
    clean = reasons == ""
    refused = {key: int((reasons == key).sum()) for key in REFUSAL_REASONS if (reasons == key).any()}
    ct, cx = times[clean], X[clean]
    n = len(ct)
    empty = np.empty((0, X.shape[1]))
    if n == 0:
        return MachineData(device_id, name, node_type, interval_s, empty, empty, np.empty(0), refused=refused,
                           total_rows=len(times), recorded_interval_s=None if interval_s == recorded else recorded)
    span = float(ct[-1] - ct[0])
    val_at, test_at = split_points(float(ct[0]), float(ct[-1]))
    v0 = int(np.searchsorted(ct, val_at, side="left"))
    t0 = int(np.searchsorted(ct, test_at, side="left"))
    t0 = max(t0, n - MAX_HELDOUT_ROWS)
    v0 = max(v0, t0 - MAX_HELDOUT_ROWS)
    test, test_times = cx[t0:], ct[t0:]
    val, val_times = cx[v0:t0], ct[v0:t0]
    fit_t, fit_x = ct[:v0], cx[:v0]
    if len(fit_t):
        end = float(val_times[0]) if len(val_times) else float(ct[-1])
        bucket = fit_bucket_s(end - float(ct[0]), interval_s, MAX_FIT_ROWS)
        keys = np.floor(fit_t / bucket)
        first = np.concatenate(([True], keys[1:] != keys[:-1]))
        fit_x = fit_x[first]
        fit_t = fit_t[first]
    return MachineData(
        device_id, name, node_type, interval_s, fit_x, val, val_times, test, test_times,
        clean_rows=n, clean_hours=clean_hours(n, interval_s, span), span_hours=span / 3600.0,
        refused=refused, total_rows=len(times), fit_times=fit_t if len(fit_t) else np.empty(0),
        recorded_interval_s=None if interval_s == recorded else recorded,
    )


# one statement labels each row of one machine with the reason it is refused (null when it is clean). The columns
# come from SENSOR_COLS, which is a constant list and never user input
_LABELLED = """
WITH base AS (
    SELECT t.recorded_at AS ts, t.quality, {cols},
           t.recorded_at - LAG(t.recorded_at) OVER w AS gap_prev,
           LEAD(t.recorded_at) OVER w - t.recorded_at AS gap_next
    FROM telemetry t
    WHERE t.device_id = :dev AND t.recorded_at >= :since AND t.recorded_at < :until
    WINDOW w AS (ORDER BY t.recorded_at)
), labelled AS (
    SELECT b.*, CASE
        WHEN EXISTS (
            SELECT 1 FROM maintenance_windows m
            WHERE (m.device_id = :dev OR m.device_id IS NULL) AND b.ts BETWEEN m.start_at AND m.end_at
        ) THEN 'maintenance'
        WHEN b.quality ?| ARRAY['faults', 'rejected', 'dropped_health', 'dropped_values'] THEN 'sensor_fault'
        WHEN EXISTS (
            SELECT 1 FROM alerts a
            WHERE a.device_id = :dev AND a.category = 'machine' AND a.triggered_at <= b.ts
              AND (a.resolved IS NOT TRUE OR a.resolved_at IS NULL OR a.resolved_at >= b.ts)
              AND (a.kind IS DISTINCT FROM 'anomaly' OR a.fault_confirmed IS TRUE)
        ) THEN 'machine_alert'
        WHEN b.gap_prev > make_interval(secs => :late) OR b.gap_next > make_interval(secs => :late) THEN 'link'
    END AS reason
    FROM base b
)
"""


def _labelled() -> str:
    return _LABELLED.format(cols=", ".join(f"t.{c}" for c in SENSOR_COLS))


_REFERENCE = """
SELECT t.recorded_at, t.temperature FROM telemetry t
WHERE t.device_id = :src AND t.recorded_at >= :since AND t.recorded_at < :until AND t.temperature IS NOT NULL
ORDER BY t.recorded_at
"""


def _rows_to_array(result) -> tuple[np.ndarray, np.ndarray]:
    times, values = [], []
    while True:
        chunk = result.fetchmany(5000)
        if not chunk:
            break
        for row in chunk:
            times.append(row[0].timestamp())
            values.append(row[1:])
    if not times:
        return np.empty(0), np.empty((0, len(SENSOR_COLS)))
    return np.array(times), np.array(values, dtype=float)


_GAPS = """
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY gap), count(*) FROM (
    SELECT extract(epoch FROM t.recorded_at - LAG(t.recorded_at) OVER (ORDER BY t.recorded_at)) AS gap
    FROM telemetry t
    WHERE t.device_id = :dev AND t.recorded_at >= :since AND t.recorded_at < :until
) g WHERE gap > 0
"""


def _interval_from_gaps(median_gap, count, recorded_s: float) -> float:
    """The observed interval from the median gap SQL measured, with the same rule as observed_interval."""
    recorded_s = float(max(1.0, recorded_s or 5.0))
    if median_gap is None or (count or 0) < 50:
        return recorded_s
    seen = float(median_gap)
    if recorded_s / INTERVAL_TOLERANCE <= seen <= recorded_s * INTERVAL_TOLERANCE:
        return recorded_s
    return float(min(max(round(seen, 1), 1.0), 86_400.0))


def load_machine(device: Device, now: datetime | None = None, session_factory=None) -> MachineData:
    """
    Read one machine's clean training rows. See the module note for what clean means and for the bounds.

    The session is its own and short: it is opened here, runs at most five statements of at most
    STATEMENT_TIMEOUT_MS each and is closed before this returns.
    """
    now = now or datetime.now(timezone.utc)
    recorded = float(max(1, device.expected_interval_s or 5))
    window = {"dev": device.id, "since": now - timedelta(days=WINDOW_DAYS), "until": now}
    select_cols = ", ".join(SENSOR_COLS)
    db = (session_factory or SessionLocal)()
    try:
        db.execute(text(f"SET LOCAL statement_timeout = {int(STATEMENT_TIMEOUT_MS)}"))
        gap = db.execute(text(_GAPS), window).first()
        interval = _interval_from_gaps(gap[0] if gap else None, gap[1] if gap else 0, recorded)
        base = {**window, "late": LATE_GAP_INTERVALS * interval}
        stats = db.execute(
            text(_labelled() + "SELECT reason, count(*), min(ts), max(ts) FROM labelled GROUP BY reason"), base
        ).fetchall()
        refused = {r[0]: int(r[1]) for r in stats if r[0] is not None}
        total = sum(int(r[1]) for r in stats)
        clean = [r for r in stats if r[0] is None]
        empty = np.empty((0, len(MODEL_COLS)))
        moved = None if interval == recorded else recorded
        ref_times = ref_values = None
        source = getattr(device, "ambient_source_id", None)
        if source is not None and str(source) != str(device.id):
            ref = db.execute(text(_REFERENCE), {**window, "src": source}).fetchall()
            ref_times = np.array([r[0].timestamp() for r in ref]) if ref else None
            ref_values = np.array([float(r[1]) for r in ref]) if ref else None
        if not clean or not clean[0][1]:
            return MachineData(str(device.id), device.name, device.type, interval, empty, empty, np.empty(0),
                               refused=refused, total_rows=total, recorded_interval_s=moved)
        n, first, last = int(clean[0][1]), clean[0][2], clean[0][3]
        span = (last - first).total_seconds()
        val_at, test_at = (datetime.fromtimestamp(x, tz=timezone.utc)
                           for x in split_points(first.timestamp(), last.timestamp()))

        def part(lo, hi):
            # newest first so the cap keeps the newest rows, then put back in time order
            result = db.execute(
                text(_labelled() + f"SELECT ts, {select_cols} FROM labelled WHERE reason IS NULL AND ts >= :lo"
                     + (" AND ts < :hi" if hi is not None else "") + " ORDER BY ts DESC LIMIT :cap"),
                {**base, "lo": lo, "hi": hi, "cap": MAX_HELDOUT_ROWS},
            )
            times, rows = _rows_to_array(result)
            times, rows = times[::-1], rows[::-1]
            return times, _with_reference(times, rows, ref_times, ref_values)

        test_times, test = part(test_at, None)
        val_hi = datetime.fromtimestamp(float(test_times[0]), tz=timezone.utc) if len(test_times) else None
        val_times, val = part(val_at, val_hi)
        fit = empty
        fit_times = np.empty(0)
        fit_end_ts = val_times[0] if len(val_times) else (test_times[0] if len(test_times) else None)
        if fit_end_ts is not None:
            fit_end = datetime.fromtimestamp(float(fit_end_ts), tz=timezone.utc)
            bucket = fit_bucket_s((fit_end - first).total_seconds(), interval, MAX_FIT_ROWS)
            fit_result = db.execute(
                text(_labelled() + f"SELECT ts, {select_cols} FROM ("
                     "SELECT DISTINCT ON (floor(extract(epoch FROM ts) / :bucket)) * FROM labelled "
                     "WHERE reason IS NULL AND ts < :fit_end "
                     "ORDER BY floor(extract(epoch FROM ts) / :bucket), ts) sampled ORDER BY ts"),
                {**base, "bucket": bucket, "fit_end": fit_end},
            )
            fit_times, fit = _rows_to_array(fit_result)
            fit = _with_reference(fit_times, fit, ref_times, ref_values)
        return MachineData(
            str(device.id), device.name, device.type, interval, fit, val, val_times, test, test_times,
            clean_rows=n, clean_hours=clean_hours(n, interval, span), span_hours=span / 3600.0,
            refused=refused, total_rows=total, fit_times=fit_times, recorded_interval_s=moved,
        )
    finally:
        db.rollback()
        db.close()
