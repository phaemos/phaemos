from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import Alert
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.services import alert_service, anomaly_decision

# these run the real decision module (services/anomaly_decision.py) with real timestamps, so a test passes only when the
# readings satisfy its windows. The stubbed-decision tests of each action are in test_rule_alerts.py

STEP = 5


def _seed(db, device, end, scores, step=STEP):
    """Scored readings step seconds apart, the last one at end."""
    n = len(scores)
    for i, score in enumerate(scores):
        db.add(Telemetry(
            device_id=device.id, temperature=25.0, anomaly_score=score, is_anomaly=score >= 0.7,
            recorded_at=end - timedelta(seconds=(n - 1 - i) * step),
        ))
    db.flush()


def _post(client, device, stub_score, score):
    stub_score(score)
    res = client.post("/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 25.0}, headers={"x-api-key": device.api_key})
    assert res.status_code == 201


def _open_alerts(db, device):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).all()


@pytest.fixture(autouse=True)
def _interval(device, db):
    device.expected_interval_s = STEP
    db.flush()


def _now():
    return datetime.now(timezone.utc)


def test_a_single_anomalous_reading_raises_nothing(client, db, device, stub_score):
    _seed(db, device, _now() - timedelta(seconds=STEP), [0.1] * 24)
    _post(client, device, stub_score, 0.9)
    assert _open_alerts(db, device) == []


def test_a_short_burst_of_anomalies_raises_nothing(client, db, device, stub_score):
    # three in a row was enough once. The real decision needs most of a two minute window
    _seed(db, device, _now() - timedelta(seconds=STEP), [0.1] * 21 + [0.9, 0.95, 0.99])
    _post(client, device, stub_score, 0.95)
    assert _open_alerts(db, device) == []


def test_a_run_of_anomalies_raises_one_alert_and_one_ticket(client, db, device, stub_score):
    _seed(db, device, _now() - timedelta(seconds=STEP), [0.95] * 24)
    _post(client, device, stub_score, 0.99)
    _post(client, device, stub_score, 0.99)
    alerts = _open_alerts(db, device)
    assert len(alerts) == 1
    assert alerts[0].kind == "anomaly" and alerts[0].severity == "critical"
    tickets = db.query(Ticket).filter(Ticket.alert_id == alerts[0].id).all()
    assert len(tickets) == 1
    assert tickets[0].priority == "critical"


@pytest.mark.parametrize("score,severity", [(0.75, "warning"), (0.92, "critical")])
def test_severity_follows_the_median_of_the_window(client, db, device, stub_score, score, severity):
    _seed(db, device, _now() - timedelta(seconds=STEP), [score] * 24)
    _post(client, device, stub_score, score)
    assert _open_alerts(db, device)[0].severity == severity


def test_a_warning_turns_critical_when_the_window_does(db, device):
    t0 = _now()
    _seed(db, device, t0, [0.75] * 24)
    alert_service.evaluate_anomaly(device, db, now=t0)
    (alert,) = _open_alerts(db, device)
    assert alert.severity == "warning"
    # two minutes on the window holds only the new readings
    t1 = t0 + timedelta(seconds=130)
    _seed(db, device, t1, [0.95] * 24)
    alert_service.evaluate_anomaly(device, db, now=t1)
    db.refresh(alert)
    assert alert.severity == "critical" and alert.resolved is False
    assert len(_open_alerts(db, device)) == 1


CALM = int(anomaly_decision.clear_window_s(STEP) / STEP) + 1


def test_the_alert_clears_once_readings_are_normal_again_for_a_long_calm(db, device):
    t0 = _now()
    _seed(db, device, t0, [0.9] * 24)
    alert_service.evaluate_anomaly(device, db, now=t0)
    assert len(_open_alerts(db, device)) == 1
    # five calm minutes are not enough any more: a fault that comes and goes would reopen it
    t1 = t0 + timedelta(seconds=400)
    _seed(db, device, t1, [0.1] * 60)
    alert_service.evaluate_anomaly(device, db, now=t1)
    assert len(_open_alerts(db, device)) == 1
    # half an hour of calm does
    t2 = t0 + timedelta(seconds=anomaly_decision.CLEAR_SECONDS + 200)
    _seed(db, device, t2, [0.1] * CALM)
    alert_service.evaluate_anomaly(device, db, now=t2)
    assert _open_alerts(db, device) == []


def test_a_fault_that_goes_on_leaves_the_one_alert_open(db, device):
    t0 = _now()
    _seed(db, device, t0, [0.9] * 24)
    alert_service.evaluate_anomaly(device, db, now=t0)
    t1 = t0 + timedelta(seconds=120)
    _seed(db, device, t1, [0.9] * 24)
    alert_service.evaluate_anomaly(device, db, now=t1)
    assert len(_open_alerts(db, device)) == 1
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 1


def test_a_returning_fault_reuses_the_open_ticket(db, device):
    t0 = _now()
    _seed(db, device, t0, [0.95] * 24)
    alert_service.evaluate_anomaly(device, db, now=t0)
    t1 = t0 + timedelta(seconds=anomaly_decision.CLEAR_SECONDS + 200)
    _seed(db, device, t1, [0.1] * CALM)
    alert_service.evaluate_anomaly(device, db, now=t1)
    assert _open_alerts(db, device) == []
    # a critical window waits its shorter re-arm and then raises, on the same ticket
    t2 = t1 + timedelta(seconds=130)
    _seed(db, device, t2, [0.95] * 24)
    alert_service.evaluate_anomaly(device, db, now=t2)
    assert _open_alerts(db, device) == []
    t3 = t1 + timedelta(seconds=anomaly_decision.CRITICAL_REARM_SECONDS + 130)
    _seed(db, device, t3, [0.95] * 24)
    alert_service.evaluate_anomaly(device, db, now=t3)
    assert len(_open_alerts(db, device)) == 1
    assert db.query(Ticket).filter(Ticket.device_id == device.id).count() == 1


def test_a_warning_waits_after_a_resolve_before_it_can_raise_again(db, device):
    t0 = _now()
    _seed(db, device, t0, [0.75] * 24)
    alert_service.evaluate_anomaly(device, db, now=t0)
    t1 = t0 + timedelta(seconds=anomaly_decision.CLEAR_SECONDS + 200)
    _seed(db, device, t1, [0.1] * CALM)
    alert_service.evaluate_anomaly(device, db, now=t1)
    assert _open_alerts(db, device) == []
    t2 = t1 + timedelta(seconds=130)
    _seed(db, device, t2, [0.75] * 24)
    alert_service.evaluate_anomaly(device, db, now=t2)
    assert _open_alerts(db, device) == []
    assert anomaly_decision.REARM_SECONDS > 130


def test_the_alert_names_the_sensor_that_carried_the_score_and_the_api_returns_it(client, db, device, auth_headers, monkeypatch):
    from app.services import ml_service

    asked = []
    note = {"sensor": "temperature", "value": 41.0, "direction": "above", "low": 18.0, "high": 30.0, "deviations": 6.0}
    monkeypatch.setattr(ml_service, "explain_reading", lambda reading, device_id=None: asked.append((reading["temperature"], device_id)) or note)
    t0 = _now()
    _seed(db, device, t0, [0.95] * 24)
    alert_service.evaluate_anomaly(device, db, now=t0)
    # explained once, for the newest over-boundary reading, for this machine
    assert asked == [(25.0, device.id)]
    (alert,) = _open_alerts(db, device)
    assert alert.evidence["sensor"] == "temperature" and alert.evidence["value"] == 41.0
    assert alert.evidence["range"] == [18.0, 30.0] and alert.evidence["direction"] == "above"
    assert "above this machine's usual range" in alert.message
    listed = client.get("/api/v1/alerts", headers=auth_headers).json()
    mine = next(a for a in listed if a["id"] == str(alert.id))
    assert mine["evidence"]["sensor"] == "temperature" and mine["evidence"]["over_boundary"] >= 12


def test_calm_readings_are_not_explained(db, device, monkeypatch):
    from app.services import ml_service

    monkeypatch.setattr(ml_service, "explain_reading", lambda *a, **k: pytest.fail("nothing to explain"))
    t0 = _now()
    _seed(db, device, t0, [0.1] * 24)
    alert_service.evaluate_anomaly(device, db, now=t0)
