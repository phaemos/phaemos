"""
Replay protection: a post is accepted only when its (boot, seq) is newer than the last accepted for the machine.
"""

import pytest
from passlib.context import CryptContext
from sqlalchemy import text

from app.models.telemetry import Telemetry
from app.models.user import User
from app.services import health_service, replay

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _post(client, device, expect=None, **fields):
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(device.id), "temperature": 22.0, **fields},
        headers={"X-API-Key": device.api_key},
    )
    if expect is not None:
        assert res.status_code == expect, res.text
    return res


def _rows(db, device):
    return db.query(Telemetry).filter(Telemetry.device_id == device.id).count()


def test_a_newer_pair_is_accepted_and_stored(client, db, device):
    _post(client, device, 201, boot=3, seq=10)
    _post(client, device, 201, boot=3, seq=11)
    _post(client, device, 201, boot=3, seq=20)
    # a new boot may restart the counter at a low seq: the boot decides first
    _post(client, device, 201, boot=4, seq=0)
    assert _rows(db, device) == 4
    assert (device.last_boot, device.last_seq) == (4, 0) and device.replay_protected is True


def test_the_exact_pair_last_accepted_is_a_retry_and_answers_200_with_a_marker(client, db, device):
    _post(client, device, 201, boot=3, seq=10)
    before = (device.last_seen, _rows(db, device))
    res = _post(client, device, 200, boot=3, seq=10)
    assert res.json()["status"] == "duplicate" and res.json()["stored"] is False
    assert (device.last_seen, _rows(db, device)) == before


def test_an_older_pair_is_refused_with_409_and_a_plain_message(client, db, device):
    _post(client, device, 201, boot=3, seq=10)
    for pair in ((3, 9), (2, 500), (3, 0)):
        res = _post(client, device, 409, boot=pair[0], seq=pair[1])
        assert "older" in res.json()["detail"]
    assert _rows(db, device) == 1
    assert device.replay_refused == 3


def test_a_refused_post_is_not_a_heartbeat_and_runs_no_alert_logic(client, db, device):
    _post(client, device, 201, boot=3, seq=10)
    seen = device.last_seen
    _post(client, device, 409, boot=3, seq=5, temperature=99.0)
    assert device.last_seen == seen
    assert _rows(db, device) == 1


def test_a_machine_that_has_sent_the_pair_must_always_send_it(client, db, device):
    _post(client, device, 201, boot=3, seq=10)
    for fields in ({}, {"seq": 11}, {"boot": 3}):
        res = _post(client, device, 409, **fields)
        assert "boot and seq" in res.json()["detail"]
    assert _rows(db, device) == 1


def test_a_machine_that_never_sent_the_pair_is_accepted_and_shown_unprotected(client, db, device, auth_headers):
    _post(client, device, 201)
    _post(client, device, 201, boot=1)
    _post(client, device, 201, seq=5)
    assert device.replay_protected is False
    body = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert body["replay_protected"] is False
    assert body["replay_status"].startswith("no replay protection")


def test_the_first_pair_turns_protection_on(client, db, device, auth_headers):
    _post(client, device, 201)
    _post(client, device, 201, boot=1, seq=1)
    body = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert body["replay_protected"] is True and body["last_boot"] == 1 and body["last_seq"] == 1
    assert body["replay_status"].startswith("protected")


def test_a_streak_of_refusals_is_shown_with_the_way_out(client, db, device, auth_headers):
    _post(client, device, 201, boot=40, seq=3)
    for n in range(3):
        _post(client, device, 409, boot=1, seq=n)
    body = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert body["replay_refused"] == 3
    assert "accept a new counter" in body["replay_status"]
    # an accepted post ends the streak
    _post(client, device, 201, boot=40, seq=4)
    assert client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()["replay_refused"] == 0


def test_an_admin_can_accept_a_new_counter_after_a_wiped_flash_and_it_is_audited(client, db, device, auth_headers):
    _post(client, device, 201, boot=40, seq=3)
    _post(client, device, 409, boot=1, seq=1)
    res = client.post(f"/api/v1/devices/{device.id}/accept-counter", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["replay_refused"] == 0 and res.json()["last_boot"] is None
    # the machine must still send the pair. Its new start is taken
    _post(client, device, 409)
    _post(client, device, 201, boot=1, seq=1)
    _post(client, device, 409, boot=1, seq=0)
    row = db.execute(text("SELECT action, detail FROM audit_log WHERE action = 'replay_counter_accepted'")).one()
    assert "previous_boot=40" in row.detail and "previous_seq=3" in row.detail


def test_only_an_admin_can_accept_a_counter(client, db, device):
    tech = User(name="t", email="replay-tech@example.com", password_hash=_pwd_ctx.hash("Passw0rd!x"), role="technician")
    db.add(tech)
    db.flush()
    from app.routes.auth import create_access_token
    headers = {"Authorization": f"Bearer {create_access_token({'sub': str(tech.id), 'role': tech.role})}"}
    assert client.post(f"/api/v1/devices/{device.id}/accept-counter", headers=headers).status_code == 403


def test_the_check_and_the_update_happen_under_the_device_lock(client, db, device, monkeypatch):
    # two posts racing both read the last pair. The lock makes the second wait and see the first's pair, so it is judged after it
    order = []
    real_lock = health_service.lock_device
    real_judge = replay.judge
    monkeypatch.setattr(health_service, "lock_device", lambda *a, **k: order.append("lock") or real_lock(*a, **k))
    monkeypatch.setattr(replay, "judge", lambda *a, **k: order.append("judge") or real_judge(*a, **k))
    _post(client, device, 201, boot=1, seq=1)
    assert order[:2] == ["lock", "judge"]


def test_replaying_a_captured_post_stores_nothing_new(client, db, device):
    # what an attacker with a capture of one post can do: send it again, now or after others have been accepted
    _post(client, device, 201, boot=5, seq=100)
    _post(client, device, 201, boot=5, seq=101)
    captured = dict(boot=5, seq=100, temperature=99.0)
    _post(client, device, 409, **captured)
    _post(client, device, 409, **captured)
    assert _rows(db, device) == 2


@pytest.mark.parametrize("last,pair,verdict", [
    ((1, 5), (1, 6), replay.ACCEPT), ((1, 5), (2, 0), replay.ACCEPT), ((1, 5), (1, 5), replay.DUPLICATE),
    ((1, 5), (1, 4), replay.OLD), ((2, 0), (1, 99), replay.OLD),
])
def test_judge(last, pair, verdict):
    class D:
        replay_protected = True
        last_boot, last_seq = last
    assert replay.judge(D, *pair) == verdict


# -- a pair pushed to the ceiling must not lock the machine out ---------------------------------

def test_the_largest_possible_pair_is_refused_outright_and_the_machine_still_posts(client, db, device):
    _post(client, device, 201, boot=3, seq=10)
    res = _post(client, device, 422, boot=2147483647, seq=4294967295)
    assert "higher than any machine could reach" in res.json()["detail"]
    # nothing was stored and the last accepted pair is untouched, so the real node carries on
    assert (device.last_boot, device.last_seq) == (3, 10)
    _post(client, device, 201, boot=3, seq=11)
    assert _rows(db, device) == 2


@pytest.mark.parametrize("fields,status", [
    ({"boot": replay.BOOT_CEILING, "seq": 5}, 201),
    ({"boot": replay.BOOT_CEILING + 1, "seq": 5}, 422),
    ({"boot": 5, "seq": replay.SEQ_CEILING}, 201),
    ({"boot": 5, "seq": replay.SEQ_CEILING + 1}, 422),
    # a Pico that falls back to Unix seconds as its boot is legitimate
    ({"boot": 1_800_000_000, "seq": 0}, 201),
    # one half alone is bounded too
    ({"boot": 2147483647}, 422),
    ({"seq": 4294967295}, 422),
])
def test_the_bounds_are_exact(client, db, device, fields, status):
    _post(client, device, status, **fields)


def test_a_big_jump_in_boot_is_accepted_and_shown_as_a_warning_with_the_advice_to_rotate(client, db, device, auth_headers):
    _post(client, device, 201, boot=3, seq=10)
    _post(client, device, 201, boot=4, seq=0)
    # an ordinary restart is not a warning
    assert client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()["replay_warning"] is None
    _post(client, device, 201, boot=2_000_000, seq=0)
    body = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert "boot jumped from 4 to 2000000" in body["counter_jump_note"]
    assert body["counter_jump_at"] is not None
    assert "Rotate this machine's key" in body["replay_warning"]


def test_a_big_jump_in_seq_within_one_boot_is_a_warning_too(client, db, device, auth_headers):
    _post(client, device, 201, boot=3, seq=10)
    _post(client, device, 201, boot=3, seq=11 + replay.SEQ_JUMP_WARN)
    body = client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()
    assert "seq jumped" in body["counter_jump_note"]


def test_the_first_pair_and_the_pico_move_to_unix_seconds_are_the_only_quiet_big_values(client, db, device, auth_headers):
    # the first pair has nothing to jump from
    _post(client, device, 201, boot=1_800_000_000, seq=0)
    assert client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()["replay_warning"] is None


def test_accepting_a_counter_clears_the_warning_and_the_audit_says_to_rotate(client, db, device, auth_headers):
    _post(client, device, 201, boot=3, seq=10)
    _post(client, device, 201, boot=900_000, seq=0)
    res = client.post(f"/api/v1/devices/{device.id}/accept-counter", headers=auth_headers)
    body = res.json()
    assert body["replay_warning"] is None and body["counter_jump_note"] is None
    assert "rotate the machine's key as well" in body["replay_recovery"]
    row = db.execute(text("SELECT detail FROM audit_log WHERE action = 'replay_counter_accepted'")).one()
    assert "key_rotation_advised=true" in row.detail and "counter_jump=boot jumped" in row.detail


def test_an_unprotected_machine_has_no_recovery_text(client, db, device, auth_headers):
    _post(client, device, 201)
    assert client.get(f"/api/v1/devices/{device.id}", headers=auth_headers).json()["replay_recovery"] is None
