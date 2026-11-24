"""
The anomaly alert decision, as a pure function.

It takes the recent scored readings of one machine and says what to do about its anomaly alert. It has no database
and no clock of its own, so the live path (alert_service.evaluate_anomaly) and the evaluation that measures the false
alert rate (services/ml_service.py and scripts/evaluate_model.py) run exactly the same code.

An alert needs a sustained fault and not a lucky run of readings: most of the scored readings in a window must sit
at or over the model's boundary and so must their median. Once raised it stays open until a long calm (CLEAR_SECONDS or
CLEAR_INTERVALS intervals): a fault that comes and goes keeps one alert open and does not raise one alert per burst. A
machine that has just resolved waits before it can raise again, a warning for REARM_SECONDS and a critical window for
CRITICAL_REARM_SECONDS.

Time. The windows are measured back from the machine's newest scored reading and not from the moment of the call, so a
node whose readings arrive late still fills its windows. The machine has gone quiet only when its newest reading is older
than the live limit the ingest path itself uses (the larger of LIVE_MIN_SECONDS and LIVE_INTERVALS intervals). The
interval is the one the readings show (the median gap between the recent ones, within INTERVAL_BOUNDS of the stated
one), so a node that posts slower than its record still gets windows of enough readings.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

# the normalised score at or over which a reading counts as outside normal. It is the public boundary of the model
# (ml_service.ANOMALY_THRESHOLD is the same number: training maps its measured boundary onto it)
BOUNDARY = 0.7
# a window whose median reaches this is critical. It sits 0.15 above the boundary, which is about a fifth further
# from the typical reading than the boundary itself, so a critical alert means clearly and not just barely outside
CRITICAL_SCORE = 0.85
# an alert resolves only when the median of the calm window is under this. It sits well under the boundary so a
# score hovering at the edge cannot open and close the alert in turn
CLEAR_LEVEL = 0.5
# the share of scored readings in the raise window that must be at or over the boundary. Most and not all, so one
# stray normal reading in a real fault does not delay the alert. Compared as 4 in 5 in integers, never as a float
RAISE_SHARE_NUMERATOR, RAISE_SHARE_DENOMINATOR = 4, 5
# the raise window is the larger of this many seconds and RAISE_INTERVALS posting intervals. Two minutes is the
# shortest spell worth a person's attention. 24 intervals keeps a slow node's window as many readings long
RAISE_SECONDS = 120.0
RAISE_INTERVALS = 24
# a clear excursion does not wait for the whole window. The window shrinks as the median score rises: the full window at
# the boundary and this shorter one, the larger of RAISE_MIN_SECONDS and RAISE_MIN_INTERVALS intervals, at the critical
# score. The 80 per cent rule holds at every length and the fewest readings scale with the window (never under
# MIN_SHORT_POINTS). A minute is the shortest spell that is not a daily start-up or a single knock
RAISE_MIN_SECONDS = 60.0
RAISE_MIN_INTERVALS = 6
MIN_SHORT_POINTS = 5
# how many window lengths between the shortest and the full one are tried
WINDOW_STEPS = 5
# fewest scored readings in the raise window. Fewer than a dozen is too little to call a median or a share
MIN_RAISE_POINTS = 12
# the calm an open alert needs before it resolves: the larger of this many seconds and CLEAR_INTERVALS intervals. Half an
# hour is longer than the off spells of the intermittent faults the evaluation injects (ten minutes off and on, a running
# fault with eight minute stoppages), so such a fault keeps one alert open. The cost is that an alert stays open for half
# an hour after a real fault ends
CLEAR_SECONDS = 1800.0
CLEAR_INTERVALS = 120
# fewest scored readings in the clear window, for the same reason as the raise window
MIN_CLEAR_POINTS = 12
# the calm window may hold this share of readings at or over the boundary and still be calm: a healthy machine puts about
# one reading in a thousand there by construction and a half hour of a 5 s node is 360 readings. The newest short window
# must hold none, so an alert never resolves in the middle of a burst
CALM_MAX_SHARE = 0.05
# a gap between two scored readings longer than the larger of this many seconds and GAP_INTERVALS intervals resets the
# raise window, so a node that was silent does not join old readings to new ones. Thirty seconds is the ingest path's own
# live limit, so delivery jitter of a few seconds on a fast node is not a silence
GAP_INTERVALS = 3
GAP_MIN_SECONDS = 30.0
# the live limit of routes/telemetry.py (resolve_observed): a newest reading older than this means the machine went quiet
LIVE_MIN_SECONDS = 30.0
LIVE_INTERVALS = 3
# after an alert resolves, a new warning waits this long and a critical window this long. Both wait, so an intermittent
# fault cannot open a new critical alert every time it returns
REARM_SECONDS = 900.0
CRITICAL_REARM_SECONDS = 300.0
# an open alert whose scores have sat between the clear level and the boundary (the hysteresis band) for the whole clear
# window is closed once it is this old, with a note telling the person so, instead of staying open for ever
MAX_OPEN_SECONDS = 24 * 3600.0
# the observed interval is the median gap of up to this many recent readings, needs at least INTERVAL_MIN_GAPS gaps and is
# kept between a quarter and twenty times the stated interval (and between 1 s and a day)
INTERVAL_GAPS = 60
INTERVAL_MIN_GAPS = 5
INTERVAL_BOUNDS = (0.25, 20.0)


@dataclass(frozen=True)
class Decision:
    """
    What to do about a machine's anomaly alert.

    action   "raise" (open a new alert), "escalate" (an open warning becomes critical), "resolve" (close the open
             alert) or "none".
    severity "warning" or "critical" for raise and escalate. None for resolve and none.
    reason   one plain sentence for the alert message or the log, for example "9 of 12 scored readings in the last
             120 s were at or over the anomaly limit of 0.70 (median 0.91)". Empty for none.
    evidence the figures behind the decision: counts, share, median, window seconds. Small and JSON friendly.
    """

    action: str
    severity: str | None = None
    reason: str = ""
    evidence: dict = field(default_factory=dict)


NONE = Decision("none")


def raise_window_s(interval_s: float) -> float:
    return max(RAISE_SECONDS, RAISE_INTERVALS * interval_s)


def clear_window_s(interval_s: float) -> float:
    return max(CLEAR_SECONDS, CLEAR_INTERVALS * interval_s)


def gap_limit_s(interval_s: float) -> float:
    return max(GAP_MIN_SECONDS, GAP_INTERVALS * interval_s)


def live_limit_s(interval_s: float) -> float:
    return max(LIVE_MIN_SECONDS, LIVE_INTERVALS * interval_s)


def history_seconds(interval_s: float) -> float:
    """How far back the caller must read scored readings: the clear window and a raise window at the stated interval."""
    interval_s = max(float(interval_s or 0), 1.0)
    return clear_window_s(interval_s) + raise_window_s(interval_s)


def observed_interval(points, interval_s: float) -> float:
    """The interval the newest readings show: the median gap, within INTERVAL_BOUNDS of the stated interval."""
    stated = max(float(interval_s or 0), 1.0)
    recent = points[-(INTERVAL_GAPS + 1):]
    gaps = [(recent[i][0] - recent[i - 1][0]).total_seconds() for i in range(1, len(recent))]
    gaps = [g for g in gaps if g > 0]
    if len(gaps) < INTERVAL_MIN_GAPS:
        return stated
    seen = statistics.median(gaps)
    lo, hi = stated * INTERVAL_BOUNDS[0], stated * INTERVAL_BOUNDS[1]
    return float(min(max(seen, lo, 1.0), hi, 86_400.0))


def _recent_points(points, anchor: datetime, window_s: float, interval_s: float) -> list[int]:
    """
    The indexes of the points in the window_s seconds up to anchor (the newest reading) since the last gap.

    Walks back from the newest reading and stops at the first gap longer than gap_limit_s or at the window edge.
    """
    limit = gap_limit_s(interval_s)
    found: list[int] = []
    later = anchor
    for i in range(len(points) - 1, -1, -1):
        when = points[i][0]
        if (anchor - when).total_seconds() > window_s:
            break
        if (later - when).total_seconds() > limit:
            break
        found.append(i)
        later = when
    found.reverse()
    return found


def raise_min_window_s(interval_s: float) -> float:
    return min(max(RAISE_MIN_SECONDS, RAISE_MIN_INTERVALS * interval_s), raise_window_s(interval_s))


def level_for_window(window_s: float, interval_s: float) -> float:
    """The median score a window of this length must reach: the boundary at the full window and critical at the shortest."""
    full, short = raise_window_s(interval_s), raise_min_window_s(interval_s)
    if full <= short:
        return BOUNDARY
    share = min(max((full - window_s) / (full - short), 0.0), 1.0)
    return BOUNDARY + (CRITICAL_SCORE - BOUNDARY) * share


def min_points_for_window(window_s: float, interval_s: float) -> int:
    full = raise_window_s(interval_s)
    return max(MIN_SHORT_POINTS, math.ceil(MIN_RAISE_POINTS * window_s / full)) if window_s < full else MIN_RAISE_POINTS


def _sustained(scores: list[float], window_s: float, interval_s: float) -> tuple[bool, float | None]:
    if len(scores) < min_points_for_window(window_s, interval_s) or not scores:
        return False, None
    over = sum(score >= BOUNDARY for score in scores)
    median = statistics.median(scores)
    ok = over * RAISE_SHARE_DENOMINATOR >= len(scores) * RAISE_SHARE_NUMERATOR and median >= level_for_window(window_s, interval_s)
    return ok, median


def _sensor_words(name: str) -> str:
    return {"current_ma": "current", "power_mw": "power", "bus_voltage": "supply voltage", "ir_temperature": "surface temperature",
            "contact_temp": "contact temperature"}.get(name, name.replace("_", " "))


# the unit a sensor's offset is stated in, so "about 2.4" is never read without one
_UNITS = {"temperature": " °C", "ir_temperature": " °C", "contact_temp": " °C", "humidity": " %RH", "pressure": " hPa",
          "current_ma": " mA", "power_mw": " mW", "bus_voltage": " V", "sound_level": " dB", "light_level": " lux",
          "shaft_rpm": " rpm", "fft_peak_hz": " Hz", "distance_mm": " mm"}


def _amount(sensor: str, value: float) -> str:
    """An approximate amount in words: two significant figures at most, with the sensor's unit when known."""
    size = abs(value)
    text = f"{size:.1f}" if size >= 1 else f"{size:.2g}"
    return text + _UNITS.get(sensor, "")


def decide(
    points: list[tuple[datetime, float]],
    open_alert_since: datetime | None,
    last_resolved_at: datetime | None,
    now: datetime,
    interval_s: float,
    details: list | None = None,
) -> Decision:
    """
    Decide what to do about one machine's anomaly alert.

    points            (time, normalised score) of the machine's scored readings, oldest first and newest last. Only
                      scored readings are passed: an unscored reading is not evidence either way and must be left
                      out by the caller. Scores are on the public 0-1 scale where 0.7 is the model's boundary. The
                      list needs to reach back at least history_seconds(interval_s) seconds.
    open_alert_since  when the machine's open anomaly alert was raised and None when none is open. An open alert is
                      taken to be a warning, so a critical window answers "escalate". The caller ignores that when
                      the alert is already critical.
    last_resolved_at  when the machine's last anomaly alert resolved and None when there was none. It sets the re-arm delay.
    now               the time of the evaluation, timezone aware and in the same zone as the points. It is used only to
                      tell whether the machine has gone quiet and for the re-arm delay: the windows end at the newest point.
    interval_s        the machine's stated posting interval in seconds. A value under 1 is taken as 1. The interval used
                      is the one the readings show (observed_interval).
    details           optional and parallel to points: for each point None or a dict naming the sensor that made the score
                      high: {"sensor", "value", "direction" ("above" or "below"), "low", "high"} for a value outside its
                      range or {"kind": "drift", "sensor", "value", "expected", "offset", "direction", "minutes"} for a
                      change that built up over time. When given, the reason names the sensor most often over the boundary
                      in the window and the evidence carries the sensor and its latest value and usual range.

    Returns a Decision. The caller acts on it: raise opens one alert and sends one notification, escalate updates
    the open alert and sends one notification, resolve closes it and none does nothing.
    """
    if not points:
        return NONE
    interval_s = observed_interval(points, interval_s)
    anchor = points[-1][0]
    quiet = (now - anchor).total_seconds() > live_limit_s(interval_s)
    full = raise_window_s(interval_s)
    short = raise_min_window_s(interval_s)
    in_full = [] if quiet else _recent_points(points, anchor, full, interval_s)
    scores_full = [points[i][1] for i in in_full]
    # the longest window that is sustained wins: the full one first and then shorter ones that need a higher median
    lengths = [full] + [full - (full - short) * k / WINDOW_STEPS for k in range(1, WINDOW_STEPS + 1)] if short < full else [full]
    chosen = None
    for length in lengths:
        indexes = [i for i in in_full if (anchor - points[i][0]).total_seconds() <= length]
        scores = [points[i][1] for i in indexes]
        ok, median = _sustained(scores, length, interval_s)
        if ok:
            chosen = (length, indexes, scores, median)
            break
    sustained = chosen is not None
    if sustained:
        window_s, indexes, scores, median = chosen
    else:
        window_s, indexes, scores = full, in_full, scores_full
        median = statistics.median(scores_full) if scores_full else None
    critical = sustained and median >= CRITICAL_SCORE
    over = sum(score >= BOUNDARY for score in scores)
    evidence = {
        "readings": len(scores), "over_boundary": over, "median": None if median is None else round(median, 4),
        "window_s": round(window_s, 1), "interval_s": round(interval_s, 1),
    }
    reason = ""
    if sustained:
        found = Counter()
        latest = {}
        for i in indexes:
            note = details[i] if details is not None and i < len(details) else None
            if note and points[i][1] >= BOUNDARY:
                found[note["sensor"]] += 1
                latest[note["sensor"]] = note
        reason = (
            f"{over} of {len(scores)} scored readings in the last {window_s:.0f} s were at or over the anomaly limit "
            f"of {BOUNDARY:.2f} (median {median:.2f})"
        )
        if found:
            sensor = found.most_common(1)[0][0]
            note = latest[sensor]
            words = _sensor_words(sensor)
            if note.get("rise_above"):
                # the model judges this sensor as its rise above the air temperature and the value is that rise
                words = f"{words} rise above the {_sensor_words(note['rise_above'])}"
            if note.get("kind") == "drift":
                # the change detector: a sensor that has moved away from what it should read for this load. The offset is
                # the average over the run and approximate and the minutes are when the accumulator last left zero
                delta = note.get("offset")
                if delta is None:
                    delta = abs(note["value"] - note["expected"])
                reason = (f"{words} has run roughly {_amount(sensor, delta)} {note['direction']} what this "
                          f"machine normally shows for this load, on average over about the last {note['minutes']} minutes. "
                          + reason)
                evidence.update(sensor=sensor, expected=note["expected"], value=note["value"], minutes=note["minutes"],
                                direction=note["direction"], offset=round(float(delta), 4))
            elif note.get("kind") == "combination":
                # the forest carried the score: no single sensor is out of its range, the combination is unusual
                reason = (f"the combination of readings is unusual for this machine; the sensor furthest from its usual value "
                          f"is {words} ({note['direction']} its middle). " + reason)
                evidence.update(sensor=sensor, value=note["value"], range=[note["low"], note["high"]], direction=note["direction"],
                                combination=True)
            else:
                how = "well " if critical else ""
                reason = (f"{words} is {how}{note['direction']} this machine's usual range. " + reason)
                evidence.update(sensor=sensor, value=note["value"], range=[note["low"], note["high"]], direction=note["direction"])

    if open_alert_since is not None:
        if critical:
            return Decision("escalate", "critical", reason, evidence)
        # the clear window is plain time back from the newest reading: a silence does not hide an anomalous reading that
        # is still inside it, so a gap resets the raise window and not this one. It is long, so a fault that comes and
        # goes keeps its one alert
        clear_s = clear_window_s(interval_s)
        calm = [score for when, score in points if 0 <= (anchor - when).total_seconds() <= clear_s]
        newest = [score for when, score in points if 0 <= (anchor - when).total_seconds() <= short]
        if (not quiet and len(calm) >= MIN_CLEAR_POINTS and statistics.median(calm) < CLEAR_LEVEL
                and sum(score >= BOUNDARY for score in calm) <= CALM_MAX_SHARE * len(calm)
                and not any(score >= BOUNDARY for score in newest)):
            return Decision(
                "resolve", None,
                f"the median of the last {len(calm)} scored readings ({clear_s / 60:.0f} minutes) is "
                f"{statistics.median(calm):.2f} and at most one in twenty is at or over the anomaly limit",
                {"readings": len(calm), "median": round(statistics.median(calm), 4), "window_s": clear_s},
            )
        age = (now - open_alert_since).total_seconds()
        if (not quiet and age >= MAX_OPEN_SECONDS and len(calm) >= MIN_CLEAR_POINTS
                and not any(score >= BOUNDARY for score in calm)):
            # the hysteresis band: scores just under the limit but not calm. The alert is closed so it does not stay open for
            # ever and its reason says why, so a person looks at the machine
            return Decision(
                "resolve", None,
                f"the alert has been open for {age / 3600:.0f} hours and no reading in the last {clear_s / 60:.0f} minutes "
                f"reached the anomaly limit, but the scores have stayed just under it (median {statistics.median(calm):.2f}, "
                f"between {CLEAR_LEVEL:.2f} and {BOUNDARY:.2f}). It is closed so it does not stay open for ever: check the "
                "machine, as it has not gone back to its usual readings",
                {"readings": len(calm), "median": round(statistics.median(calm), 4), "window_s": clear_s,
                 "open_hours": round(age / 3600, 1), "hysteresis": True},
            )
        return NONE

    if not sustained:
        return NONE
    if last_resolved_at is not None:
        waited = (now - last_resolved_at).total_seconds()
        hold = CRITICAL_REARM_SECONDS if critical else REARM_SECONDS
        if waited < hold:
            return Decision("none", None, "", {**evidence, "rearm_wait_s": round(hold - waited, 1)})
    return Decision("raise", "critical" if critical else "warning", reason, evidence)
