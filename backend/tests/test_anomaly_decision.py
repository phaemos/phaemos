"""
The anomaly alert decision (services/anomaly_decision.py) at every edge of its rules. The function is pure, so these
tests need no database: scores and times go in and a Decision comes out.
"""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.services import anomaly_decision as ad
from app.services.anomaly_decision import decide

NOW = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)


def series(scores, interval=5.0, end=NOW):
    """(time, score) points ending at `end`, one per interval, oldest first."""
    n = len(scores)
    return [(end - timedelta(seconds=interval * (n - 1 - i)), s) for i, s in enumerate(scores)]


def run(scores, interval=5.0, open_since=None, resolved=None):
    return decide(series(scores, interval), open_since, resolved, NOW, interval)


# -- raising ------------------------------------------------------------------------------------------------------

def test_exactly_80_per_cent_over_the_boundary_raises():
    # 16 of 20 is exactly four in five
    d = run([0.8] * 16 + [0.1] * 4)
    assert d.action == "raise" and d.severity == "warning"
    assert d.evidence["over_boundary"] == 16 and d.evidence["readings"] == 20


def test_just_under_80_per_cent_does_not_raise():
    # 15 of 20 is 75 per cent
    assert run([0.9] * 15 + [0.1] * 5).action == "none"


def test_a_score_exactly_on_the_boundary_counts_as_over():
    assert run([ad.BOUNDARY] * 20).action == "raise"


def test_a_score_just_under_the_boundary_does_not():
    assert run([ad.BOUNDARY - 0.001] * 20).action == "none"


def test_twelve_scored_readings_are_the_least_that_count_at_the_boundary():
    assert run([ad.BOUNDARY] * 11).action == "none"
    assert run([ad.BOUNDARY] * 12).action == "raise"


def test_a_clear_excursion_raises_on_a_shorter_window_and_never_on_fewer_than_six_readings():
    # six readings (a minute at 5 s) are the least. They raise through a window shorter than the full 120 s
    assert run([0.95] * 5).action == "none"
    d = run([0.95] * 6)
    assert d.action == "raise" and d.severity == "critical" and d.evidence["window_s"] < 120.0
    # the shorter the window the higher the median it needs: 0.75 needs a window of about 100 s and 11 readings
    assert run([0.75] * 10).action == "none"
    assert run([0.75] * 11).action == "raise"


def test_the_window_lengthens_as_the_median_falls_to_the_boundary():
    assert ad.level_for_window(120.0, 5.0) == ad.BOUNDARY
    assert ad.level_for_window(60.0, 5.0) == ad.CRITICAL_SCORE
    assert ad.level_for_window(75.0, 5.0) == pytest.approx(0.8125)
    assert ad.min_points_for_window(120.0, 5.0) == 12 and ad.min_points_for_window(60.0, 5.0) == 6


def test_the_reason_names_the_sensor_and_the_evidence_carries_its_range():
    note = {"sensor": "current_ma", "value": 1800.0, "direction": "above", "low": 120.0, "high": 480.0}
    d = decide(series([0.95] * 12), None, None, NOW, 5.0, details=[note] * 12)
    assert d.reason.startswith("current is well above this machine's usual range.")
    assert d.evidence["sensor"] == "current_ma" and d.evidence["value"] == 1800.0 and d.evidence["range"] == [120.0, 480.0]
    d = decide(series([0.75] * 24), None, None, NOW, 5.0, details=[{**note, "direction": "below"}] * 24)
    assert d.reason.startswith("current is below this machine's usual range.")


def test_the_window_is_two_minutes_at_a_fast_interval():
    # 40 readings at 5 s span 195 s. Only the newest 25 (120 s) are the window: the 15 old anomalous ones do not count
    assert run([0.9] * 15 + [0.1] * 25).action == "none"
    # the same pattern at a 30 s interval has a 720 s window, which holds all 40 readings and 15 of 40 is too few
    assert decide(series([0.9] * 15 + [0.1] * 25, 30.0), None, None, NOW, 30.0).action == "none"
    # 20 of 24 readings over the boundary inside that window is four in five and it raises
    assert decide(series([0.9] * 20 + [0.1] * 4, 30.0), None, None, NOW, 30.0).action == "raise"


def test_the_window_is_24_intervals_at_a_slow_interval():
    # at 30 s the window is 720 s. 24 readings fit in it
    d = run([0.9] * 24, interval=30.0)
    assert d.action == "raise" and d.evidence["window_s"] == 720.0


def test_a_short_harmless_excursion_does_not_raise():
    # 15 s of anomalous readings in an otherwise normal two minutes: the case the old rule alerted on
    d = run([0.1] * 21 + [0.95] * 3)
    assert d.action == "none"


def test_a_gap_longer_than_the_gap_limit_resets_the_window():
    # the limit is the larger of 30 s and three intervals. At 5 s a 40 s silence (the old run ends 60 s ago and the new
    # one starts 20 s ago) splits the runs
    old = series([0.75] * 20, end=NOW - timedelta(seconds=60))
    new = series([0.75] * 5)
    assert decide(old + new, None, None, NOW, 5.0).action == "none"


def test_a_gap_of_exactly_the_limit_does_not_reset_it():
    new = series([0.75] * 5)
    first = new[0][0]
    old = series([0.75] * 20, end=first - timedelta(seconds=ad.GAP_MIN_SECONDS))
    assert decide(old + new, None, None, NOW, 5.0).action == "raise"
    old = series([0.75] * 20, end=first - timedelta(seconds=ad.GAP_MIN_SECONDS + 1))
    assert decide(old + new, None, None, NOW, 5.0).action == "none"


def test_delivery_jitter_on_a_fast_node_is_not_a_silence():
    # a 5 s node with every fourth post 16 s late: the review found it never raised
    gaps = [5.0, 5.0, 5.0, 16.0] * 10
    times = [NOW - timedelta(seconds=sum(gaps[i:])) for i in range(len(gaps))] + [NOW]
    assert decide([(t, 0.95) for t in times], None, None, NOW, 5.0).action == "raise"


@pytest.mark.parametrize("late", [0, 10, 16, 25, 30])
def test_readings_that_arrive_late_but_still_live_raise(late):
    # telemetry treats a reading up to 30 s old as live, so the decision must too: the windows end at the newest reading
    pts = series([0.97] * 60, end=NOW - timedelta(seconds=late))
    d = decide(pts, None, None, NOW, 5.0)
    assert d.action == "raise"
    # the window is the 120 s up to the newest reading, whatever its delay: all 25 readings at 5 s, never fewer
    assert d.evidence["readings"] == 25


def test_a_machine_gone_quiet_past_the_live_limit_gives_no_alert():
    pts = series([0.9] * 30, end=NOW - timedelta(seconds=ad.live_limit_s(5.0) + 1))
    assert decide(pts, None, None, NOW, 5.0).action == "none"


def test_a_node_posting_six_times_slower_than_its_record_still_raises():
    # the record says 5 s and the node posts every 30 s: the windows follow the interval the readings show
    pts = series([0.95] * 30, interval=30.0)
    d = decide(pts, None, None, NOW, 5.0)
    assert d.action == "raise" and d.evidence["interval_s"] == pytest.approx(30.0)


def test_the_observed_interval_is_bounded_by_the_stated_one():
    pts = series([0.1] * 30, interval=3600.0)
    assert ad.observed_interval(pts, 5.0) == pytest.approx(5.0 * ad.INTERVAL_BOUNDS[1])
    assert ad.observed_interval(series([0.1] * 3, interval=30.0), 5.0) == 5.0


def test_an_empty_list_is_none():
    assert decide([], None, None, NOW, 5.0).action == "none"


def test_an_interval_under_one_second_is_taken_as_one():
    pts = series([0.9] * 130, interval=1.0)
    assert decide(pts, None, None, NOW, 0.0).action == "raise"


# -- severity ----------------------------------------------------------------------------------------------------

def test_median_at_the_critical_score_is_critical():
    d = run([ad.CRITICAL_SCORE] * 20)
    assert d.action == "raise" and d.severity == "critical"


def test_median_just_under_the_critical_score_is_a_warning():
    d = run([ad.CRITICAL_SCORE - 0.001] * 20)
    assert d.action == "raise" and d.severity == "warning"


def test_an_open_warning_escalates_when_the_window_turns_critical():
    d = run([0.95] * 20, open_since=NOW - timedelta(minutes=10))
    assert d.action == "escalate" and d.severity == "critical"


def test_an_open_alert_is_not_raised_again_by_a_warning_window():
    assert run([0.8] * 20, open_since=NOW - timedelta(minutes=10)).action == "none"


# -- resolving ---------------------------------------------------------------------------------------------------

def _calm(n=None, interval=5.0):
    n = n or int(ad.clear_window_s(interval) / interval) + 1
    return [0.1] * n


def test_an_open_alert_resolves_only_after_a_long_calm():
    d = run(_calm(), open_since=NOW - timedelta(hours=1))
    assert d.action == "resolve" and d.severity is None
    # five minutes of calm is not enough any more: an intermittent fault would reopen it
    assert run([0.9] * 100 + [0.1] * 60, open_since=NOW - timedelta(hours=1)).action == "none"


def test_a_reading_at_the_boundary_in_the_newest_minute_keeps_it_open():
    d = run(_calm()[:-1] + [ad.BOUNDARY], open_since=NOW - timedelta(hours=1))
    assert d.action == "none"


def test_a_few_stray_readings_over_the_boundary_in_a_long_calm_do_not_hold_it_open():
    calm = _calm()
    for i in range(0, 300, 60):
        calm[i] = 0.75
    assert run(calm, open_since=NOW - timedelta(hours=1)).action == "resolve"


def test_a_median_exactly_at_the_clear_level_keeps_it_open():
    assert run([ad.CLEAR_LEVEL] * len(_calm()), open_since=NOW - timedelta(hours=1)).action == "none"


def test_a_median_just_under_the_clear_level_resolves():
    assert run([ad.CLEAR_LEVEL - 0.001] * len(_calm()), open_since=NOW - timedelta(hours=1)).action == "resolve"


def test_a_score_hovering_between_the_levels_neither_raises_nor_resolves():
    # 0.6 is under the boundary and over the clear level: the alert stays as it is, which is the hysteresis
    assert run([0.6] * len(_calm()), open_since=NOW - timedelta(hours=1)).action == "none"
    assert run([0.6] * 60).action == "none"


def test_resolving_needs_twelve_scored_readings():
    assert run([0.1] * 11, open_since=NOW - timedelta(hours=1)).action == "none"


def test_an_intermittent_fault_keeps_one_alert_open_and_does_not_flap():
    import numpy as np
    from app.services import model_evaluation as ev
    # ten minutes at 0.9 then ten minutes calm, for four hours: the review counted 12 raises
    scores = ([0.9] * 120 + [0.1] * 120) * 12
    result = ev.replay(np.arange(len(scores)) * 5.0 + 1.7e9, np.array(scores), 5.0, gated=False)
    assert len(result.raises) == 1
    # a fault seen only while the machine runs, with eight minute stoppages, for eight hours: the review counted 8
    scores = ([0.9] * 600 + [0.1] * 96) * 8
    assert len(ev.replay(np.arange(len(scores)) * 5.0 + 1.7e9, np.array(scores), 5.0, gated=False).raises) == 1


def test_a_gap_does_not_hide_an_anomalous_reading_inside_the_clear_window():
    clear = ad.clear_window_s(5.0)
    old = series([0.9] * 24, end=NOW - timedelta(seconds=clear - 100))
    new = series([0.1] * 24)
    assert decide(old + new, NOW - timedelta(hours=1), None, NOW, 5.0).action == "none"


# -- the re-arm delay --------------------------------------------------------------------------------------------

def test_a_warning_is_held_back_for_15_minutes_after_a_resolve():
    d = run([0.8] * 20, resolved=NOW - timedelta(minutes=5))
    assert d.action == "none"
    assert d.evidence["rearm_wait_s"] == pytest.approx(600.0)


def test_a_critical_window_is_held_back_for_its_shorter_re_arm():
    d = run([0.95] * 20, resolved=NOW - timedelta(seconds=30))
    assert d.action == "none" and d.evidence["rearm_wait_s"] == pytest.approx(ad.CRITICAL_REARM_SECONDS - 30)
    d = run([0.95] * 20, resolved=NOW - timedelta(seconds=ad.CRITICAL_REARM_SECONDS))
    assert d.action == "raise" and d.severity == "critical"


def test_exactly_15_minutes_after_the_resolve_it_may_raise():
    assert run([0.8] * 20, resolved=NOW - timedelta(seconds=ad.REARM_SECONDS)).action == "raise"
    assert run([0.8] * 20, resolved=NOW - timedelta(seconds=ad.REARM_SECONDS - 1)).action == "none"


def test_a_resolve_long_ago_does_not_hold_back():
    assert run([0.8] * 20, resolved=NOW - timedelta(days=2)).action == "raise"


# -- the result --------------------------------------------------------------------------------------------------

def test_the_decision_is_frozen_and_carries_a_plain_reason():
    d = run([0.9] * 20)
    with pytest.raises(FrozenInstanceError):
        d.action = "none"
    assert d.reason.startswith("20 of 20 scored readings in the last 120 s")
    assert "median 0.90" in d.reason
    assert "\u2014" not in d.reason and "\u2013" not in d.reason


def test_none_has_no_severity_and_no_reason():
    d = run([0.1] * 20)
    assert (d.action, d.severity, d.reason) == ("none", None, "")


def test_the_windows_follow_the_constants():
    assert ad.raise_window_s(5.0) == 120.0 and ad.raise_window_s(10.0) == 240.0
    assert ad.clear_window_s(5.0) == 1800.0 and ad.clear_window_s(60.0) == 7200.0
    assert ad.history_seconds(5.0) == 1920.0


def test_a_drift_note_is_put_in_plain_words_with_the_average_offset_and_the_time():
    note = {"kind": "drift", "sensor": "temperature", "value": 28.1, "expected": 24.0, "offset": 3.62, "direction": "above",
            "minutes": 20}
    d = decide(series([0.9] * 24), None, None, NOW, 5.0, details=[note] * 24)
    assert d.reason.startswith("temperature has run roughly 3.6 °C above what this machine normally shows for this load, "
                               "on average over about the last 20 minutes.")
    assert d.evidence["sensor"] == "temperature" and d.evidence["expected"] == 24.0 and d.evidence["offset"] == 3.62
    assert d.evidence["minutes"] == 20 and "range" not in d.evidence


def test_a_forest_note_names_the_sensor_furthest_from_its_range():
    note = {"kind": "combination", "sensor": "humidity", "value": 40.0, "direction": "below", "low": 41.0, "high": 60.0}
    d = decide(series([0.9] * 24), None, None, NOW, 5.0, details=[note] * 24)
    assert d.reason.startswith("the combination of readings is unusual for this machine; the sensor furthest from its usual "
                               "value is humidity")


def test_a_rise_above_the_air_is_named_as_a_rise():
    note = {"kind": "drift", "sensor": "contact_temp", "rise_above": "temperature", "value": 12.0, "expected": 9.0,
            "offset": 3.0, "direction": "above", "minutes": 15}
    d = decide(series([0.9] * 24), None, None, NOW, 5.0, details=[note] * 24)
    assert d.reason.startswith("contact temperature rise above the temperature has run roughly 3.0 °C above")


def test_an_alert_held_open_by_scores_just_under_the_limit_is_closed_after_a_day_with_a_note():
    hovering = [0.6] * (int(ad.clear_window_s(5.0) / 5.0) + 1)
    assert run(hovering, open_since=NOW - timedelta(hours=23)).action == "none"
    d = run(hovering, open_since=NOW - timedelta(seconds=ad.MAX_OPEN_SECONDS))
    assert d.action == "resolve" and "check the machine" in d.reason and d.evidence["hysteresis"] is True
    # a reading at the limit in the window keeps it open whatever its age
    assert run(hovering[:-1] + [ad.BOUNDARY], open_since=NOW - timedelta(days=3)).action == "none"
