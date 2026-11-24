"""
A sequential change detector beside the forest and the per-sensor baseline.

A step or a slow drift in one sensor is the textbook case for accumulating small deviations from an expected value over
time and not for judging one reading against a range. A range for one temperature sensor is wide because temperature
lags the machine's state. A forest cannot say how far past its range a value has gone.

Expected value. For each sensor the model predicts its value from the machine's OTHER sensors (their current values and
two exponentially smoothed views of them, over SMOOTH_TAUS) and a daily profile (the day and its first harmonic). The
smoothed terms carry the thermal lag, so a room that warms twenty minutes after the machine starts is expected to. The
weights are a ridge regression on the clean fit rows. The sensor's own history is never an input, so a drift in a sensor
cannot be absorbed into its own expectation.

Spread. The residual (observed minus expected) is not equally noisy all the time: it is small while the machine holds a
state and large for a few minutes after it changes one, because no lag model is exact. So its spread is modelled as
sd(g) = sqrt(quiet^2 + (slope * g)^2), where g measures how far the other sensors sit from their five minute average (how
fast the machine is changing state). quiet is read from the steady periods and slope from the transitions, both on the
fit rows. The allowance is a multiple of that quiet spread, so a small steady offset is seen while the machine is steady
and a start-up transient is not taken for one.

Detection. The standardised residual feeds a two-sided CUSUM that ignores deviations under ALLOWANCE. The accumulators are
in standard deviations times minutes: each reading adds its excess times the minutes since the previous one (at most
MAX_STEP_S). So the rate of accumulation does not depend on how often a node posts, a batch whose readings carry the same
time adds nothing and a reading seen twice (a retried transaction) adds nothing the second time. The raw score of a
reading is the largest accumulator. ml_service measures the boundary on held-out healthy readings and maps the raw score
onto the public 0 to 1 scale with 0.7 at that boundary.

Slow adaptation within a bound. The residual's level wanders for reasons that are not a fault: the weather, a warmer room
this week, a season, a new product. That level is followed by a time-weighted exponential average over LEVEL_TAU_S and
taken off before the CUSUM, so what is accumulated is how far the residual has moved in the last hours. A step or a
drift that develops within hours stands out against it and is caught. Day-to-day weather moves the level by a few hundredths
of a degree an hour and is not. The level is clipped to plus or minus level_bound, LEVEL_BOUND times the hour-to-hour
wander of the residual measured on the validation readings (which the fit never saw), so a change larger than the machine
was seen to wander is never learned away live: past the bound it accumulates like any fault. The costs are plain. A
change slow enough to look like weather (a fraction of a degree a day) is not seen by the detector until the level
reaches its bound and a step is seen for a few hours and then taken as the new level. ml_service starts a machine's
level where the newest held-out readings left it, so the first hours in service are not measured against an old level.

Gaps and restarts. A gap shorter than RESET_GAP_S (or GAP_INTERVALS observed intervals when that is longer) carries the
state over: the smoothed views step across it. A longer gap re-seeds the smoothed views from the new reading and for
WARMUP_S seconds after that nothing accumulates. The accumulators are held, not zeroed, across such a gap and its warm-up:
a silence is no evidence that a fault has gone, so an alert that was open stays open through an outage instead of
reading the warm-up as calm. A reading at or before the last one (a retry, a batch stamped at one instant, a reading out
of order) does not step the state at all. The level is kept across a gap: it is slow by design. The accumulators are
capped at CAP_BOUNDARIES times the measured boundary, so a long fault that has ended clears within about half an hour
of healthy readings.

State is per machine and lives between readings. It is a small object (DetectorState) behind a StateStore with get and
put, which the evaluation backs with memory and the server backs with the database.

The module is pure: arrays and times in and out, no database and no clock.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# the smoothed views of the other sensors: a quick one that follows a change of state within minutes and a slow one that
# carries a thermal lag of half an hour. A regression on the two can match any lag between them
SMOOTH_TAUS = (300.0, 1800.0)
# the accumulators are kept in standard deviations times this many seconds (a minute)
REF_S = 60.0
# a gap longer than this many observed intervals and longer than RESET_GAP_S resets the detector. Five minutes is the quick
# view's own time constant: a shorter silence (a radio outage, a few lost posts) leaves the views close to right
GAP_INTERVALS = 3
RESET_GAP_S = 300.0
# seconds after a reset during which nothing accumulates, while the smoothed views settle. One slow view's time constant:
# a shorter warm-up left the thermal-lag view seeded wrong and fresh runs crossed the boundary on healthy readings (on the
# validation seeds 8 per cent of fresh one-hour runs did at 600 s and none at 1,200 s or more)
WARMUP_S = 1800.0
# the deviation the CUSUM ignores, in quiet-period standard deviations of the residual. Chosen on the validation seeds of
# the evaluation (scripts/evaluate_model.py --tune): see the curve of detection against fault size in docs/architecture.md
ALLOWANCE = 2.0
# one reading's standardised residual is clipped to this. With the time weighting a single knock adds at most
# (Z_CAP - ALLOWANCE) times its few seconds, so the cap can be high enough that a large fault crosses in minutes
Z_CAP = 40.0
# one reading adds at most the excess over this many seconds, so the first reading after a silence counts like one reading
MAX_STEP_S = 120.0
# the accumulators never exceed this many standard-deviation minutes, so a long fault cannot make the score unbounded. A
# model whose measured boundary is above half of it is refused (it could hardly ever be crossed)
S_CAP = 3000.0
# once the boundary is measured the accumulators are capped at this many boundaries: the score is 1.0 at three, so more
# only delays the clear when the fault ends
CAP_BOUNDARIES = 3.0
# a sensor is watched only when the regression explains at least this share of its variance on the fit rows. A sensor
# that nothing else predicts (a lone driver of the machine) would accumulate every change of state as a fault
MIN_R2 = 0.5
# ridge penalty on the scaled regression, so a column that mirrors another cannot get huge opposite weights
RIDGE = 1.0
# the spread model is read from the residuals in this many bins of g, by quantile
SPREAD_BINS = 10
# the level of a residual is followed over this many seconds and clipped to LEVEL_BOUND times its hour-to-hour wander;
# chosen on the validation seeds of the evaluation, like ALLOWANCE
LEVEL_TAU_S = 2 * 3600.0
LEVEL_BOUND = 4.0
# a residual level is measured in windows of this length to estimate its wander
LEVEL_WINDOW_S = 3600.0


@dataclass
class Detector:
    """Per-sensor regression weights and residual spreads learned from the clean fit rows."""

    cols: list
    center: np.ndarray
    scale: np.ndarray
    # one row per target sensor: weights on [other sensors now, other sensors smoothed, daily profile] and the intercept
    coef: np.ndarray
    # the quiet-period spread of each residual and how much it grows with g (see the module note), scaled units
    quiet_sd: np.ndarray
    slope: np.ndarray
    # which sensors the expectation is good enough to watch (see MIN_R2)
    active: np.ndarray = None
    # the largest level the slow adaptation may reach for each sensor, scaled units
    level_bound: np.ndarray = None
    # set by ml_service from the validation readings: the raw score that maps to 0.7 and the one that maps to 0
    boundary: float = 1.0
    typical: float = 0.0
    arl_hours: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class DetectorState:
    """What must survive between readings of one machine."""

    smooth: np.ndarray | None = None  # (views, sensors)
    last_t: float | None = None
    warm_from: float | None = None
    s_pos: np.ndarray | None = None
    s_neg: np.ndarray | None = None
    # the time each accumulator last left zero, for "over the last N minutes"
    since_pos: np.ndarray | None = None
    since_neg: np.ndarray | None = None
    # the slow level of each residual, scaled units (see the module note)
    level: np.ndarray | None = None
    # the residual summed over the current run of each accumulator (scaled units times minutes), for the stated offset
    area_pos: np.ndarray | None = None
    area_neg: np.ndarray | None = None
    # the slow level of each sensor in each operating state of the baseline, sensor units (ml_service keeps it)
    base_level: np.ndarray | None = None
    # the observed time between readings, a slow average and how many readings have stepped the state
    interval_s: float | None = None
    steps: int = 0
    # which model the state belongs to. A state left by another model (a retrain) is carried over by ml_service when the
    # new model reads the same sensors on close enough scales and started cold otherwise
    model_id: str | None = None
    # the basis the state is expressed in: the detector's columns, centre, scale and boundary, so it can be re-expressed
    # in a new model's units after a retrain
    basis: dict | None = None
    # a cold start: no level was known, so for the warm-up the level is the running mean of the machine's own residuals
    # (warm_n of them so far) and not a figure from training. base_from and base_n do the same for the per-state levels
    cold: bool = False
    warm_n: int = 0
    base_from: float | None = None
    base_n: np.ndarray | None = None

    def to_dict(self) -> dict:
        def f(a):
            return None if a is None else np.asarray(a, dtype=float).tolist()
        return {"smooth": f(self.smooth), "last_t": self.last_t, "warm_from": self.warm_from, "s_pos": f(self.s_pos),
                "s_neg": f(self.s_neg), "since_pos": f(self.since_pos), "since_neg": f(self.since_neg),
                "level": f(self.level), "base_level": f(self.base_level), "interval_s": self.interval_s,
                "steps": int(self.steps), "model_id": self.model_id, "area_pos": f(self.area_pos),
                "area_neg": f(self.area_neg), "basis": self.basis, "cold": bool(self.cold), "warm_n": int(self.warm_n),
                "base_from": self.base_from, "base_n": f(self.base_n)}

    @classmethod
    def from_dict(cls, data: dict) -> "DetectorState":
        def a(v):
            return None if v is None else np.array(v, dtype=float)
        model_id = data.get("model_id")
        basis = data.get("basis")
        return cls(a(data.get("smooth")), data.get("last_t"), data.get("warm_from"), a(data.get("s_pos")),
                   a(data.get("s_neg")), a(data.get("since_pos")), a(data.get("since_neg")), a(data.get("level")),
                   a(data.get("area_pos")), a(data.get("area_neg")), a(data.get("base_level")), data.get("interval_s"),
                   int(data.get("steps") or 0), model_id if isinstance(model_id, str) else None,
                   basis if isinstance(basis, dict) else None, bool(data.get("cold")), int(data.get("warm_n") or 0),
                   data.get("base_from"), a(data.get("base_n")))


class MemoryStateStore:
    """The in-memory store the evaluation and the default scoring path use. The server supplies one backed by a table."""

    def __init__(self):
        self._states: dict = {}

    def get(self, key) -> DetectorState | None:
        return self._states.get(key)

    def put(self, key, state: DetectorState) -> None:
        self._states[key] = state

    def clear(self) -> None:
        self._states.clear()


def time_of_day(t) -> np.ndarray:
    """Four terms of a daily profile (the day and its first harmonic as sine and cosine) for epoch seconds t."""
    phase = 2.0 * np.pi * (np.asarray(t, dtype=float) % 86400.0) / 86400.0
    return np.stack([np.sin(phase), np.cos(phase), np.sin(2 * phase), np.cos(2 * phase)], axis=-1)


def _features(Z: np.ndarray, smooth: np.ndarray, j: int, tod: np.ndarray) -> np.ndarray:
    """Other sensors now and in each smoothed view and the daily profile. smooth is (views, k) or (n, views, k)."""
    keep = [i for i in range(Z.shape[-1]) if i != j]
    views = smooth[..., keep].reshape(*smooth.shape[:-2], -1)
    return np.concatenate([Z[..., keep], views, tod], axis=-1)


def smoothed_series(Z: np.ndarray, times: np.ndarray) -> np.ndarray:
    """The exponentially smoothed views of each column along the readings, one per SMOOTH_TAUS: an (n, views, k) array."""
    out = np.empty((len(Z), len(SMOOTH_TAUS), Z.shape[1]))
    out[0] = Z[0]
    taus = np.array(SMOOTH_TAUS)[:, None]
    for i in range(1, len(Z)):
        alpha = 1.0 - np.exp(-max(times[i] - times[i - 1], 0.0) / taus)
        out[i] = out[i - 1] + alpha * (Z[i] - out[i - 1])
    return out


def _transient(Z: np.ndarray, fast: np.ndarray) -> np.ndarray:
    """g for every target sensor at once: the root mean square of the OTHER sensors' distance from their quick view."""
    d2 = (Z - fast) ** 2
    k = Z.shape[-1]
    if k < 2:
        return np.zeros_like(Z)
    total = d2.sum(axis=-1, keepdims=True)
    return np.sqrt(np.maximum(total - d2, 0.0) / (k - 1))


def _spread_model(r: np.ndarray, g: np.ndarray) -> tuple[float, float]:
    """quiet and slope of sd(g)^2 = quiet^2 + (slope g)^2, from robust spreads of the residual in bins of g."""
    edges = np.unique(np.quantile(g, np.linspace(0.0, 1.0, SPREAD_BINS + 1)))
    if len(edges) < 3:
        sd = float(np.median(np.abs(r - np.median(r))) * 1.4826)
        return max(sd, 1e-6), 0.0
    which = np.clip(np.searchsorted(edges, g, side="right") - 1, 0, len(edges) - 2)
    gx, sx = [], []
    for b in range(len(edges) - 1):
        part = r[which == b]
        if len(part) < 30:
            continue
        gx.append(float(np.median(g[which == b])))
        sx.append(float(np.median(np.abs(part - np.median(part))) * 1.4826))
    gx, sx = np.array(gx), np.array(sx)
    if len(gx) < 2:
        return max(float(sx.min()) if len(sx) else 1e-6, 1e-6), 0.0
    # least squares on the squares, kept non-negative. The quiet spread is never above the quietest bin's own spread
    A = np.column_stack([np.ones_like(gx), gx ** 2])
    coef, *_ = np.linalg.lstsq(A, sx ** 2, rcond=None)
    quiet2 = float(np.clip(coef[0], (0.5 * sx.min()) ** 2, sx.min() ** 2))
    slope2 = float(max(coef[1], 0.0))
    return max(np.sqrt(quiet2), 1e-6), float(np.sqrt(slope2))


def _window_means(r: np.ndarray, times: np.ndarray, width: float) -> np.ndarray:
    keys = np.floor(times / width)
    _, inverse = np.unique(keys, return_inverse=True)
    sums = np.bincount(inverse, weights=r)
    counts = np.bincount(inverse)
    return sums[counts >= 5] / counts[counts >= 5]


def fit(X: np.ndarray, times: np.ndarray, cols: list) -> Detector:
    """Learn the expected value of each sensor from the clean rows X (n, k), in time order, with their epoch times."""
    center = np.median(X, axis=0)
    q1, q3 = np.percentile(X, [25, 75], axis=0)
    scale = np.where(q3 - q1 > 1e-9, q3 - q1, np.where(X.std(axis=0) > 1e-9, X.std(axis=0), 1.0))
    Z = (X - center) / scale
    smooth = smoothed_series(Z, times)
    g_all = _transient(Z, smooth[:, 0, :])
    k = X.shape[1]
    tod = time_of_day(times)
    coef = np.zeros((k, (1 + len(SMOOTH_TAUS)) * (k - 1) + 4 + 1))
    quiet = np.ones(k)
    slope = np.zeros(k)
    bound = np.zeros(k)
    active = np.zeros(k, dtype=bool)
    for j in range(k):
        F = np.hstack([_features(Z, smooth, j, tod), np.ones((len(Z), 1))])
        penalty = RIDGE * np.eye(F.shape[1])
        penalty[-1, -1] = 0.0
        w = np.linalg.solve(F.T @ F + penalty * len(F) * 1e-3, F.T @ Z[:, j])
        coef[j] = w
        r = Z[:, j] - F @ w
        var = float(np.var(Z[:, j]))
        active[j] = var > 1e-12 and 1.0 - float(np.var(r)) / var >= MIN_R2
        quiet[j], slope[j] = _spread_model(r, g_all[:, j])
        # the wander of the residual's level on the fit rows. ml_service replaces the bound with one measured on the
        # validation readings, which the regression never saw and where the level wanders more
        means = _window_means(r, times, LEVEL_WINDOW_S)
        seen = float(np.std(means)) if len(means) >= 3 else quiet[j]
        bound[j] = LEVEL_BOUND * max(seen, quiet[j])
    return Detector(list(cols), center, scale, coef, quiet, slope, active, bound)


def residuals(det: Detector, times: np.ndarray, X: np.ndarray) -> np.ndarray:
    """The raw residuals (scaled units) of a run of readings, with the smoothed views run along them. No CUSUM, no level."""
    Z = (np.asarray(X, dtype=float) - det.center) / det.scale
    smooth = smoothed_series(Z, np.asarray(times, dtype=float))
    tod = time_of_day(times)
    out = np.empty_like(Z)
    for j in range(Z.shape[1]):
        F = np.hstack([_features(Z, smooth, j, tod), np.ones((len(Z), 1))])
        out[:, j] = Z[:, j] - F @ det.coef[j]
    return out


def wander(r: np.ndarray, times: np.ndarray) -> np.ndarray:
    """The hour-to-hour wander of each residual column: the spread of its hourly means."""
    out = np.zeros(r.shape[1])
    for j in range(r.shape[1]):
        means = _window_means(r[:, j], times, LEVEL_WINDOW_S)
        out[j] = float(np.std(means)) if len(means) >= 3 else 0.0
    return out


def _expected(det: Detector, z: np.ndarray, smooth: np.ndarray, tod: np.ndarray) -> np.ndarray:
    """The expected value of every sensor at once: one row of features per sensor against its weights."""
    k = len(z)
    other = np.array([[i for i in range(k) if i != j] for j in range(k)])
    views = smooth[:, other].transpose(1, 0, 2).reshape(k, -1)
    F = np.concatenate([z[other], views, np.tile(tod, (k, 1)), np.ones((k, 1))], axis=1)
    return (F * det.coef).sum(axis=1)


def spread_now(det: Detector, z: np.ndarray, smooth: np.ndarray) -> np.ndarray:
    g = _transient(z[None], smooth[0][None])[0]
    return np.sqrt(det.quiet_sd ** 2 + (det.slope * g) ** 2)


def reset_gap_s(interval_s: float) -> float:
    return max(RESET_GAP_S, GAP_INTERVALS * max(float(interval_s), 1.0))


def _score(state: DetectorState) -> float:
    if state.s_pos is None:
        return 0.0
    return float(max(state.s_pos.max(), state.s_neg.max()))


def step(det: Detector, state: DetectorState, t: float, x: np.ndarray, interval_s: float) -> float:
    """
    Take one reading (time t in epoch seconds, values x in the detector's column order) and return its raw score.

    The raw score is the largest accumulator over the sensors, in standard-deviation minutes. The state is updated in
    place. interval_s is the observed posting interval of the machine: it sets how long a gap must be to reset.
    """
    z = (np.asarray(x, dtype=float) - det.center) / det.scale
    k = len(z)
    if state.last_t is not None and t <= state.last_t and state.smooth is not None:
        # a retry, a batch stamped at one instant or a reading out of order: it is no new evidence about time
        return _score(state)
    dt = None if state.last_t is None else t - state.last_t
    fresh = state.smooth is None or dt is None or dt > reset_gap_s(interval_s) or state.s_pos is None
    if state.level is None or len(state.level) != k:
        # nothing is known about this machine's present level: it is read from its own residuals during the warm-up
        state.level = np.zeros(k)
        state.cold, state.warm_n = True, 0
    if fresh:
        state.smooth = np.tile(z, (len(SMOOTH_TAUS), 1))
        if state.s_pos is None or len(state.s_pos) != k:
            state.s_pos, state.s_neg = np.zeros(k), np.zeros(k)
            state.since_pos, state.since_neg = np.full(k, t), np.full(k, t)
        state.warm_from = t
        state.last_t = t
        state.steps += 1
        return _score(state)
    alpha = 1.0 - np.exp(-dt / np.array(SMOOTH_TAUS)[:, None])
    state.smooth = state.smooth + alpha * (z - state.smooth)
    state.last_t = t
    state.steps += 1
    weight = min(dt, MAX_STEP_S)
    expected = _expected(det, z, state.smooth, time_of_day(t))
    raw_r = z - expected
    if t - state.warm_from < WARMUP_S:
        if state.cold:
            # a cold start takes the level from the machine's own readings: the running mean of its residuals so far
            bound = det.level_bound if det.level_bound is not None else np.full(k, np.inf)
            state.warm_n += 1
            clipped = np.clip(raw_r, -Z_CAP * det.quiet_sd, Z_CAP * det.quiet_sd)
            state.level = np.clip(state.level + (clipped - state.level) / state.warm_n, -bound, bound) * det.active
        # the accumulators are held through the warm-up: no accumulation and no decay
        return _score(state)
    state.cold = False
    # the slow level first, so a reading's own residual moves it only a little
    a = 1.0 - np.exp(-weight / LEVEL_TAU_S)
    bound = det.level_bound if det.level_bound is not None else np.full(k, np.inf)
    state.level = np.clip(state.level + a * (np.clip(raw_r, -Z_CAP * det.quiet_sd, Z_CAP * det.quiet_sd) - state.level),
                          -bound, bound)
    sd = spread_now(det, z, state.smooth)
    r = np.where(det.active, np.clip((raw_r - state.level) / sd, -Z_CAP, Z_CAP), 0.0)
    minutes = weight / REF_S
    cap = min(S_CAP, CAP_BOUNDARIES * det.boundary) if det.extra.get("measured") else S_CAP
    new_pos = np.minimum(np.maximum(0.0, state.s_pos + (r - ALLOWANCE) * minutes), cap)
    new_neg = np.minimum(np.maximum(0.0, state.s_neg + (-r - ALLOWANCE) * minutes), cap)
    state.since_pos = np.where(state.s_pos <= 0.0, t - weight, state.since_pos)
    state.since_neg = np.where(state.s_neg <= 0.0, t - weight, state.since_neg)
    # the plain residual over each run, so the stated offset is its average and does not depend on how noisy the
    # residual was thought to be while the run built up
    excess = (raw_r - state.level) * minutes
    if state.area_pos is None or len(state.area_pos) != k:
        state.area_pos, state.area_neg = np.zeros(k), np.zeros(k)
    state.area_pos = np.where(new_pos > 0.0, np.where(state.s_pos <= 0.0, 0.0, state.area_pos) + excess, 0.0)
    state.area_neg = np.where(new_neg > 0.0, np.where(state.s_neg <= 0.0, 0.0, state.area_neg) - excess, 0.0)
    state.s_pos, state.s_neg = new_pos, new_neg
    return float(max(new_pos.max(), new_neg.max()))


def run(det: Detector, times: np.ndarray, X: np.ndarray, interval_s: float, state: DetectorState | None = None) -> np.ndarray:
    """Raw scores for a run of readings from a fresh state (or the one given). It is step() in a loop."""
    state = state or DetectorState()
    return np.array([step(det, state, float(t), X[i], interval_s) for i, t in enumerate(times)])


def normalise(det: Detector, raw: np.ndarray, threshold: float = 0.7, saturation_gap: float = 2.0) -> np.ndarray:
    """Raw score to 0-1: zero at typical and the threshold at the boundary and 1.0 two boundary distances beyond it."""
    gap = max(det.boundary - det.typical, 1e-9)
    below = threshold * (raw - det.typical) / gap
    above = threshold + (1.0 - threshold) * (raw - det.boundary) / (saturation_gap * gap)
    return np.clip(np.where(raw <= det.boundary, below, above), 0.0, 1.0)


def explain(det: Detector, state: DetectorState, x: np.ndarray, t: float) -> dict:
    """
    Which sensor the accumulators blame and how: the sensor, the average offset over the run and for how long.

    {"sensor", "direction" ("above" or "below"), "expected", "value", "offset", "minutes", "kind": "drift"}. The offset is
    the mean residual (less its slow level) since the accumulator last left zero, in sensor units. It is an average over
    the run, which is steadier than the gap between one reading and its expected value and it is stated as approximate:
    for a drift it is the average over the run and not the latest size. Call it straight after step() for the same reading.
    """
    z = (np.asarray(x, dtype=float) - det.center) / det.scale
    scores = np.maximum(state.s_pos, state.s_neg)
    j = int(np.argmax(scores))
    f = np.concatenate([_features(z, state.smooth, j, time_of_day(t)), [1.0]])
    level = 0.0 if state.level is None else float(state.level[j])
    expected = float((f @ det.coef[j] + level) * det.scale[j] + det.center[j])
    up = state.s_pos[j] >= state.s_neg[j]
    since = state.since_pos[j] if up else state.since_neg[j]
    minutes = max((t - since) / 60.0, 1.0)
    area = state.area_pos if up else state.area_neg
    if area is not None:
        offset = float(area[j]) / max((t - since) / 60.0, 1e-9) * float(det.scale[j])
    else:
        accumulated = float(state.s_pos[j] if up else state.s_neg[j])
        offset = (accumulated / minutes + ALLOWANCE) * float(det.quiet_sd[j]) * float(det.scale[j])
    return {
        "sensor": det.cols[j], "direction": "above" if up else "below", "expected": round(expected, 4),
        "value": round(float(x[j]), 4), "offset": round(offset, 4), "minutes": max(int(round(minutes)), 1),
        "kind": "drift",
    }
