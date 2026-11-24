"""
Measuring an anomaly model before it is used: how often it would raise a false alert and whether it still catches
real faults.

Both measurements run the readings through the very same alert decision the live path uses
(services/anomaly_decision.py), reading by reading, so the figure is the alert count a machine would really have had.
This module knows nothing about scikit-learn: it takes a function that turns readings into normalised scores.

Faults are injected into held-out healthy readings. The four the model is held to are the client simulator's faults
(client/python/phaemos_client/nodes.py: bearing and overheat) and a current spike. Their size is the simulator's own:
multiples of the healthy value, which on a Celsius reading is large (x1.6 is +12 to 17 degrees). They are a floor a model
must clear to be used and not a claim about small faults: scripts/evaluate_model.py measures additive faults of several
sizes, faults at start-up, intermittent faults and slow drifts and reports them all.

A fault is caught only when an alert is raised within its stated deadline of the onset (deadline_s), not anywhere in the
fault's window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import numpy as np

from app.services import anomaly_decision as ad
from app.services import change_detector as cd

# the false alert budget of the contract: no more than one anomaly alert per machine per week on healthy data
BUDGET_PER_WEEK = 1.0
# stricter and stricter quantiles of the validation readings' healthy scores, tried in turn until the budget is met. The
# first is the contract's 1 reading in 1,000. The last is the worst validation reading itself. Four tries, so at most three
# tightenings
QUANTILES = (0.001, 0.0003, 0.0001, 0.0)
# a model that misses more than this share of the injected faults (within their deadlines) is refused like one that is
# too noisy. The faults are the simulator's own large ones, so this is a floor and not a claim about small faults. In the
# full evaluation on six test seeds the pico_w node type and the general model were refused by it while every machine
# model passed. The stuck value is not counted: the sensor health check handles it
MAX_MISSED_SHARE = 0.4
# fewest validation readings for the 1 in 1,000 quantile to mean anything: 2,000 readings put two of them beyond it on
# average, so the boundary lies between measured readings and not on the single worst one. Neighbouring readings are
# strongly alike, so the true number of independent readings is far smaller still and the doc says so
MIN_HELDOUT_ROWS = 2_000
SECONDS_PER_WEEK = 7 * 86_400.0

# the simulator's own faults (client/python/phaemos_client/nodes.py FAULTS): how each moves its fields at full severity,
# as multiples of the healthy value. A fault applies to the columns the model has and skips the rest
BEARING = {"vibration_x": 12.0, "vibration_y": 12.0, "vib_magnitude": 10.0, "fft_peak_hz": 3.5, "sound_level": 1.4,
           "contact_temp": 1.3}
OVERHEAT = {"temperature": 1.6, "ir_temperature": 2.2, "contact_temp": 2.4, "current_ma": 1.5, "power_mw": 1.5}
# each fault: the columns it moves and how its severity runs (0 is no change and 1 is the simulator's full severity)
# and for how many seconds. The shape lines up with the contract: a step and a slow drift in temperature (the
# simulator's overheat, jumping to full severity for an hour and ramped to full over six hours), a rise in vibration
# (its bearing fault ramped to full over two hours), a value that stops moving (not in the simulator) and a current
# spike (not in the simulator: current and power at four times their value for ten minutes, the size of a stalled
# motor). A spike of seconds is the threshold rules' job and a harmless excursion here on purpose. Every size is one a
# person would call a fault in every state of the machine: a model that reads the joint state of many sensors can miss
# a fault that stays inside one sensor's range while the machine idles. The results say so
FAULTS = {
    "temperature_step": {"columns": OVERHEAT, "ramp": False, "severity": 1.0, "seconds": 3_600, "deadline_s": 1_800},
    "slow_drift": {"columns": OVERHEAT, "ramp": True, "severity": 1.0, "seconds": 21_600, "deadline_s": 10_800},
    "vibration_rise": {"columns": BEARING, "ramp": True, "severity": 1.0, "seconds": 7_200, "deadline_s": 3_600},
    # a sensor whose value stops moving is a sensor fault. The server's sensor health check handles it, so it is
    # neither required of the model nor counted in its refusal rule. It stays in the table, marked
    "stuck_value": {"columns": None, "ramp": False, "severity": 0.0, "seconds": 7_200, "handled": True},
    "current_spike": {"columns": {"current_ma": 4.0, "power_mw": 4.0}, "ramp": False, "severity": 1.0, "seconds": 600,
                      "deadline_s": 600},
}
FAULT_KINDS = tuple(FAULTS)
# the columns tried in turn for a stuck value: the first one the model uses freezes at the value it had at the onset
STUCK_COLUMNS = ("temperature", "humidity", "pressure", "light_level", "vibration_x", "current_ma")
# trials per fault type, spread evenly through the held-out readings
TRIALS = 5


def utc(epoch: float) -> datetime:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc)


@dataclass
class Segment:
    """Consecutive held-out readings of one machine: epoch times, (n, k) unscaled values and its posting interval."""

    key: str
    interval_s: float
    times: np.ndarray
    X: np.ndarray


@dataclass
class Replay:
    raises: list = field(default_factory=list)
    escalations: int = 0
    resolves: int = 0


def replay(times: np.ndarray, scores: np.ndarray, interval_s: float, gated: bool = True) -> Replay:
    """
    Run scored readings through ad.decide one reading at a time, keeping the open alert and the last resolve.

    gated skips the call while no alert is open and fewer readings than the raise rule can need are at or over the
    boundary in the raise window. That count is a necessary condition of a raise (80 per cent of at least 5 readings
    is at least 4), so the gate changes no result and only saves time. A test runs both and compares.
    """
    n = len(times)
    out = Replay()
    if n == 0:
        return out
    interval_s = max(float(interval_s), 1.0)
    # the decision works on the interval the readings show, so the windows here are cut for that interval too
    if n > ad.INTERVAL_MIN_GAPS:
        gaps = np.diff(np.asarray(times, dtype=float))
        gaps = gaps[gaps > 0]
        if len(gaps) >= ad.INTERVAL_MIN_GAPS:
            seen = float(np.median(gaps))
            interval_s = min(max(seen, interval_s * ad.INTERVAL_BOUNDS[0], 1.0), interval_s * ad.INTERVAL_BOUNDS[1])
    dts = [utc(t) for t in times]
    scored = scores.tolist()
    points = list(zip(dts, scored))
    over = np.concatenate(([0], np.cumsum(scores >= ad.BOUNDARY)))
    window = ad.raise_window_s(interval_s)
    clear = ad.history_seconds(interval_s)
    first_raise = np.searchsorted(times, times - window, side="left")
    first_clear = np.searchsorted(times, times - clear, side="left")
    # a raise needs 80 per cent of at least MIN_SHORT_POINTS readings at or over the boundary in some window that
    # lies inside the full one, so at least this many in the full window
    need = -(-ad.MIN_SHORT_POINTS * ad.RAISE_SHARE_NUMERATOR // ad.RAISE_SHARE_DENOMINATOR)
    open_since = None
    last_resolved = None
    for i in range(n):
        if gated and open_since is None and over[i + 1] - over[first_raise[i]] < need:
            continue
        decision = ad.decide(points[first_clear[i]:i + 1], open_since, last_resolved, dts[i], interval_s)
        if decision.action == "raise":
            open_since = dts[i]
            out.raises.append({"index": i, "time": float(times[i]), "severity": decision.severity})
        elif decision.action == "escalate":
            out.escalations += 1
        elif decision.action == "resolve":
            open_since, last_resolved = None, dts[i]
            out.resolves += 1
    return out


def false_alert_rate(segments: list[Segment], score_fn: Callable) -> dict:
    """The anomaly alerts the model would have raised on healthy held-out readings, per machine per week."""
    alerts, seconds = 0, 0.0
    for seg in segments:
        result = replay(seg.times, score_fn(seg.X, seg.times, seg.interval_s), seg.interval_s)
        alerts += len(result.raises)
        seconds += len(seg.times) * seg.interval_s
    weeks = seconds / SECONDS_PER_WEEK
    return {
        "alerts": alerts, "heldout_hours": round(seconds / 3600.0, 2),
        "per_machine_week": (alerts / weeks) if weeks > 0 else None,
    }


def inject(kind: str, X: np.ndarray, cols: list[str], start: int, rows: int) -> np.ndarray | None:
    """A copy of X with the fault applied from row start for rows rows. It returns None when no column fits the fault."""
    fault = FAULTS[kind]
    if fault["columns"] is None:
        Y = X.copy()
        stop = min(start + rows, len(Y))
        if stop <= start:
            return None
        for name in STUCK_COLUMNS:
            if name in cols:
                Y[start:stop, cols.index(name)] = Y[start, cols.index(name)]
                return Y
        return None
    return inject_spec(fault, X, cols, start, rows)


# the columns that show whether a machine is running, tried in turn, for start-up onsets and running-only faults
LOAD_COLUMNS = ("current_ma", "power_mw", "vib_magnitude", "vibration_x", "sound_level")


def _running(X: np.ndarray, cols: list[str]) -> np.ndarray | None:
    for name in LOAD_COLUMNS:
        if name in cols:
            c = X[:, cols.index(name)]
            mid = (np.percentile(c, 10) + np.percentile(c, 90)) / 2.0
            return c > mid
    return None


def startups(X: np.ndarray, cols: list[str]) -> np.ndarray:
    """Row indexes where the machine starts running (its load column rises through the middle of its range)."""
    run = _running(X, cols)
    if run is None:
        return np.empty(0, dtype=int)
    return np.flatnonzero(run[1:] & ~run[:-1]) + 1


def inject_spec(spec: dict, X: np.ndarray, cols: list[str], start: int, rows: int, times: np.ndarray | None = None,
                interval_s: float = 5.0) -> np.ndarray | None:
    """
    A copy of X with one fault of a specification applied from row start for rows rows or None when no column fits.

    spec keys: "columns" {column: multiple} multiplies the healthy value, "add" {column: amount} adds to it, "ramp" grows
    the fault linearly from nothing to full over its length, "intermittent" (on_s, off_s) shows it only in the on spells,
    "running_only" shows it only while the machine runs. "severity" scales it (1 is the stated size).
    """
    Y = X.copy()
    stop = min(start + rows, len(Y))
    if stop <= start:
        return None
    mult = {c: m for c, m in (spec.get("columns") or {}).items() if c in cols}
    add = {c: d for c, d in (spec.get("add") or {}).items() if c in cols}
    if not mult and not add:
        return None
    n = stop - start
    severity = spec.get("severity", 1.0) * (np.arange(n) / max(rows - 1, 1) if spec.get("ramp") else np.ones(n))
    if spec.get("intermittent"):
        on, off = spec["intermittent"]
        since = (times[start:stop] - times[start]) if times is not None else np.arange(n) * float(interval_s)
        severity = severity * ((since % (on + off)) < on)
    if spec.get("running_only"):
        run = _running(X, cols)
        if run is not None:
            severity = severity * run[start:stop]
    for name, multiple in mult.items():
        Y[start:stop, cols.index(name)] *= 1.0 + (multiple - 1.0) * severity
    for name, amount in add.items():
        Y[start:stop, cols.index(name)] += amount * severity
    return Y


def lead_rows(interval_s: float) -> int:
    """Healthy readings before an onset: an hour, so the detector is past its warm-up and its slow views have settled."""
    return int(max(3_600.0, ad.raise_window_s(interval_s) + cd.WARMUP_S + 600.0) / interval_s) + 5


def detection(
    segments: list[Segment], cols: list[str], score_fn: Callable, replay_fn=None, faults: dict | None = None,
    trials: int | None = None, use_deadline: bool = True,
) -> dict:
    """
    Inject each fault into the held-out readings `trials` times and say whether and how soon an alert was raised.

    Returns {"faults": [per type: kind, applicable, trials, caught, median_delay_s, delays_s], "missed_share": float}.
    A trial is caught when the decision raises an alert at or after the fault's onset and no later than its deadline_s
    (use_deadline=False keeps the old rule: anywhere before the fault ends). The healthy lead-in before the onset fills
    the decision's windows with ordinary readings first. A fault with "at_startup" starts where the machine starts
    running. replay_fn lets the evaluation run another alert rule through the same trials. It takes (times, scores,
    interval) and returns an object with a list `raises` of dicts with a "time".
    """
    replay_fn = replay_fn or replay
    faults = FAULTS if faults is None else faults
    trials = TRIALS if trials is None else trials
    usable = [s for s in segments if len(s.times) >= 200]
    table = []
    caught_all = trials_all = 0
    for kind, spec in faults.items():
        if spec.get("handled"):
            table.append({"kind": kind, "applicable": False, "handled": True, "trials": 0, "caught": 0,
                          "median_delay_s": None, "delays_s": []})
            continue
        delays: list[float] = []
        done = 0
        for t in range(trials):
            if not usable:
                break
            seg = usable[t % len(usable)]
            rows = max(int(spec["seconds"] / seg.interval_s), 1)
            lead = lead_rows(seg.interval_s)
            room = len(seg.times) - lead
            if room < 10:
                continue
            # a fault longer than the held-out readings left after the lead-in is cut to what there is
            length = min(rows, max(room, 1))
            slack = max(room - length, 0)
            per_seg = math.ceil(trials / max(len(usable), 1))
            frac = (t // max(len(usable), 1) + 0.5) / per_seg
            start = lead + int(slack * min(frac, 1.0))
            if spec.get("at_startup"):
                ups = startups(seg.X, cols)
                ups = ups[(ups >= lead) & (ups <= lead + slack)]
                if not len(ups):
                    continue
                start = int(ups[min(int(frac * len(ups)), len(ups) - 1)])
            if spec is FAULTS.get(kind):
                Y = inject(kind, seg.X, cols, start, length)
            else:
                Y = inject_spec(spec, seg.X, cols, start, length, seg.times, seg.interval_s)
            if Y is None:
                break
            lo = max(0, start - lead)
            hi = min(len(seg.times), start + length + int(ad.raise_window_s(seg.interval_s) / seg.interval_s))
            result = replay_fn(seg.times[lo:hi], score_fn(Y[lo:hi], seg.times[lo:hi], seg.interval_s), seg.interval_s)
            onset = float(seg.times[start])
            end = float(seg.times[min(start + length, len(seg.times) - 1)])
            limit = min(end, onset + spec["deadline_s"]) if use_deadline and spec.get("deadline_s") else end
            done += 1
            hits = [r["time"] for r in result.raises if onset <= r["time"] <= limit]
            if hits:
                delays.append(hits[0] - onset)
        table.append({
            "kind": kind, "applicable": done > 0, "trials": done, "caught": len(delays),
            "median_delay_s": float(np.median(delays)) if delays else None,
            "delays_s": [round(d, 1) for d in delays], "deadline_s": spec.get("deadline_s") if use_deadline else None,
        })
        caught_all += len(delays)
        trials_all += done
    missed = (1.0 - caught_all / trials_all) if trials_all else None
    return {"faults": table, "missed_share": missed, "trials": trials_all, "caught": caught_all}
