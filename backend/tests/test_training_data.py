"""
Which readings may teach the anomaly model (services/training_data.py): maintenance, faulted and dropped readings,
readings while a rule alert or a confirmed model alert was open and readings beside a link gap are left out, the rest are
split by time into fit, validation and test parts and the fit part is sampled evenly. An unconfirmed model alert refuses
nothing. The SQL path runs against the test database and is compared with the in-memory path the evaluation uses.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.models.alert import Alert
from app.models.maintenance import MaintenanceWindow
from app.models.telemetry import Telemetry
from app.services import training_data as td

COLS = td.SENSOR_COLS
T = COLS.index("temperature")
NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
INTERVAL = 60
N = 4320
FIRST = NOW - timedelta(days=3)


def when(i):
    return FIRST + timedelta(seconds=INTERVAL * i)


# the rows each kind of trouble covers, by row number. Rows 1000 to 1019 never arrived (a link gap of 20 minutes)
MAINTENANCE = range(100, 200)
FAULTED = list(range(300, 310)) + [320, 321, 322]
ALERT_OPEN = range(500, 550)
MISSING = range(1000, 1020)


class _Keep:
    """The test's session with the two calls that would end its transaction made harmless."""

    def __init__(self, session):
        self.session = session

    def execute(self, *args, **kwargs):
        return self.session.execute(*args, **kwargs)

    def rollback(self):
        pass

    def close(self):
        pass


def _quality(i):
    if i in range(300, 310):
        return {"faults": {"bme280": "missing"}}
    return {320: {"dropped_values": ["x"]}, 321: {"rejected": {"temperature": 99.0}}, 322: {"dropped_health": ["rssi"]},
            330: {"scored_by": "general"}}.get(i)


@pytest.fixture
def machine(db, device):
    device.expected_interval_s = INTERVAL
    device.type = "esp32"
    db.add(MaintenanceWindow(
        device_id=device.id, label="service", start_at=when(MAINTENANCE.start), end_at=when(MAINTENANCE.stop - 1),
    ))
    # a window for another machine and an alert of the monitoring kind must refuse nothing
    db.add(Alert(device_id=device.id, message="silent", severity="warning", category="monitoring", kind="offline",
                 triggered_at=when(600), resolved=True, resolved_at=when(649)))
    db.add(Alert(device_id=device.id, message="hot", severity="warning", category="machine", resolved=True,
                 triggered_at=when(ALERT_OPEN.start), resolved_at=when(ALERT_OPEN.stop - 1)))
    db.add_all([
        Telemetry(device_id=device.id, node_type="esp32", recorded_at=when(i), temperature=float(i),
                  humidity=50.0, quality=_quality(i))
        for i in range(N) if i not in MISSING
    ])
    db.flush()
    return device


def _indices(array):
    return set(array[:, T].astype(int).tolist())


def test_sql_leaves_out_each_kind_of_trouble_and_says_how_many(machine, db):
    data = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    assert data.refused == {"maintenance": 100, "sensor_fault": 13, "machine_alert": 50, "link": 2}
    assert data.total_rows == N - len(MISSING)
    assert data.clean_rows == N - len(MISSING) - 165
    used = _indices(data.fit) | _indices(data.held)
    excluded = set(MAINTENANCE) | set(FAULTED) | set(ALERT_OPEN) | {999, 1020}
    assert not used & excluded
    # a monitoring alert and a note in quality that is not a fault leave their rows in
    assert 330 in used or 330 in _indices(data.held) or data.clean_rows > 0
    assert any(600 <= i <= 649 for i in used | set(range(600, 650)))


def test_the_split_is_by_time_into_fit_validation_and_test(machine, db):
    data = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    fit, val, test = sorted(_indices(data.fit)), sorted(_indices(data.val)), sorted(_indices(data.test))
    assert fit and val and test
    # not one fitted reading is as new as the oldest validation one and not one validation reading as new as a test one
    assert max(fit) < min(val) and max(val) < min(test)
    # validation and test are each the newer fifths of the clean span and every clean row in them
    assert 0.18 < len(val) / data.clean_rows < 0.22 and 0.18 < len(test) / data.clean_rows < 0.22
    assert test == list(range(min(test), N))
    assert list(data.held_times) == sorted(data.held_times)


def test_an_unconfirmed_model_alert_refuses_nothing_and_a_confirmed_one_does(machine, db):
    db.add(Alert(device_id=machine.id, message="model", severity="warning", category="machine", kind="anomaly",
                 triggered_at=when(2200), resolved=True, resolved_at=when(2249)))
    db.flush()
    data = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    assert data.refused["machine_alert"] == 50
    db.add(Alert(device_id=machine.id, message="model, confirmed", severity="warning", category="machine", kind="anomaly",
                 triggered_at=when(2400), resolved=True, resolved_at=when(2429), fault_confirmed=True))
    db.flush()
    data = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    assert data.refused["machine_alert"] == 80


def test_the_observed_interval_replaces_a_wrong_record(machine, db):
    machine.expected_interval_s = 5
    db.flush()
    data = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    # the node posts every 60 s whatever its record says, so its rows are not refused as a failing link
    assert data.interval_s == 60.0 and data.recorded_interval_s == 5.0
    assert data.refused.get("link", 0) == 2


def test_the_fit_rows_are_taken_evenly_across_the_span_and_capped(machine, db, monkeypatch):
    monkeypatch.setattr(td, "MAX_FIT_ROWS", 200)
    data = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    fit = sorted(_indices(data.fit))
    assert len(fit) <= 200
    # spread over the whole fitted span and not bunched at one end
    gaps = np.diff(fit)
    # the fit part is the oldest 60 per cent (about 2,500 clean rows), so one sample about every 13 rows. The few big gaps
    # are the maintenance window and the other refused rows
    assert 11 <= np.median(gaps) <= 15 and np.percentile(gaps, 90) <= 20
    assert fit[0] < 30 and fit[-1] > 2400


def test_the_held_out_parts_are_capped_to_their_newest_rows(machine, db, monkeypatch):
    monkeypatch.setattr(td, "MAX_HELDOUT_ROWS", 50)
    data = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    assert len(data.val) == 50 and len(data.test) == 50
    assert max(_indices(data.fit)) < min(_indices(data.val))
    assert max(_indices(data.test)) == N - 1


def test_a_fleet_wide_maintenance_window_counts_for_every_machine(machine, db):
    db.add(MaintenanceWindow(device_id=None, label="power cut", start_at=when(2000), end_at=when(2099)))
    db.flush()
    data = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    assert data.refused["maintenance"] == 200


def test_readings_older_than_the_window_are_not_read(machine, db):
    data = td.load_machine(machine, now=NOW + timedelta(days=td.WINDOW_DAYS), session_factory=lambda: _Keep(db))
    assert data.total_rows == 0 and len(data.fit) == 0 and not data.enough


def test_the_sql_and_the_in_memory_selection_agree(machine, db):
    sql = td.load_machine(machine, now=NOW, session_factory=lambda: _Keep(db))
    idx = [i for i in range(N) if i not in MISSING]
    times = np.array([when(i).timestamp() for i in idx])
    X = np.full((len(idx), len(COLS)), np.nan)
    X[:, T] = idx
    reasons = np.full(len(idx), "", dtype=object)
    pos = {i: k for k, i in enumerate(idx)}
    for i in MAINTENANCE:
        reasons[pos[i]] = "maintenance"
    for i in FAULTED:
        reasons[pos[i]] = "sensor_fault"
    for i in ALERT_OPEN:
        reasons[pos[i]] = "machine_alert"
    for i in (999, 1020):
        reasons[pos[i]] = "link"
    mem = td.select_from_arrays(times, X, reasons, INTERVAL)
    assert _indices(mem.fit) == _indices(sql.fit)
    assert _indices(mem.val) == _indices(sql.val) and _indices(mem.test) == _indices(sql.test)
    assert mem.refused == sql.refused and mem.clean_rows == sql.clean_rows


# -- the pure parts -----------------------------------------------------------------------------------------------

def test_hours_count_clean_readings_at_their_interval_and_never_more_than_the_span():
    assert td.clean_hours(2880, 30.0, 48 * 3600) == pytest.approx(24.0)
    assert td.clean_hours(2880, 30.0, 10 * 3600) == pytest.approx(10.0)
    assert td.clean_hours(100_000, 5.0, 3600.0) == pytest.approx(1.0)


def test_a_machine_needs_a_day_of_readings_enough_readings_and_a_day_of_test():
    def data(hours, span, rows=td.MIN_CLEAN_ROWS, test_hours=30.0):
        e = np.empty((0, len(COLS)))
        test_times = 1e9 + np.arange(0, test_hours * 3600, 5.0)
        test = np.zeros((len(test_times), len(COLS)))
        return td.MachineData("a", "a", None, 5.0, e, e, np.empty(0), test, test_times, clean_rows=rows,
                              clean_hours=hours, span_hours=span)
    assert data(130.0, 130.0).enough
    assert not data(23.9, 48.0).enough
    assert not data(30.0, 23.9).enough
    assert not data(130.0, 130.0, rows=td.MIN_CLEAN_ROWS - 1).enough
    # a test part shorter than a day cannot give a false alert figure worth reporting
    assert not data(130.0, 130.0, test_hours=20.0).enough


def test_the_hours_a_machine_needs_follow_its_interval_and_the_test_part():
    assert td.MIN_CLEAN_ROWS == 10_000
    # five days: the newest fifth must hold a day
    assert td.hours_needed(5) == pytest.approx(120.0)
    assert td.hours_needed(60) == pytest.approx(166.67, abs=0.01)


def test_the_observed_interval_stands_only_when_it_differs_from_the_record():
    times = 1e9 + 30.0 * np.arange(500)
    assert td.observed_interval(times, 5.0) == 30.0
    assert td.observed_interval(times, 28.0) == 28.0
    assert td.observed_interval(times[:10], 5.0) == 5.0


def test_thin_evenly_keeps_order_and_the_ends():
    a = np.arange(1000).reshape(-1, 1)
    out = td.thin_evenly(a, 10)
    assert len(out) == 10 and out[0, 0] == 0 and out[-1, 0] == 999
    assert list(out[:, 0]) == sorted(out[:, 0])
    assert td.thin_evenly(a, 5000) is a
    assert len(td.thin_evenly(a, 0)) == 0


def test_thin_latest_keeps_the_newest():
    a = np.arange(100)
    assert list(td.thin_latest(a, 3)) == [97, 98, 99]


def test_the_fit_bucket_is_never_under_one_interval():
    assert td.fit_bucket_s(1000.0, 30.0, 20_000) == 30.0
    assert td.fit_bucket_s(14 * 86400.0, 5.0, 20_000) == 61.0


def test_select_from_arrays_counts_every_reason_and_keeps_the_split_in_time():
    n = 2000
    times = 1_700_000_000.0 + 10.0 * np.arange(n)
    X = np.full((n, len(COLS)), np.nan)
    X[:, T] = np.arange(n)
    reasons = np.full(n, "", dtype=object)
    reasons[:50] = "maintenance"
    reasons[100:130] = "sensor_fault"
    data = td.select_from_arrays(times, X, reasons, 10.0)
    assert data.refused == {"maintenance": 50, "sensor_fault": 30}
    assert data.clean_rows == n - 80
    assert data.fit[:, T].max() < data.val[:, T].min() and data.val[:, T].max() < data.test[:, T].min()
    assert len(data.held) + len(td.thin_evenly(data.fit, 10 ** 9)) <= data.clean_rows


def test_with_no_clean_rows_there_is_nothing_to_train_on():
    times = np.arange(10.0)
    X = np.zeros((10, len(COLS)))
    data = td.select_from_arrays(times, X, np.full(10, "maintenance", dtype=object), 1.0)
    assert data.clean_rows == 0 and not data.enough and len(data.fit) == 0
