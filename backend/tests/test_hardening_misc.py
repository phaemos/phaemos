"""
The smaller security items: spreadsheet safe exports, a machine's share of the daily alert caps, the phone confirmation gate and
the no-scored-reading alert skipping machines that are unscored by design.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.models.alert import Alert
from app.models.telemetry import Telemetry
from app.services import alert_service, cooldown, csv_safe, health_service, ml_service
from tests.test_alert_notifications import FakeRedis


@pytest.fixture
def store(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cooldown, "_client", lambda: fake)
    cooldown._local.clear()
    cooldown._local_daily.clear()
    yield fake
    cooldown._local.clear()
    cooldown._local_daily.clear()


# -- spreadsheet safe cells ---------------------------------------------------------------------

@pytest.mark.parametrize("text_in", ["=1+1", "+1", "-1+1", "@SUM(A1)", "\t=1", "\r=1", '=HYPERLINK("http://x","y")'])
def test_a_text_cell_that_would_be_a_formula_gets_a_quote(text_in):
    assert csv_safe.safe_cell(text_in) == "'" + text_in


@pytest.mark.parametrize("value", ["esp32", "", "1+1", 5, -3.5, None, True, datetime(2030, 1, 1)])
def test_other_cells_pass_unchanged(value):
    assert csv_safe.safe_cell(value) == value


def test_the_telemetry_export_neutralises_a_node_type_that_is_a_formula(client, db, device, auth_headers):
    now = datetime.now(timezone.utc)
    db.add(Telemetry(device_id=device.id, node_type='=HYPERLINK("x")', temperature=-5.0, recorded_at=now))
    db.flush()
    res = client.get(
        "/api/v1/telemetry/export",
        params={"device_id": str(device.id), "from_ts": (now - timedelta(hours=1)).isoformat()},
        headers=auth_headers,
    )
    assert res.status_code == 200
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert rows[0]["node_type"] == "'=HYPERLINK(\"x\")"
    # a negative number is a number and is left alone
    assert rows[0]["temperature"] == "-5.0"


# -- a machine's share of the daily caps --------------------------------------------------------

def test_one_machine_can_spend_its_share_and_no_more(db, device, store, monkeypatch):
    monkeypatch.setattr(settings, "alert_email_daily_cap", 50)
    got = [alert_service.reserve_daily_send("email", device, 1, 50, False)[0] for _ in range(14)]
    # a quarter of 50 is 12
    assert [g is not None for g in got] == [True] * 12 + [False] * 2
    held, refused, limit = alert_service.reserve_daily_send("email", device, 1, 50, True)
    assert held is None and refused == f"email:{device.id}" and limit == 12


def test_another_machine_still_has_its_own_share(db, device, store):
    from app.models.device import Device
    other = Device(name="Other", api_key="o" * 43)
    db.add(other)
    db.flush()
    for _ in range(12):
        assert alert_service.reserve_daily_send("email", device, 1, 50, False)[0] is not None
    assert alert_service.reserve_daily_send("email", device, 1, 50, False)[0] is None
    assert alert_service.reserve_daily_send("email", other, 1, 50, False)[0] is not None


def test_a_warning_cannot_use_the_critical_reserve_but_a_critical_alert_can(db, device, store):
    # the site has used 40 of 50. A fifth of the day's allowance is kept for critical alerts
    cooldown.count_daily("email", 40)
    held, refused, limit = alert_service.reserve_daily_send("email", device, 1, 50, False)
    assert held is None and refused == "email" and limit == 40
    assert alert_service.reserve_daily_send("email", device, 1, 50, True)[0] is not None


def test_a_machine_that_loses_the_site_cap_gives_its_own_count_back(db, device, store):
    cooldown.count_daily("email", 40)
    alert_service.reserve_daily_send("email", device, 1, 50, False)
    # its own count was reserved first and given back when the site refused, so it is not spent for nothing
    assert cooldown.count_daily(f"email:{device.id}", 0) == 0


def test_small_caps_are_not_squeezed_by_the_share(db, device, store):
    # a cap under ten is the whole cap for one machine and has no reserve: tests and small sites behave as before
    for _ in range(3):
        assert alert_service.reserve_daily_send("email", device, 1, 3, False)[0] is not None
    assert alert_service.reserve_daily_send("email", device, 1, 3, False)[0] is None


# -- the phone confirmation gate ----------------------------------------------------------------

def test_texts_wait_for_a_confirmed_number_once_the_account_carries_the_confirmation():
    class Unconfirmed:
        phone_confirmed_at = None

    class Confirmed:
        phone_confirmed_at = datetime.now(timezone.utc)

    class NoField:
        pass

    assert alert_service._phone_confirmed(Unconfirmed()) is False
    assert alert_service._phone_confirmed(Confirmed()) is True
    # until the model has the field there is nothing to check
    assert alert_service._phone_confirmed(NoField()) is True


# -- the no-scored-reading alert and machines that are unscored by design ------------------------

def _unscored(db, device, seconds):
    t0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
    return health_service.track_scoring(db, device, {"temperature": 1.0}, False, t0 + timedelta(seconds=seconds))


@pytest.mark.parametrize("state", ["learning", "none"])
def test_a_machine_that_is_unscored_by_design_gets_no_alert(db, device, monkeypatch, state):
    monkeypatch.setattr(ml_service, "model_status", lambda device_id, node_type: {"state": state})
    monkeypatch.setattr(ml_service, "scoring_problem", lambda: None)
    assert _unscored(db, device, 0) is None
    assert _unscored(db, device, 4000) is None
    assert db.query(Alert).filter(Alert.device_id == device.id).count() == 0
    assert device.unscored_since is None


def test_a_machine_that_should_be_scored_still_gets_the_alert(db, device, monkeypatch):
    monkeypatch.setattr(ml_service, "model_status", lambda device_id, node_type: {"state": "ready"})
    monkeypatch.setattr(ml_service, "scoring_problem", lambda: None)
    monkeypatch.setattr(ml_service, "missing_features", lambda reading, device_id=None: ["humidity"])
    _unscored(db, device, 0)
    note = _unscored(db, device, 700)
    assert note is not None and note[0] == "unscored"


def test_the_missing_inputs_are_asked_for_this_machine(db, device, monkeypatch):
    asked = []
    monkeypatch.setattr(ml_service, "model_status", lambda device_id, node_type: {"state": "ready"})
    monkeypatch.setattr(ml_service, "scoring_problem", lambda: None)
    monkeypatch.setattr(ml_service, "missing_features", lambda reading, device_id=None: asked.append(device_id) or [])
    _unscored(db, device, 0)
    assert asked == [device.id]
