"""
The replay of the contract's section 6: the same simulated healthy week through the OLD alert rule and the NEW model
and decision. Then the labelled faults. The full evaluation (`make ml-eval`) runs more machines and seeds. This test runs
two machines on a seed that no setting was ever chosen on (not the builder's seed and not a validation seed), so it
says something about seeds the tuning never saw. Everything is seeded, so the numbers are the same on every run.
"""
import numpy as np
import pytest

from app.scripts import evaluate_model as ev_script
from app.services import model_evaluation as ev

# a 5 s machine and a 10 s machine of the same node type: two intervals and one node type model to fall back on
FLEET = [
    ev_script.Spec("press-a", "esp32", 5, ev_script.ESP),
    ev_script.Spec("press-b", "esp32", 10, ev_script.ESP),
]


# a seed outside the builder's seed, the validation seeds and the reported test seeds
SEED = 4242


@pytest.fixture(scope="module")
def result():
    assert SEED != ev_script.SEED and SEED not in ev_script.VALIDATION_SEEDS and SEED not in ev_script.TEST_SEEDS
    return ev_script.evaluate(FLEET, seed=SEED)


def test_the_new_model_stays_inside_the_budget_on_a_healthy_week(result):
    news = [row["new"] for row in result["rows"]]
    assert all(value is not None for value in news), "a machine has no accepted model"
    # the budget is one false alert per machine per week. On a seed no setting was chosen on, the mean over the machines
    # must be inside it. One machine-week is one draw of a count whose mean is at most one, so two in it is not a breach
    # (a Poisson count of mean one is two or more about a quarter of the time) and three would be (one time in twelve)
    assert sum(news) / len(news) <= ev.BUDGET_PER_WEEK
    assert max(news) <= 2.0


def test_the_old_rule_raised_far_more_false_alerts_on_the_same_week(result):
    for row in result["rows"]:
        # the improvement is a number: the old rule's count beside the new one's
        assert row["old_deployed"] >= 50 * max(row["new"], 1.0)
        assert row["old_good"] >= 20 * max(row["new"], 1.0)


def test_the_labelled_faults_are_caught_by_the_new_model_within_their_deadlines(result):
    faults = result["faults"]
    for kind in ("temperature_step", "slow_drift", "vibration_rise", "current_spike"):
        trials, caught, delays = faults[kind]["new"]
        # caught means raised within the stated deadline of the onset and the delays prove it
        assert trials >= 10 and caught >= trials - 1, kind
        assert delays and max(delays) <= ev.FAULTS[kind]["deadline_s"] and min(delays) >= 0
    # a value that stops moving is a sensor fault. The sensor health check handles it, so it is not injected here
    assert ev.FAULTS["stuck_value"]["handled"] and faults["stuck_value"]["new"][0] == 0


def test_the_report_prints_both_tables_and_says_the_data_is_simulated(result):
    text = ev_script.report(result)
    assert "SIMULATED data. No real machine data has been used." in text
    assert "Table 1." in text and "Table 2." in text and "handled by the sensor health check" in text
    assert "\u2014" not in text and "\u2013" not in text


# -- the old rule, copied from before this change -----------------------------------------------------------------

def _old(scores, interval=5.0):
    t = np.arange(len(scores)) * interval
    return ev_script.old_replay(t, np.array(scores, dtype=float), interval).raises


def test_the_old_rule_alerts_on_three_anomalous_readings_in_a_row():
    assert len(_old([0.1, 0.9, 0.9, 0.9, 0.1])) == 1
    assert _old([0.1, 0.9, 0.9, 0.1, 0.9, 0.9, 0.1]) == []


def test_the_old_rule_needs_three_normal_readings_to_clear_before_it_alerts_again():
    scores = [0.9] * 3 + [0.1] * 3 + [0.9] * 3
    assert len(_old(scores)) == 2
    assert len(_old([0.9] * 3 + [0.1, 0.9, 0.1] + [0.9] * 3)) == 1


def test_the_old_rule_ignores_readings_more_than_a_window_apart():
    t = np.array([0.0, 40.0, 80.0])
    assert ev_script.old_replay(t, np.array([0.9, 0.9, 0.9]), 5.0).raises == []


def test_the_gate_in_the_replay_changes_no_result():
    rng = np.random.default_rng(5)
    times = np.arange(4000) * 5.0
    scores = np.clip(rng.normal(0.3, 0.25, 4000), 0, 1)
    scores[1000:1300] = 0.95
    scores[2500:2530] = 0.9
    a, b = ev.replay(times, scores, 5.0, gated=True), ev.replay(times, scores, 5.0, gated=False)
    assert a.raises == b.raises and a.escalations == b.escalations and a.resolves == b.resolves
    assert len(a.raises) >= 1


# -- the seed split ------------------------------------------------------------------------------------------------------

def test_the_seed_split_lives_in_one_manifest_and_the_tuning_never_reads_a_test_seed():
    manifest = ev_script.seed_manifest()
    assert not set(manifest["validation"]) & set(manifest["test"])
    assert ev_script.VALIDATION_SEEDS == tuple(manifest["validation"]) and ev_script.TEST_SEEDS == tuple(manifest["test"])
    with pytest.raises(ValueError, match="test seed"):
        ev_script.tune([manifest["test"][0]], [{"k": 2, "tau_h": 2, "bound": 4}])
    # the replay test's own seed is neither
    assert SEED not in manifest["validation"] and SEED not in manifest["test"]


def test_the_interval_respects_the_grouping_by_machine():
    # ten machines: one raised all the alerts. Counted as independent weeks the interval would be narrow. Resampling the
    # machines whole shows how little ten machine-weeks say
    units = [(10, 1.0)] + [(0, 1.0)] * 9
    lo, hi = ev_script.cluster_interval(units)
    assert lo == 0.0 and hi >= 2.0
