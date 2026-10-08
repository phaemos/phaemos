import pytest

from app.models.alert import Alert
from app.models.ticket import Ticket


def _send(client, device, monkeypatch, score):
    # the model is stubbed so each reading's score is exactly what the test needs
    monkeypatch.setattr("app.routes.telemetry.score_reading", lambda reading: (score, score >= 0.7))
    res = client.post("/api/v1/telemetry", json={"device_id": str(device.id), "temperature": 25.0}, headers={"x-api-key": device.api_key})
    assert res.status_code == 201


def _open_alerts(db, device):
    return db.query(Alert).filter(Alert.device_id == device.id, Alert.resolved.is_(False)).all()


def test_a_single_anomalous_reading_raises_nothing(client, db, device, monkeypatch):
    for score in (0.1, 0.1, 0.9):
        _send(client, device, monkeypatch, score)
    assert _open_alerts(db, device) == []


def test_a_run_of_anomalies_raises_one_alert_and_one_ticket(client, db, device, monkeypatch):
    for score in (0.75, 0.8, 0.9, 0.95, 0.99):
        _send(client, device, monkeypatch, score)
    alerts = _open_alerts(db, device)
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    tickets = db.query(Ticket).filter(Ticket.alert_id == alerts[0].id).all()
    assert len(tickets) == 1
    assert tickets[0].priority == "critical"


@pytest.mark.parametrize("scores,severity", [((0.72, 0.75, 0.8), "warning"), ((0.72, 0.9, 0.8), "critical")])
def test_severity_follows_the_peak_score(client, db, device, monkeypatch, scores, severity):
    for score in scores:
        _send(client, device, monkeypatch, score)
    assert _open_alerts(db, device)[0].severity == severity


def test_the_alert_clears_once_readings_are_normal_again(client, db, device, monkeypatch):
    for score in (0.9, 0.9, 0.9):
        _send(client, device, monkeypatch, score)
    assert len(_open_alerts(db, device)) == 1
    for score in (0.1, 0.2, 0.1):
        _send(client, device, monkeypatch, score)
    assert _open_alerts(db, device) == []


def test_a_returning_fault_reuses_the_open_ticket(client, db, device, monkeypatch):
    for score in (0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.9, 0.9, 0.9):
        _send(client, device, monkeypatch, score)
    assert len(_open_alerts(db, device)) == 1
    assert db.query(Ticket).filter(Ticket.device_id == device.id).count() == 1
