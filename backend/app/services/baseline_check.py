"""
A per-sensor baseline beside the Isolation Forest.

The forest says "this combination of readings is unusual" and cannot say how far outside the healthy range a single
sensor has gone: a tree can only split inside the range it saw, so a value far beyond it scores like the most extreme
healthy one. This check answers the other question. For each sensor it learns the machine's own normal range from the
same clean fit rows and says how many robust deviations a reading sits from it.

A machine is not one state. It idles and it runs and the same temperature or current is ordinary in one and a fault in
the other. So the fit rows are first grouped into at most MAX_STATES operating states by k-means on the robustly scaled
columns. Each state keeps a median and a robust spread (the median absolute deviation) for every sensor. To judge sensor
j of a reading, the state is chosen from the other sensors only, so a faulty sensor cannot move the reading into the
state that suits it. The sensor's distance is |value - state median| / state spread. The reading's raw baseline score
is the largest distance over its sensors.

A sensor's level within a state may drift slowly for reasons that are not a fault (a warmer room, a season, a lighter
product). ml_service follows that level per state with a slow average and takes it off the reading before the baseline and
the forest judge it, clipped to plus or minus level_bound (LEVEL_BOUND times the hour-to-hour wander of the level on the fit
rows), so a change larger than the machine ever wandered is never learned away live.

The module is pure: arrays in and arrays out, no database, no clock. The boundary that turns the raw distance into the
public 0 to 1 scale is measured by ml_service on validation readings exactly as the forest's is. It is stored here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import KMeans

# at most this many operating states. Idle and running is two. A third covers a start-up or a low-load mode
MAX_STATES = 4
# another state is kept when it cuts the k-means inertia by at least this share. Smaller gains are the ordinary spread
# of one state and not a second state
STATE_GAIN = 0.15
# a state with fewer rows than this share of the fit rows is merged away, so a brief excursion never becomes a state
MIN_STATE_SHARE = 0.02
# k-means is fitted on at most this many rows, taken evenly, so a large fit split costs the same as a small one
CLUSTER_ROWS = 6000
# the spread of a sensor in a state never falls under this share of its spread over all fit rows, so a sensor that sits
# on one value for hours cannot make every small wobble look enormous
SPREAD_FLOOR = 0.05
# the median absolute deviation of a normal distribution is this share of its standard deviation
MAD_TO_SD = 1.4826
SEED = 42
# the largest slow shift of a sensor's level within a state that is followed live, in hour-to-hour wanders of that level
LEVEL_BOUND = 3.0
LEVEL_WINDOW_S = 3600.0


@dataclass
class Baseline:
    """What one machine's sensors normally do, per operating state. Fitted by fit() and used through score()."""

    cols: list
    center: np.ndarray
    scale: np.ndarray
    centroids: np.ndarray
    median: np.ndarray
    spread: np.ndarray
    # set by ml_service from the validation readings: the raw distance that maps to 0 and to 0.7
    typical: float = 0.0
    boundary: float = 1.0
    # (states, k): the largest slow level shift per state and sensor that is followed live, sensor units
    level_bound: np.ndarray | None = None
    # (k,): each sensor's own healthy tail, in its distances, measured on validation readings by ml_service. A sensor's
    # distance is read against it, so one sensor with harmless bursts (a forklift on the vibration) does not set the
    # limit of every other sensor. None reads every distance as it is
    sensor_scale: np.ndarray | None = None
    extra: dict = field(default_factory=dict)

    @property
    def states(self) -> int:
        return len(self.centroids)


def fit(X: np.ndarray, cols: list, times: np.ndarray | None = None) -> Baseline:
    """
    Learn the states and each sensor's median and spread in each state from the complete rows X (n, k).

    With the rows' epoch times it also measures how far each sensor's level wanders hour to hour in each state, which
    bounds the live slow adaptation (see the module note). Without them no level is followed.
    """
    center = np.median(X, axis=0)
    q1, q3 = np.percentile(X, [25, 75], axis=0)
    scale = np.where(q3 - q1 > 1e-9, q3 - q1, np.where(X.std(axis=0) > 1e-9, X.std(axis=0), 1.0))
    Z = (X - center) / scale
    sample = Z if len(Z) <= CLUSTER_ROWS else Z[np.linspace(0, len(Z) - 1, CLUSTER_ROWS).round().astype(int)]
    best, inertia = None, None
    for k in range(1, min(MAX_STATES, len(sample)) + 1):
        model = KMeans(n_clusters=k, n_init=3, random_state=SEED).fit(sample)
        if best is None or (inertia > 0 and (inertia - model.inertia_) / inertia >= STATE_GAIN):
            best, inertia = model, model.inertia_
        else:
            break
    centroids = best.cluster_centers_
    labels = np.argmin(((Z[:, None, :] - centroids[None]) ** 2).sum(axis=2), axis=1)
    keep = [s for s in range(len(centroids)) if (labels == s).mean() >= MIN_STATE_SHARE] or [0]
    centroids = centroids[keep]
    labels = np.argmin(((Z[:, None, :] - centroids[None]) ** 2).sum(axis=2), axis=1)
    overall = np.maximum(np.median(np.abs(X - center), axis=0) * MAD_TO_SD, 1e-9)
    median = np.empty((len(centroids), X.shape[1]))
    spread = np.empty_like(median)
    for s in range(len(centroids)):
        rows = X[labels == s]
        median[s] = np.median(rows, axis=0)
        mad = np.median(np.abs(rows - median[s]), axis=0) * MAD_TO_SD
        spread[s] = np.maximum(mad, SPREAD_FLOOR * overall)
    level_bound = None
    if times is not None and len(times) == len(X):
        level_bound = np.zeros_like(median)
        for s in range(len(centroids)):
            inside = labels == s
            keys = np.floor(times[inside] / LEVEL_WINDOW_S)
            if inside.sum() < 10:
                continue
            _, inverse = np.unique(keys, return_inverse=True)
            counts = np.bincount(inverse)
            dev = X[inside] - median[s]
            means = np.stack([np.bincount(inverse, weights=dev[:, j]) for j in range(X.shape[1])], axis=1)
            means = means[counts >= 3] / counts[counts >= 3][:, None]
            wander = means.std(axis=0) if len(means) >= 3 else spread[s]
            level_bound[s] = LEVEL_BOUND * np.maximum(wander, 0.25 * spread[s])
    return Baseline(list(cols), center, scale, centroids, median, spread, level_bound=level_bound)


def state_of(baseline: Baseline, X: np.ndarray) -> np.ndarray:
    """The operating state of each row of X, from all its sensors."""
    Z = (np.atleast_2d(X) - baseline.center) / baseline.scale
    return np.argmin(((Z[:, None, :] - baseline.centroids[None]) ** 2).sum(axis=2), axis=1)


def distances(baseline: Baseline, X: np.ndarray) -> np.ndarray:
    """Each sensor's distance from its normal range, in robust deviations, for each row of X: an (n, k) array."""
    Z = (X - baseline.center) / baseline.scale
    per_column = (Z[:, None, :] - baseline.centroids[None]) ** 2
    total = per_column.sum(axis=2)
    out = np.empty(X.shape)
    for j in range(X.shape[1]):
        # the state is chosen without sensor j
        state = np.argmin(total - per_column[:, :, j], axis=1)
        out[:, j] = np.abs(X[:, j] - baseline.median[state, j]) / baseline.spread[state, j]
    return out


def _watched(baseline: Baseline) -> np.ndarray:
    """Which sensors count towards the score. A room channel kept only as context (ml_service's ambient plan) does not."""
    watch = baseline.extra.get("watch") if isinstance(baseline.extra, dict) else None
    if watch is None or not np.any(watch):
        return np.ones(len(baseline.cols), dtype=bool)
    return np.asarray(watch, dtype=bool)


def _relative(baseline: Baseline, d: np.ndarray) -> np.ndarray:
    scale = getattr(baseline, "sensor_scale", None)
    return d if scale is None else d / np.maximum(scale, 1e-9)


def raw_scores(baseline: Baseline, X: np.ndarray) -> np.ndarray:
    """The largest distance of each row over the watched sensors, each read against its own healthy tail."""
    return _relative(baseline, distances(baseline, X))[:, _watched(baseline)].max(axis=1)


# the score reaches 1.0 this many boundary distances beyond the boundary. Critical (0.85) is half way, so a critical
# baseline score means twice as far from typical as the boundary and not merely a little past it. A fault that moves a
# sensor several times its range saturates at 1.0 and a healthy state change (a machine starting up) that overshoots the
# boundary by a third does not look critical
SATURATION_GAP = 2.0


def normalise(baseline: Baseline, raw: np.ndarray, threshold: float = 0.7) -> np.ndarray:
    """
    Map raw distances onto 0 to 1: a typical healthy reading is 0 and the measured boundary is the threshold.

    Below the boundary the map is a straight line from typical to the boundary. Beyond it the score climbs from the
    threshold to 1.0 over SATURATION_GAP boundary distances.
    """
    gap = max(baseline.boundary - baseline.typical, 1e-9)
    below = threshold * (raw - baseline.typical) / gap
    above = threshold + (1.0 - threshold) * (raw - baseline.boundary) / (SATURATION_GAP * gap)
    return np.clip(np.where(raw <= baseline.boundary, below, above), 0.0, 1.0)


def explain(baseline: Baseline, x: np.ndarray) -> dict:
    """
    Which sensor of one reading is furthest from its range and how: the sensor, its value, its usual range and the side.

    The range is the state median plus and minus the measured boundary in spreads, so the value is outside it exactly
    when the reading is at or over the boundary.
    """
    row = np.asarray(x, dtype=float)[None]
    raw = distances(baseline, row)[0]
    d = np.where(_watched(baseline), _relative(baseline, raw[None])[0], -np.inf)
    j = int(np.argmax(d))
    Z = (row - baseline.center) / baseline.scale
    state = int(np.argmin(((Z - baseline.centroids) ** 2).sum(axis=1) - (Z[0, j] - baseline.centroids[:, j]) ** 2))
    med, spread = float(baseline.median[state, j]), float(baseline.spread[state, j])
    scale = 1.0 if getattr(baseline, "sensor_scale", None) is None else float(baseline.sensor_scale[j])
    width = baseline.boundary * scale * spread
    value = float(row[0, j])
    return {
        "sensor": baseline.cols[j], "value": round(value, 4), "direction": "above" if value >= med else "below",
        "low": round(med - width, 4), "high": round(med + width, 4), "deviations": round(float(raw[j]), 2),
    }
