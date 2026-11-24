"""
Who may see and change what belongs to a machine.

The rule is the one GET /devices already applied: admins and viewers read every
machine, technicians read their own and unowned ones. Only admins and
technicians change anything. Each route below must answer the same way.
"""

import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from passlib.context import CryptContext
from starlette.websockets import WebSocketDisconnect

from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.maintenance import MaintenanceWindow
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.config import settings
from app.services.keys import derive_key
from app.models.user import User
from app.services import ws_manager
from tests._shape import plain

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _headers(user):
    from app.routes.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'role': user.role})}"}


def _make_user(db, email, role):
    u = User(name=email, email=email, password_hash=_pwd_ctx.hash("Passw0rd!x"), role=role)
    db.add(u)
    db.flush()
    return u


def _make_device(db, name, owner=None):
    d = Device(
        name=name, location="Lab", type="esp32",
        api_key=secrets.token_urlsafe(32), owner_id=owner.id if owner else None,
    )
    db.add(d)
    db.flush()
    return d


@pytest.fixture
def admin(db):
    return _make_user(db, "acl-admin@test.com", "admin")


@pytest.fixture
def tech(db):
    return _make_user(db, "acl-tech@test.com", "technician")


@pytest.fixture
def other_tech(db):
    return _make_user(db, "acl-other@test.com", "technician")


@pytest.fixture
def viewer(db):
    return _make_user(db, "acl-viewer@test.com", "viewer")


@pytest.fixture
def stranger(db):
    # a role outside the three the product knows. It must get nothing.
    return _make_user(db, "acl-stranger@test.com", "contractor")


@pytest.fixture
def mine(db, tech):
    return _make_device(db, "mine", tech)


@pytest.fixture
def theirs(db, other_tech):
    return _make_device(db, "theirs", other_tech)


@pytest.fixture
def shared(db):
    return _make_device(db, "shared")


def _reading(db, device):
    db.add(Telemetry(device_id=device.id, temperature=20.0, recorded_at=datetime.now(timezone.utc)))
    db.flush()


def _alert(db, device, resolved=False):
    a = Alert(device_id=device.id, message="hot", severity="warning", resolved=resolved)
    db.add(a)
    db.flush()
    return a


# ── telemetry reads and the anomaly history ─────────────────────────────────

# the export route needs a start time and covers at most 31 days
_EXPORT_FROM = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

_READ_PATHS = [
    "/api/v1/telemetry/{id}",
    "/api/v1/telemetry/{id}/latest",
    "/api/v1/telemetry/export?device_id={id}&from_ts=" + _EXPORT_FROM,
    "/api/v1/ml/anomalies/{id}",
]


NOT_FOUND = {"detail": "Device not found"}


@pytest.mark.parametrize("path", _READ_PATHS)
def test_machine_reads_follow_the_machine_rule(client, db, admin, tech, other_tech, viewer, mine, theirs, shared, path):
    _reading(db, mine)
    _reading(db, theirs)
    _reading(db, shared)

    def get(user, device):
        return client.get(path.format(id=device.id), headers=_headers(user))

    # latest answers 200 and the lists answer 200 too, including when empty
    assert get(admin, theirs).status_code == 200
    assert get(viewer, theirs).status_code == 200
    assert get(tech, mine).status_code == 200
    assert get(tech, shared).status_code == 200
    # another technician's machine is refused, with the body of a machine that does not exist
    for user, device in ((tech, theirs), (other_tech, mine)):
        res = get(user, device)
        assert res.status_code == 404
        assert plain(res) == NOT_FOUND


@pytest.mark.parametrize("path", _READ_PATHS)
def test_machine_reads_still_need_a_sign_in(client, shared, path):
    assert client.get(path.format(id=shared.id)).status_code == 401


@pytest.mark.parametrize("path", _READ_PATHS)
def test_a_refused_machine_and_a_missing_one_look_identical(client, db, admin, tech, theirs, path):
    _reading(db, theirs)
    missing = client.get(path.format(id=uuid.uuid4()), headers=_headers(admin))
    refused = client.get(path.format(id=theirs.id), headers=_headers(tech))
    assert (refused.status_code, plain(refused)) == (missing.status_code, plain(missing)) == (404, NOT_FOUND)
    assert "temperature" not in refused.text


@pytest.mark.parametrize("path", _READ_PATHS)
def test_an_unknown_role_reads_nothing(client, db, stranger, shared, path):
    _reading(db, shared)
    res = client.get(path.format(id=shared.id), headers=_headers(stranger))
    assert (res.status_code, plain(res)) == (404, NOT_FOUND)


def test_refused_telemetry_read_matches_the_devices_route(client, tech, theirs):
    via_devices = client.get(f"/api/v1/devices/{theirs.id}", headers=_headers(tech))
    via_telemetry = client.get(f"/api/v1/telemetry/{theirs.id}", headers=_headers(tech))
    assert (via_telemetry.status_code, plain(via_telemetry)) == (via_devices.status_code, plain(via_devices))
    assert via_devices.status_code == 404


def test_bucketed_history_refusal_wins_over_a_window_that_is_too_large(client, tech, mine, theirs):
    # ten second buckets over thirty days is far past the cap, so the owner is told so
    start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    params = {"bucket": 10, "from_ts": start}
    assert client.get(f"/api/v1/telemetry/{mine.id}", params=params, headers=_headers(tech)).status_code == 422
    # the same request for another technician's machine is refused first and says nothing about buckets
    res = client.get(f"/api/v1/telemetry/{theirs.id}", params=params, headers=_headers(tech))
    assert (res.status_code, plain(res)) == (404, NOT_FOUND)


def test_bucketed_history_allowed_for_the_owner(client, db, tech, mine):
    _reading(db, mine)
    start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    res = client.get(
        f"/api/v1/telemetry/{mine.id}", params={"bucket": 300, "from_ts": start}, headers=_headers(tech)
    )
    assert res.status_code == 200


def test_device_key_ingest_is_unchanged(client, theirs):
    res = client.post(
        "/api/v1/telemetry",
        json={"device_id": str(theirs.id), "temperature": 21.5},
        headers={"X-API-Key": theirs.api_key},
    )
    assert res.status_code == 201


# ── live readings socket ────────────────────────────────────────────────────

class _Tracked:
    # the socket route opens its own session and closes it. Tests keep their rows in an
    # uncommitted transaction, so the route is handed the test session. Each hand-out and each
    # close is counted, which lets a test prove the route never leaks a session.
    def __init__(self, session, closed):
        self._session = session
        self._closed = closed

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        self._closed.append(1)


@pytest.fixture
def sessions(db, monkeypatch):
    opened, closed = [], []

    def factory():
        opened.append(1)
        return _Tracked(db, closed)

    monkeypatch.setattr("app.routes.ws.SessionLocal", factory)
    # a client that sends no first frame is refused after this long. Short, so tests stay quick
    monkeypatch.setattr("app.routes.ws.FIRST_FRAME_SECONDS", 0.3)
    return opened, closed


def _token(user):
    return _headers(user)["Authorization"].split(" ", 1)[1]


def _url(device_id, token):
    return f"/ws/telemetry/{device_id}?token={token}"


def _subscribers(device_id):
    return list(ws_manager._connections.get(str(device_id), []))


def _assert_unsubscribed(device_id):
    # the server removes a socket as its handler ends, which can trail the client by a moment
    deadline = time.time() + 3
    while _subscribers(device_id) and time.time() < deadline:
        time.sleep(0.05)
    assert _subscribers(device_id) == []


def _wait_subscribed(device_id):
    deadline = time.time() + 3
    while not _subscribers(device_id) and time.time() < deadline:
        time.sleep(0.05)
    assert len(_subscribers(device_id)) == 1


@pytest.fixture
def subscribe_log(monkeypatch):
    # records every call that would put a socket in the manager's connection set
    calls = []
    real = ws_manager.subscribe

    def recording(device_id, websocket):
        calls.append(device_id)
        real(device_id, websocket)

    monkeypatch.setattr("app.routes.ws.subscribe", recording)
    return calls


def _expect_close_1008(ws):
    with pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_text()
    assert exc.value.code == 1008


def test_socket_opens_for_admin_viewer_owner_and_shared(client, sessions, admin, viewer, tech, mine, theirs, shared):
    for user, device in ((admin, theirs), (viewer, theirs), (tech, mine), (tech, shared)):
        with client.websocket_connect(_url(device.id, _token(user))):
            _wait_subscribed(device.id)
        _assert_unsubscribed(device.id)


def test_socket_session_is_closed_after_every_check(client, sessions, tech, mine, theirs):
    opened, closed = sessions
    with client.websocket_connect(_url(mine.id, _token(tech))):
        pass
    with client.websocket_connect(_url(theirs.id, _token(tech))) as ws:
        _expect_close_1008(ws)
    assert len(opened) == len(closed) >= 2


def test_refused_socket_is_accepted_then_closed_with_1008_and_never_subscribed(
    client, sessions, subscribe_log, tech, theirs
):
    missing = uuid.uuid4()
    refusals = [
        # a token that is not one at all
        (theirs.id, "not-a-token"),
        # no token
        (theirs.id, ""),
        # a missing machine
        (missing, _token(tech)),
        # a machine this technician may not read
        (theirs.id, _token(tech)),
    ]
    for device_id, token in refusals:
        with client.websocket_connect(_url(device_id, token)) as ws:
            # connecting succeeds, so a browser gets the documented close code and not a failed handshake
            assert _subscribers(device_id) == []
            _expect_close_1008(ws)
        _assert_unsubscribed(device_id)
    # the manager was never asked to hold any of them
    assert subscribe_log == []


def test_every_socket_refusal_looks_the_same(client, sessions, tech, theirs):
    outcomes = set()
    for device_id, token in ((uuid.uuid4(), _token(tech)), (theirs.id, _token(tech)), (theirs.id, "junk")):
        with client.websocket_connect(_url(device_id, token)) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            outcomes.add((exc.value.code, exc.value.reason))
    assert len(outcomes) == 1


def test_socket_refuses_a_token_that_has_expired(client, sessions, tech, mine):
    expired = jwt.encode(
        {"sub": str(tech.id), "type": "access", "ver": 0, "exp": int(time.time()) - 30},
        derive_key("access"), algorithm=settings.algorithm,
    )
    with client.websocket_connect(_url(mine.id, expired)) as ws:
        _expect_close_1008(ws)
    _assert_unsubscribed(mine.id)


def test_socket_closes_when_its_token_expires(client, sessions, tech, mine):
    soon = jwt.encode(
        {"sub": str(tech.id), "type": "access", "ver": 0, "exp": int(time.time()) + 3},
        derive_key("access"), algorithm=settings.algorithm,
    )
    with client.websocket_connect(_url(mine.id, soon)) as ws:
        _wait_subscribed(mine.id)
        _expect_close_1008(ws)
    _assert_unsubscribed(mine.id)


def test_socket_closes_when_the_session_ends(client, db, sessions, monkeypatch, tech, mine):
    monkeypatch.setattr("app.routes.ws.RECHECK_SECONDS", 0.3)
    with client.websocket_connect(_url(mine.id, _token(tech))) as ws:
        # signing out everywhere raises the session version the token was issued with
        tech.token_version = (tech.token_version or 0) + 1
        db.flush()
        _expect_close_1008(ws)
    _assert_unsubscribed(mine.id)


def test_socket_closes_when_the_role_changes_to_nothing(client, db, sessions, monkeypatch, tech, mine):
    monkeypatch.setattr("app.routes.ws.RECHECK_SECONDS", 0.3)
    with client.websocket_connect(_url(mine.id, _token(tech))) as ws:
        tech.role = "contractor"
        db.flush()
        _expect_close_1008(ws)


def test_socket_closes_when_the_machine_changes_hands(client, db, sessions, monkeypatch, tech, other_tech, shared):
    monkeypatch.setattr("app.routes.ws.RECHECK_SECONDS", 0.3)
    with client.websocket_connect(_url(shared.id, _token(tech))) as ws:
        # an admin hands the unowned machine to another technician
        shared.owner_id = other_tech.id
        db.flush()
        _expect_close_1008(ws)
    _assert_unsubscribed(shared.id)


def test_socket_stays_open_while_the_answer_is_unchanged(client, sessions, monkeypatch, tech, mine):
    monkeypatch.setattr("app.routes.ws.RECHECK_SECONDS", 0.2)
    with client.websocket_connect(_url(mine.id, _token(tech))):
        time.sleep(0.8)
        _wait_subscribed(mine.id)


# ── alerts ──────────────────────────────────────────────────────────────────

def _ids(res):
    return {item["id"] for item in res.json()}


def test_alert_list_is_filtered_for_technicians_only(client, db, admin, viewer, tech, mine, theirs, shared):
    a_mine, a_theirs, a_shared = _alert(db, mine), _alert(db, theirs), _alert(db, shared)
    everything = {str(a_mine.id), str(a_theirs.id), str(a_shared.id)}

    assert _ids(client.get("/api/v1/alerts", headers=_headers(admin))) == everything
    assert _ids(client.get("/api/v1/alerts", headers=_headers(viewer))) == everything
    assert _ids(client.get("/api/v1/alerts", headers=_headers(tech))) == {str(a_mine.id), str(a_shared.id)}


def test_alert_list_filter_keeps_the_resolved_query(client, db, tech, mine, theirs):
    open_alert = _alert(db, mine)
    _alert(db, mine, resolved=True)
    _alert(db, theirs)
    res = client.get("/api/v1/alerts?resolved=false", headers=_headers(tech))
    assert _ids(res) == {str(open_alert.id)}


def test_alerts_for_one_machine_follow_the_machine_rule(client, db, admin, viewer, tech, mine, theirs):
    _alert(db, theirs)
    # a machine's alerts are a filter on the list (GET /alerts/{device_id} was removed)
    def for_machine(device, user):
        return client.get("/api/v1/alerts", params={"device_id": str(device.id)}, headers=_headers(user))

    assert for_machine(theirs, admin).status_code == 200
    assert for_machine(theirs, viewer).status_code == 200
    assert for_machine(mine, tech).status_code == 200
    refused = for_machine(theirs, tech)
    assert (refused.status_code, plain(refused)) == (404, NOT_FOUND)


def test_unknown_role_gets_no_alerts(client, db, stranger, shared):
    _alert(db, shared)
    assert client.get("/api/v1/alerts", headers=_headers(stranger)).json() == []


def test_resolve_alert_by_role_and_machine(client, db, admin, viewer, tech, other_tech, mine, theirs, shared):
    def resolve(user, device):
        alert = _alert(db, device)
        return client.patch(f"/api/v1/alerts/{alert.id}/resolve", headers=_headers(user))

    assert resolve(admin, theirs).status_code == 200
    assert resolve(tech, mine).status_code == 200
    assert resolve(tech, shared).status_code == 200
    # a machine the caller may not read looks like an alert that does not exist
    for user, device in ((tech, theirs), (other_tech, mine)):
        res = resolve(user, device)
        assert (res.status_code, plain(res)) == (404, {"detail": "Alert not found"})
    # viewers may read the machine but are read-only, so they are told no and not "not found"
    for device in (mine, shared):
        res = resolve(viewer, device)
        assert (res.status_code, plain(res)) == (403, {"detail": "Access denied"})


def test_refused_resolve_leaves_the_alert_open(client, db, tech, viewer, theirs, mine):
    hidden, visible = _alert(db, theirs), _alert(db, mine)
    client.patch(f"/api/v1/alerts/{hidden.id}/resolve", headers=_headers(tech))
    client.patch(f"/api/v1/alerts/{visible.id}/resolve", headers=_headers(viewer))
    db.refresh(hidden)
    db.refresh(visible)
    assert not hidden.resolved
    assert not visible.resolved


# ── alert rules ─────────────────────────────────────────────────────────────

def _rule(db, device):
    r = AlertRule(for_seconds=0, device_id=device.id, metric="temperature", condition="gt", threshold=50.0, severity="warning")
    db.add(r)
    db.flush()
    return r


def test_alert_rule_list_is_filtered_for_technicians_only(client, db, admin, viewer, tech, mine, theirs, shared):
    r_mine, r_theirs, r_shared = _rule(db, mine), _rule(db, theirs), _rule(db, shared)
    everything = {str(r_mine.id), str(r_theirs.id), str(r_shared.id)}
    assert _ids(client.get("/api/v1/alert-rules", headers=_headers(admin))) == everything
    assert _ids(client.get("/api/v1/alert-rules", headers=_headers(viewer))) == everything
    assert _ids(client.get("/api/v1/alert-rules", headers=_headers(tech))) == {str(r_mine.id), str(r_shared.id)}


def test_alert_rules_for_one_machine_follow_the_machine_rule(client, db, admin, tech, mine, theirs):
    _rule(db, theirs)
    assert client.get(f"/api/v1/alert-rules?device_id={theirs.id}", headers=_headers(admin)).status_code == 200
    assert client.get(f"/api/v1/alert-rules?device_id={mine.id}", headers=_headers(tech)).status_code == 200
    refused = client.get(f"/api/v1/alert-rules?device_id={theirs.id}", headers=_headers(tech))
    assert (refused.status_code, plain(refused)) == (404, NOT_FOUND)


def test_alert_rule_changes_stay_admin_only(client, db, admin, viewer, tech, mine):
    body = {"device_id": str(mine.id), "metric": "temperature", "condition": "gt", "threshold": 40.0, "severity": "warning"}
    rule = _rule(db, mine)
    for user in (tech, viewer):
        assert client.post("/api/v1/alert-rules", json=body, headers=_headers(user)).status_code == 403
        assert client.put(f"/api/v1/alert-rules/{rule.id}", json={"threshold": 1.0}, headers=_headers(user)).status_code == 403
        assert client.delete(f"/api/v1/alert-rules/{rule.id}", headers=_headers(user)).status_code == 403
    assert client.post("/api/v1/alert-rules", json=body, headers=_headers(admin)).status_code == 201


# ── tickets ─────────────────────────────────────────────────────────────────

def _ticket(db, device=None, alert=None, created_by=None, assigned_to=None):
    t = Ticket(
        device_id=device.id if device else None,
        alert_id=alert.id if alert else None,
        created_by=created_by.id if created_by else None,
        assigned_to=assigned_to.id if assigned_to else None,
        title="Check it", status="open", priority="low",
    )
    db.add(t)
    db.flush()
    return t


def test_ticket_list_is_filtered_for_technicians_only(client, db, admin, viewer, tech, mine, theirs, shared):
    t_mine, t_theirs, t_shared = _ticket(db, mine), _ticket(db, theirs), _ticket(db, shared)
    t_none = _ticket(db)
    # a ticket with no machine is visible to its creator and its assignee as well
    t_own_none = _ticket(db, created_by=tech)
    t_given_none = _ticket(db, assigned_to=tech)
    # tickets tied only to an alert follow the alert's machine
    t_alert_theirs = _ticket(db, alert=_alert(db, theirs))
    t_alert_mine = _ticket(db, alert=_alert(db, mine))
    everything = {
        str(t.id) for t in (t_mine, t_theirs, t_shared, t_none, t_alert_theirs, t_alert_mine, t_own_none, t_given_none)
    }

    assert _ids(client.get("/api/v1/tickets?limit=100", headers=_headers(admin))) == everything
    assert _ids(client.get("/api/v1/tickets?limit=100", headers=_headers(viewer))) == everything
    # a ticket tied to no machine may be one whose machine was deleted, so a technician does not see
    # one they neither raised nor were given
    assert _ids(client.get("/api/v1/tickets?limit=100", headers=_headers(tech))) == {
        str(t.id) for t in (t_mine, t_shared, t_alert_mine, t_own_none, t_given_none)
    }


def test_get_ticket_follows_the_machine_rule(client, db, admin, viewer, tech, mine, theirs):
    t_theirs, t_mine, t_none = _ticket(db, theirs), _ticket(db, mine), _ticket(db)
    t_alert_theirs = _ticket(db, alert=_alert(db, theirs))

    def get(user, ticket):
        return client.get(f"/api/v1/tickets/{ticket.id}", headers=_headers(user))

    assert get(admin, t_theirs).status_code == 200
    assert get(viewer, t_theirs).status_code == 200
    assert get(tech, t_mine).status_code == 200
    # refused reads look like a ticket that does not exist
    for ticket in (t_theirs, t_alert_theirs, t_none):
        res = get(tech, ticket)
        assert (res.status_code, plain(res)) == (404, {"detail": "Ticket not found"})


def test_create_ticket_needs_write_access_to_its_machine(client, db, admin, viewer, tech, mine, theirs, shared):
    def create(user, **link):
        return client.post("/api/v1/tickets", json={"title": "Look", "priority": "low", **link}, headers=_headers(user))

    assert create(tech, device_id=str(mine.id)).status_code == 201
    assert create(tech, device_id=str(shared.id)).status_code == 201
    assert create(tech).status_code == 201
    assert create(admin, device_id=str(theirs.id)).status_code == 201
    assert create(admin).status_code == 201
    # a machine the technician may not read looks like one that does not exist
    res = create(tech, device_id=str(theirs.id))
    assert (res.status_code, plain(res)) == (404, NOT_FOUND)
    alert = _alert(db, theirs)
    res = create(tech, alert_id=str(alert.id))
    assert (res.status_code, plain(res)) == (404, {"detail": "Alert not found"})
    assert create(admin, alert_id=str(alert.id)).status_code == 201


def test_viewers_cannot_create_tickets(client, db, viewer, mine, shared):
    for link in ({}, {"device_id": str(mine.id)}, {"device_id": str(shared.id)}, {"alert_id": str(_alert(db, mine).id)}):
        res = client.post("/api/v1/tickets", json={"title": "Look", **link}, headers=_headers(viewer))
        assert (res.status_code, plain(res)) == (403, {"detail": "Access denied"})


def test_unknown_role_cannot_create_or_read_tickets(client, db, stranger, shared):
    ticket = _ticket(db, shared)
    assert client.post("/api/v1/tickets", json={"title": "x"}, headers=_headers(stranger)).status_code == 403
    assert client.get("/api/v1/tickets", headers=_headers(stranger)).json() == []
    assert client.get(f"/api/v1/tickets/{ticket.id}", headers=_headers(stranger)).status_code == 404
    assert client.patch(f"/api/v1/tickets/{ticket.id}", json={"status": "closed"}, headers=_headers(stranger)).status_code == 404


def test_ticket_with_a_mismatched_machine_and_alert_is_refused(client, db, admin, tech, mine, shared, theirs):
    their_alert = _alert(db, theirs)
    body = {"title": "Look", "device_id": str(mine.id), "alert_id": str(their_alert.id)}
    for user in (tech, admin):
        res = client.post("/api/v1/tickets", json=body, headers=_headers(user))
        assert (res.status_code, plain(res)) == (404, {"detail": "Alert not found"})
    # the same ids with a matching pair are accepted
    own_alert = _alert(db, mine)
    ok = client.post(
        "/api/v1/tickets", json={**body, "alert_id": str(own_alert.id)}, headers=_headers(tech)
    )
    assert ok.status_code == 201


def test_ticket_with_an_alert_that_does_not_exist_is_a_404_not_a_database_error(client, admin, mine):
    for link in ({"alert_id": str(uuid.uuid4())}, {"device_id": str(mine.id), "alert_id": str(uuid.uuid4())}):
        res = client.post("/api/v1/tickets", json={"title": "x", **link}, headers=_headers(admin))
        assert (res.status_code, plain(res)) == (404, {"detail": "Alert not found"})


def test_create_ticket_for_a_missing_machine_answers_404(client, tech):
    res = client.post("/api/v1/tickets", json={"title": "x", "device_id": str(uuid.uuid4())}, headers=_headers(tech))
    assert (res.status_code, plain(res)) == (404, NOT_FOUND)


def test_update_ticket_by_role_and_machine(client, db, admin, viewer, tech, other_tech, mine, theirs, shared):
    def patch(user, ticket):
        return client.patch(f"/api/v1/tickets/{ticket.id}", json={"status": "in_progress"}, headers=_headers(user)).status_code

    assert patch(admin, _ticket(db, theirs)) == 200
    assert patch(tech, _ticket(db, mine)) == 200
    assert patch(tech, _ticket(db, shared)) == 200
    # a ticket with no machine is the creator's and the assignee's to change and nobody else's
    assert patch(tech, _ticket(db, created_by=tech)) == 200
    assert patch(tech, _ticket(db, assigned_to=tech)) == 200
    assert patch(tech, _ticket(db)) == 404
    # reached through its alert, the ticket follows the alert's machine
    assert patch(tech, _ticket(db, alert=_alert(db, mine))) == 200
    assert patch(tech, _ticket(db, theirs)) == 404
    assert patch(other_tech, _ticket(db, mine)) == 404
    assert patch(tech, _ticket(db, alert=_alert(db, theirs))) == 404
    # viewers read everything and change nothing
    assert patch(viewer, _ticket(db, mine)) == 403
    assert patch(viewer, _ticket(db)) == 403


def test_refused_ticket_update_changes_nothing(client, db, tech, theirs):
    ticket = _ticket(db, theirs)
    client.patch(f"/api/v1/tickets/{ticket.id}", json={"status": "closed"}, headers=_headers(tech))
    db.refresh(ticket)
    assert ticket.status == "open"


def test_ticket_missing_still_answers_404(client, admin):
    assert client.patch(f"/api/v1/tickets/{uuid.uuid4()}", json={"status": "closed"}, headers=_headers(admin)).status_code == 404
    assert client.get(f"/api/v1/tickets/{uuid.uuid4()}", headers=_headers(admin)).status_code == 404


# ── maintenance windows ─────────────────────────────────────────────────────

def _window(db, device=None):
    now = datetime.now(timezone.utc)
    w = MaintenanceWindow(
        label="w", start_at=now, end_at=now + timedelta(hours=1),
        device_id=device.id if device else None,
    )
    db.add(w)
    db.flush()
    return w


def test_maintenance_window_list_is_filtered_for_technicians_only(client, db, admin, viewer, tech, mine, theirs, shared):
    w_mine, w_theirs, w_shared, w_fleet = _window(db, mine), _window(db, theirs), _window(db, shared), _window(db)
    everything = {str(w.id) for w in (w_mine, w_theirs, w_shared, w_fleet)}
    assert _ids(client.get("/api/v1/maintenance-windows", headers=_headers(admin))) == everything
    assert _ids(client.get("/api/v1/maintenance-windows", headers=_headers(viewer))) == everything
    assert _ids(client.get("/api/v1/maintenance-windows", headers=_headers(tech))) == {
        str(w.id) for w in (w_mine, w_shared, w_fleet)
    }


def test_maintenance_window_changes_stay_admin_only(client, db, tech, viewer, mine):
    window = _window(db, mine)
    start = datetime.now(timezone.utc)
    body = {"label": "x", "start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat()}
    for user in (tech, viewer):
        assert client.post("/api/v1/maintenance-windows", json=body, headers=_headers(user)).status_code == 403
        assert client.patch(f"/api/v1/maintenance-windows/{window.id}", json={"label": "y"}, headers=_headers(user)).status_code == 403
        assert client.delete(f"/api/v1/maintenance-windows/{window.id}", headers=_headers(user)).status_code == 403


# ── firmware targeting and device changes stay as they were ─────────────────

def test_firmware_batch_update_stays_admin_only(client, tech, viewer):
    body = {"tag": "line-1", "version": "1.2.3"}
    for user in (tech, viewer):
        assert client.post("/api/v1/devices/batch/firmware-update", json=body, headers=_headers(user)).status_code == 403


# ── device changes: owner, tags and firmware version are admin matters ──────

@pytest.mark.parametrize("change", [
    {"owner_id": "SELF"},
    {"owner_id": None},
    {"tags": ["line-1"]},
    {"firmware_version": "9.9.9"},
])
def test_technician_cannot_set_admin_only_device_fields(client, db, tech, other_tech, mine, shared, change):
    body = {k: (str(tech.id) if v == "SELF" else v) for k, v in change.items()}
    field = next(iter(body))
    before = (shared.owner_id, list(shared.tags or []), shared.firmware_version)
    for device in (mine, shared):
        res = client.patch(f"/api/v1/devices/{device.id}", json=body, headers=_headers(tech))
        assert res.status_code == 403
        assert plain(res) == {"detail": f"Only an admin can change {field}"}
    db.refresh(shared)
    assert (shared.owner_id, list(shared.tags or []), shared.firmware_version) == before


def test_technician_can_still_change_the_other_device_fields(client, tech, mine):
    res = client.patch(
        f"/api/v1/devices/{mine.id}",
        json={"name": "Renamed", "location": "Bay 2", "status": "warning"},
        headers=_headers(tech),
    )
    assert res.status_code == 200
    # status belongs to the system (the liveness sweep) and is no longer writable: it is ignored
    assert (res.json()["name"], res.json()["location"], res.json()["status"]) == ("Renamed", "Bay 2", "offline")


def test_a_technician_cannot_clear_the_firmware_version_with_a_null(client, db, tech, mine):
    mine.firmware_version = "1.2.3"
    db.flush()
    res = client.patch(f"/api/v1/devices/{mine.id}", json={"firmware_version": None}, headers=_headers(tech))
    assert res.status_code == 403
    db.refresh(mine)
    assert mine.firmware_version == "1.2.3"


def test_admin_can_set_owner_tags_and_firmware_version(client, admin, tech, shared):
    res = client.patch(
        f"/api/v1/devices/{shared.id}",
        json={"owner_id": str(tech.id), "tags": ["line-1"], "firmware_version": "2.0.0"},
        headers=_headers(admin),
    )
    assert res.status_code == 200
    assert res.json()["owner_id"] == str(tech.id)
    assert res.json()["tags"] == ["line-1"]
    assert res.json()["firmware_version"] == "2.0.0"


def test_admin_can_clear_the_owner_with_an_explicit_null(client, admin, mine):
    res = client.patch(f"/api/v1/devices/{mine.id}", json={"owner_id": None}, headers=_headers(admin))
    assert res.status_code == 200
    assert res.json()["owner_id"] is None


def test_an_omitted_owner_is_left_alone(client, admin, mine, tech):
    res = client.patch(f"/api/v1/devices/{mine.id}", json={"name": "Same owner"}, headers=_headers(admin))
    assert res.status_code == 200
    assert res.json()["owner_id"] == str(tech.id)


def test_an_owner_that_does_not_exist_is_refused_cleanly(client, admin, mine):
    res = client.patch(f"/api/v1/devices/{mine.id}", json={"owner_id": str(uuid.uuid4())}, headers=_headers(admin))
    assert (res.status_code, plain(res)) == (404, {"detail": "Owner not found"})


def test_a_null_name_is_a_422_and_changes_nothing(client, admin, mine):
    # one rule for every PATCH: null clears a field that may be cleared and is refused on any other
    res = client.patch(f"/api/v1/devices/{mine.id}", json={"name": None, "location": "Bay 3"}, headers=_headers(admin))
    assert res.status_code == 422 and res.json()["code"] == "validation_failed"
    assert client.get(f"/api/v1/devices/{mine.id}", headers=_headers(admin)).json()["name"] == "mine"


def test_device_writes_by_a_reader_who_cannot_write_stay_403(client, viewer, mine):
    for call in (
        client.patch(f"/api/v1/devices/{mine.id}", json={"name": "x"}, headers=_headers(viewer)),
        client.post(f"/api/v1/devices/{mine.id}/rotate-key", json={"password": "Passw0rd!x"}, headers=_headers(viewer)),
    ):
        assert (call.status_code, plain(call)) == (403, {"detail": "Access denied"})


def test_device_writes_on_a_machine_the_caller_cannot_read_answer_404(client, tech, theirs):
    for call in (
        client.patch(f"/api/v1/devices/{theirs.id}", json={"name": "x"}, headers=_headers(tech)),
        client.post(f"/api/v1/devices/{theirs.id}/rotate-key", json={"password": "Passw0rd!x"}, headers=_headers(tech)),
        client.get(f"/api/v1/devices/{theirs.id}", headers=_headers(tech)),
    ):
        assert (call.status_code, plain(call)) == (404, NOT_FOUND)


def test_unknown_role_sees_no_devices(client, stranger, shared):
    assert client.get("/api/v1/devices", headers=_headers(stranger)).json() == []
    res = client.patch(f"/api/v1/devices/{shared.id}", json={"name": "x"}, headers=_headers(stranger))
    assert res.status_code == 404


# ── health summary ──────────────────────────────────────────────────────────

def _summary(client, user):
    res = client.get("/api/v1/health/summary", headers=_headers(user))
    assert res.status_code == 200
    return res.json()


def test_health_summary_counts_only_what_the_caller_may_read(client, db, admin, viewer, tech, stranger, mine, theirs, shared):
    mine.status = theirs.status = "online"
    for device in (mine, theirs, shared):
        _alert(db, device)
        _rule(db, device)
        _ticket(db, device)
    _ticket(db)
    _ticket(db, alert=_alert(db, theirs))
    db.flush()

    everything = {"total_devices": 3, "online": 2, "offline": 1, "active_alerts": 4, "open_tickets": 5}
    for user in (admin, viewer):
        body = _summary(client, user)
        assert {k: body[k] for k in everything} == everything

    # a technician's totals leave out the other technician's machine, its alerts and its tickets
    # and a ticket with no machine that they neither raised nor were given
    body = _summary(client, tech)
    assert {k: body[k] for k in everything} == {
        "total_devices": 2, "online": 1, "offline": 1, "active_alerts": 2, "open_tickets": 2,
    }


def test_health_summary_is_empty_for_an_unknown_role(client, db, stranger, shared):
    _alert(db, shared)
    _ticket(db, shared)
    body = _summary(client, stranger)
    assert (body["total_devices"], body["active_alerts"], body["open_tickets"]) == (0, 0, 0)


# ── live socket: the token in the first frame ───────────────────────────────

def _auth_frame(token):
    return '{"type":"auth","token":"%s"}' % token


def _first_frame_url(device_id):
    return f"/ws/telemetry/{device_id}"


@pytest.fixture
def fresh_warning(monkeypatch):
    monkeypatch.setattr("app.routes.ws._warned_about_url_token", False)


def test_first_frame_token_opens_the_socket(client, sessions, subscribe_log, admin, viewer, tech, mine, theirs, shared):
    for user, device in ((admin, theirs), (viewer, theirs), (tech, mine), (tech, shared)):
        with client.websocket_connect(_first_frame_url(device.id)) as ws:
            ws.send_text(_auth_frame(_token(user)))
            _wait_subscribed(device.id)
        _assert_unsubscribed(device.id)


def test_first_frame_token_refused_for_a_machine_the_user_may_not_read(client, sessions, subscribe_log, tech, theirs):
    with client.websocket_connect(_first_frame_url(theirs.id)) as ws:
        ws.send_text(_auth_frame(_token(tech)))
        _expect_close_1008(ws)
    assert subscribe_log == []


def test_first_frame_refusals_all_close_with_1008_and_never_subscribe(client, sessions, subscribe_log, tech, mine):
    frames = [
        _auth_frame("not-a-token"),
        _auth_frame(""),
        "not json at all",
        '["auth"]',
        '{"type":"hello","token":"%s"}' % _token(tech),
        '{"type":"auth"}',
        '{"type":"auth","token":42}',
        # over the size cap, even though the token inside is a good one
        '{"type":"auth","token":"%s","pad":"%s"}' % (_token(tech), "x" * 5000),
    ]
    outcomes = set()
    for frame in frames:
        with client.websocket_connect(_first_frame_url(mine.id)) as ws:
            ws.send_text(frame)
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            outcomes.add((exc.value.code, exc.value.reason))
    assert outcomes == {(1008, "")}
    assert subscribe_log == []


def test_first_frame_binary_message_is_refused(client, sessions, subscribe_log, tech, mine):
    with client.websocket_connect(_first_frame_url(mine.id)) as ws:
        ws.send_bytes(_auth_frame(_token(tech)).encode())
        _expect_close_1008(ws)
    assert subscribe_log == []


def test_no_first_frame_in_time_is_refused(client, sessions, subscribe_log, mine):
    with client.websocket_connect(_first_frame_url(mine.id)) as ws:
        _expect_close_1008(ws)
    assert subscribe_log == []


def test_first_frame_for_a_missing_machine_closes_the_same_way(client, sessions, subscribe_log, tech):
    with client.websocket_connect(_first_frame_url(uuid.uuid4())) as ws:
        ws.send_text(_auth_frame(_token(tech)))
        _expect_close_1008(ws)
    assert subscribe_log == []


def test_first_frame_socket_still_closes_when_the_session_ends(client, db, sessions, monkeypatch, tech, mine):
    monkeypatch.setattr("app.routes.ws.RECHECK_SECONDS", 0.3)
    with client.websocket_connect(_first_frame_url(mine.id)) as ws:
        ws.send_text(_auth_frame(_token(tech)))
        _wait_subscribed(mine.id)
        tech.token_version = (tech.token_version or 0) + 1
        db.flush()
        _expect_close_1008(ws)


def test_url_token_form_still_works_and_warns_once(client, sessions, fresh_warning, caplog, tech, mine):
    with caplog.at_level("WARNING", logger="app.routes.ws"):
        for _ in range(2):
            with client.websocket_connect(_url(mine.id, _token(tech))):
                _wait_subscribed(mine.id)
            _assert_unsubscribed(mine.id)
    warnings = [r for r in caplog.records if r.name == "app.routes.ws" and r.levelname == "WARNING"]
    assert len(warnings) == 1
    # the warning never repeats the token
    assert _token(tech) not in warnings[0].getMessage()


def test_first_frame_form_logs_no_warning(client, sessions, fresh_warning, caplog, tech, mine):
    with caplog.at_level("WARNING", logger="app.routes.ws"):
        with client.websocket_connect(_first_frame_url(mine.id)) as ws:
            ws.send_text(_auth_frame(_token(tech)))
            _wait_subscribed(mine.id)
    assert [r for r in caplog.records if r.name == "app.routes.ws"] == []


# ── live socket: caps, frame sizes and the URL form switch ──────────────────

def _held():
    from app.routes import ws as ws_module
    return dict(ws_module._by_user), dict(ws_module._by_address)


def _assert_nothing_held():
    # the handler gives its slots back as it ends, which can trail the client by a moment
    deadline = time.time() + 3
    while _held() != ({}, {}) and time.time() < deadline:
        time.sleep(0.05)
    assert _held() == ({}, {})


def test_one_address_cannot_hold_more_sockets_than_its_share(client, sessions, subscribe_log, monkeypatch, tech, mine):
    monkeypatch.setattr(settings, "ws_max_per_address", 1)
    with client.websocket_connect(_url(mine.id, _token(tech))):
        _wait_subscribed(mine.id)
        # a second socket from the same address is accepted and closed at once, never subscribed
        with client.websocket_connect(_url(mine.id, _token(tech))) as second:
            _expect_close_1008(second)
        assert len(_subscribers(mine.id)) == 1
    _assert_unsubscribed(mine.id)
    # the slots came back
    _assert_nothing_held()
    with client.websocket_connect(_url(mine.id, _token(tech))):
        _wait_subscribed(mine.id)


def test_one_account_cannot_hold_more_sockets_than_its_share(client, sessions, monkeypatch, tech, mine, shared):
    monkeypatch.setattr(settings, "ws_max_per_user", 1)
    with client.websocket_connect(_url(mine.id, _token(tech))):
        _wait_subscribed(mine.id)
        with client.websocket_connect(_url(shared.id, _token(tech))) as second:
            _expect_close_1008(second)
        assert _subscribers(shared.id) == []
    _assert_unsubscribed(mine.id)
    _assert_nothing_held()


def test_refused_sockets_give_their_slots_back(client, sessions, tech, theirs):
    for _ in range(3):
        with client.websocket_connect(_url(theirs.id, _token(tech))) as ws:
            _expect_close_1008(ws)
    _assert_nothing_held()


def test_a_first_frame_over_the_cap_is_never_parsed_or_authorised(client, sessions, monkeypatch, tech, mine):
    # what the server accepted and not only how it closed: the token inside an oversized frame
    # never reaches the check, so none of it was read as an auth frame
    calls = []
    real = ws_module_authorise()

    def counting(token, device_id):
        calls.append(token)
        return real(token, device_id)

    monkeypatch.setattr("app.routes.ws._authorise", counting)
    big = '{"type":"auth","token":"%s","pad":"%s"}' % (_token(tech), "x" * 10000)
    with client.websocket_connect(_first_frame_url(mine.id)) as ws:
        ws.send_text(big)
        _expect_close_1008(ws)
    assert calls == []
    # a frame inside the cap does reach it
    with client.websocket_connect(_first_frame_url(mine.id)) as ws:
        ws.send_text(_auth_frame(_token(tech)))
        _wait_subscribed(mine.id)
    assert len(calls) == 1


def ws_module_authorise():
    from app.routes import ws as ws_module
    return ws_module._authorise


@pytest.mark.parametrize("send", ["text", "bytes"])
def test_a_signed_in_client_cannot_make_the_server_keep_reading_big_frames(client, sessions, tech, mine, send):
    with client.websocket_connect(_first_frame_url(mine.id)) as ws:
        ws.send_text(_auth_frame(_token(tech)))
        _wait_subscribed(mine.id)
        # small frames are read and dropped
        ws.send_text("ping")
        assert len(_subscribers(mine.id)) == 1
        # one over the cap ends the socket
        if send == "text":
            ws.send_text("x" * 5000)
        else:
            ws.send_bytes(b"x" * 5000)
        _expect_close_1008(ws)
    _assert_unsubscribed(mine.id)


def test_the_url_form_can_be_switched_off_and_the_first_frame_still_works(client, sessions, monkeypatch, tech, mine):
    monkeypatch.setattr(settings, "ws_token_in_url", False)
    calls = []
    real = ws_module_authorise()
    monkeypatch.setattr("app.routes.ws._authorise", lambda t, d: calls.append(t) or real(t, d))
    with client.websocket_connect(_url(mine.id, _token(tech))) as ws:
        _expect_close_1008(ws)
    # refused before the token was even looked at
    assert calls == []
    with client.websocket_connect(_first_frame_url(mine.id)) as ws:
        ws.send_text(_auth_frame(_token(tech)))
        _wait_subscribed(mine.id)


def test_the_url_form_follows_the_environment_unless_set(monkeypatch):
    monkeypatch.setattr(settings, "ws_token_in_url", None)
    monkeypatch.setattr(settings, "environment", "development")
    assert settings.ws_token_in_url_allowed is True
    for name in ("production", "prod", "staging"):
        monkeypatch.setattr(settings, "environment", name)
        assert settings.ws_token_in_url_allowed is False
    monkeypatch.setattr(settings, "ws_token_in_url", True)
    assert settings.ws_token_in_url_allowed is True


def test_the_socket_address_follows_the_trusted_proxy_rule():
    from app.routes.ws import _client_address

    class Fake:
        def __init__(self, peer, real_ip=None):
            self.client = type("C", (), {"host": peer})()
            self.headers = {"x-real-ip": real_ip} if real_ip else {}

    assert _client_address(Fake("127.0.0.1", "203.0.113.7")) == "203.0.113.7"
    assert _client_address(Fake("203.0.113.50", "198.51.100.1")) == "203.0.113.50"
    assert _client_address(Fake("127.0.0.1", "2001:db8:1:2::5")) == _client_address(Fake("127.0.0.1", "2001:db8:1:2:9::1"))
