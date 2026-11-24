"""
The daily retention job: closed tickets, resolved alerts and audit entries are deleted once they are past their
period. Open tickets and unresolved alerts never are. The clock is passed in, so nothing waits.
"""

import secrets
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.config import settings
from app.models.alert import Alert
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.tasks import retention

# the injected clock stays close to the real one. The audit writer stamps its rows with the real time, so a clock
# years ahead would make the audit rule delete the rows the other rules had just written
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _ago(days):
    return NOW - timedelta(days=days)


class _KeepOpen:
    # lets the job close its session without ending the test's own transaction
    def __init__(self, session):
        self._session = session

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.fixture
def run(db):
    def go():
        # the job deletes with SQL and commits, which expires every loaded object. A test object whose row the job
        # rightly deleted would then raise when read. So the rows are written out, the session forgets its
        # objects and a test reads results by the ids it kept, through fresh queries
        db.flush()
        db.expunge_all()
        return retention.run_retention(lambda: _KeepOpen(db), now=NOW)
    return go


@pytest.fixture
def machine(db):
    d = Device(name="Pump", location="Lab", type="esp32", api_key=secrets.token_urlsafe(32))
    db.add(d)
    db.flush()
    return d


def _ticket(db, machine, status, age_days, alert=None):
    t = Ticket(
        device_id=machine.id, alert_id=alert.id if alert else None, title=f"t-{secrets.token_hex(3)}",
        status=status, priority="low", created_at=_ago(age_days + 5), updated_at=_ago(age_days),
    )
    db.add(t)
    db.flush()
    return SimpleNamespace(id=t.id, alert_id=t.alert_id)


def _alert(db, machine, resolved, age_days):
    a = Alert(
        device_id=machine.id, message="hot", severity="warning", resolved=resolved,
        triggered_at=_ago(age_days + 1), resolved_at=_ago(age_days) if resolved else None,
    )
    db.add(a)
    db.flush()
    return SimpleNamespace(id=a.id, model=Alert)


def _audit(db, age_days, action="login"):
    db.execute(
        text("INSERT INTO audit_log (user_id, action, created_at) VALUES ('u', :a, :t)"),
        {"a": action, "t": _ago(age_days)},
    )


def _exists(db, model, row):
    # a fresh query by the id kept before the job ran
    return db.query(model).filter(model.id == row.id).first() is not None


# -- closed tickets -----------------------------------------------------------------------------

def test_a_closed_ticket_is_deleted_after_24_months_and_not_before(db, machine, run):
    old = _ticket(db, machine, "closed", 731)
    recent = _ticket(db, machine, "closed", 700)
    run()
    assert not _exists(db, Ticket, old)
    assert _exists(db, Ticket, recent)


@pytest.mark.parametrize("status", ["open", "in_progress"])
def test_an_open_ticket_is_never_deleted_however_old(db, machine, run, status):
    ticket = _ticket(db, machine, status, 5000)
    run()
    assert _exists(db, Ticket, ticket)


# -- resolved alerts ----------------------------------------------------------------------------

def test_a_resolved_alert_is_deleted_after_12_months_and_not_before(db, machine, run):
    old = _alert(db, machine, True, 366)
    recent = _alert(db, machine, True, 300)
    run()
    assert not _exists(db, Alert, old)
    assert _exists(db, Alert, recent)


def test_an_unresolved_alert_is_never_deleted_however_old(db, machine, run):
    alert = _alert(db, machine, False, 5000)
    run()
    assert _exists(db, Alert, alert)


def test_an_alert_that_a_remaining_ticket_points_at_is_kept(db, machine, run):
    alert = _alert(db, machine, True, 400)
    ticket = _ticket(db, machine, "open", 400, alert=alert)
    run()
    assert _exists(db, Alert, alert) and _exists(db, Ticket, ticket)


def test_a_young_closed_ticket_keeps_its_old_alert(db, machine, run):
    alert = _alert(db, machine, True, 400)
    ticket = _ticket(db, machine, "closed", 100, alert=alert)
    run()
    assert _exists(db, Alert, alert) and _exists(db, Ticket, ticket)
    # the ticket keeps its link: the foreign key would null it if the alert were deleted
    assert db.query(Ticket.alert_id).filter(Ticket.id == ticket.id).scalar() == alert.id


def test_an_alert_is_never_deleted_by_nulling_a_ticket_link(db, machine, run):
    # tickets.alert_id is ON DELETE SET NULL, so a careless alert delete would succeed and quietly orphan the ticket
    alert = _alert(db, machine, True, 400)
    ticket = _ticket(db, machine, "in_progress", 10, alert=alert)
    run()
    assert db.query(Ticket.alert_id).filter(Ticket.id == ticket.id).scalar() == alert.id


def test_an_old_closed_ticket_and_its_old_alert_go_together_without_a_key_error(db, machine, run):
    alert = _alert(db, machine, True, 800)
    ticket = _ticket(db, machine, "closed", 800, alert=alert)
    done = run()
    assert done["tickets"] == 1 and done["alerts"] == 1
    assert not _exists(db, Ticket, ticket) and not _exists(db, Alert, alert)


# -- the audit log ------------------------------------------------------------------------------

def test_audit_entries_older_than_12_months_are_deleted(db, run):
    _audit(db, 400, "old-entry")
    _audit(db, 100, "new-entry")
    run()
    kept = {r[0] for r in db.execute(text("SELECT action FROM audit_log"))}
    assert "old-entry" not in kept and "new-entry" in kept


# -- the periods are settings -------------------------------------------------------------------

def test_the_defaults_are_24_12_and_12_months():
    assert settings.retention_closed_tickets_days == 730
    assert settings.retention_resolved_alerts_days == 365
    assert settings.retention_audit_days == 365


def test_a_period_can_be_changed(db, machine, run, monkeypatch):
    monkeypatch.setattr(settings, "retention_resolved_alerts_days", 30)
    old = _alert(db, machine, True, 31)
    run()
    assert not _exists(db, Alert, old)


@pytest.mark.parametrize("name,make", [
    ("retention_closed_tickets_days", lambda db, m: _ticket(db, m, "closed", 5000)),
    ("retention_resolved_alerts_days", lambda db, m: _alert(db, m, True, 5000)),
])
def test_a_period_of_zero_keeps_that_data_for_ever(db, machine, run, monkeypatch, name, make):
    monkeypatch.setattr(settings, name, 0)
    row = make(db, machine)
    run()
    assert _exists(db, Alert if hasattr(row, "model") else Ticket, row)


def test_a_period_of_zero_skips_the_audit_rule(db, run, monkeypatch):
    monkeypatch.setattr(settings, "retention_audit_days", 0)
    _audit(db, 5000, "ancient")
    done = run()
    assert "audit_log" not in done
    assert "ancient" in {r[0] for r in db.execute(text("SELECT action FROM audit_log"))}


# -- the result of each run is audited ------------------------------------------------------------

def test_each_rule_writes_its_result_to_the_audit_log(db, machine, run):
    _ticket(db, machine, "closed", 800)
    _alert(db, machine, True, 400)
    run()
    rows = db.execute(text("SELECT resource, detail FROM audit_log WHERE action = 'retention_cleanup'")).all()
    by_resource = dict(rows)
    assert by_resource["tickets"] == "deleted 1 closed tickets older than 730 days"
    assert by_resource["alerts"] == "deleted 1 resolved alerts older than 365 days"
    assert by_resource["audit_log"].startswith("deleted ")
    assert by_resource["telemetry"] == "deleted 0 rows older than 90 days"


def test_readings_are_still_deleted_after_90_days(db, machine, run):
    db.add(Telemetry(device_id=machine.id, temperature=1.0, recorded_at=_ago(91)))
    db.add(Telemetry(device_id=machine.id, temperature=2.0, recorded_at=_ago(89)))
    db.flush()
    run()
    assert db.query(Telemetry).filter(Telemetry.device_id == machine.id).count() == 1


# -- batches ------------------------------------------------------------------------------------------------

class _CountingCommits:
    def __init__(self, session):
        self._session = session
        self.commits = 0

    def close(self):
        pass

    def commit(self):
        self.commits += 1
        return self._session.commit()

    def __getattr__(self, name):
        return getattr(self._session, name)


def test_a_large_purge_is_deleted_in_batches_with_a_commit_per_batch(db, machine, monkeypatch):
    monkeypatch.setattr(retention, "_BATCH_SIZE", 2)
    for i in range(5):
        db.add(Telemetry(device_id=machine.id, temperature=float(i), recorded_at=_ago(200 + i)))
    db.add(Telemetry(device_id=machine.id, temperature=99.0, recorded_at=_ago(1)))
    db.flush()
    db.expunge_all()
    session = _CountingCommits(db)
    result = retention.run_retention(lambda: session, now=NOW)
    assert result["telemetry"] == 5
    left = db.execute(text("SELECT temperature FROM telemetry")).all()
    assert [r[0] for r in left] == [99.0]
    # five rows in batches of two are three statements, so at least three commits for the readings alone
    assert session.commits >= 3 + 3


def test_a_purge_that_is_an_exact_multiple_of_the_batch_ends_cleanly(db, machine, monkeypatch):
    monkeypatch.setattr(retention, "_BATCH_SIZE", 2)
    for i in range(4):
        db.add(Telemetry(device_id=machine.id, temperature=float(i), recorded_at=_ago(300 + i)))
    db.flush()
    db.expunge_all()
    result = retention.run_retention(lambda: _KeepOpen(db), now=NOW)
    assert result["telemetry"] == 4
    assert db.execute(text("SELECT count(*) FROM telemetry")).scalar() == 0


def test_batches_do_not_delete_what_the_rules_keep(db, machine, monkeypatch):
    monkeypatch.setattr(retention, "_BATCH_SIZE", 1)
    keep = _alert(db, machine, False, 5000)
    gone = [_alert(db, machine, True, 400 + i) for i in range(3)]
    db.flush()
    db.expunge_all()
    retention.run_retention(lambda: _KeepOpen(db), now=NOW)
    assert _exists(db, Alert, keep)
    assert not any(_exists(db, Alert, g) for g in gone)


def test_the_unresolved_rule_alerts_are_never_deleted_by_age(db, machine, run):
    # a breaching rule writes an alert on every reading and nothing resolves it, so unresolved ones can pile up;
    # an operator may still need each of them, so no rule deletes them
    old = [_alert(db, machine, False, 3000 + i) for i in range(3)]
    run()
    assert all(_exists(db, Alert, a) for a in old)


# -- sign-in sessions, status case, logging and the scheduler's zone ---------------------------------------

def _session(db, user_id, expires_days_ago, revoked=False):
    db.execute(
        text(
            "INSERT INTO user_sessions (id, user_id, current_jti, expires_at, revoked_at) "
            "VALUES (gen_random_uuid(), CAST(:u AS uuid), :j, :e, :r)"
        ),
        {"u": str(user_id), "j": secrets.token_hex(8), "e": _ago(expires_days_ago), "r": _ago(1) if revoked else None},
    )


def _sessions(db):
    return db.execute(text("SELECT count(*) FROM user_sessions")).scalar()


@pytest.fixture
def user_id(db):
    from app.models.user import User
    u = User(name="S", email=f"s-{secrets.token_hex(3)}@test.com", password_hash="x", role="viewer")
    db.add(u)
    db.flush()
    return u.id


def test_sessions_expired_for_over_a_day_are_deleted_and_the_rest_kept(db, user_id, run):
    _session(db, user_id, 3)
    _session(db, user_id, 2, revoked=True)
    # expired less than a day ago: a revoked row stays until a day past its expiry
    _session(db, user_id, 0.5, revoked=True)
    # still valid
    _session(db, user_id, -7)
    _session(db, user_id, -7, revoked=True)
    done = run()
    assert done["user_sessions"] == 2
    assert _sessions(db) == 3


def test_the_session_purge_is_batched_and_audited(db, user_id, monkeypatch):
    monkeypatch.setattr(retention, "_BATCH_SIZE", 2)
    for _ in range(5):
        _session(db, user_id, 10)
    db.flush()
    db.expunge_all()
    retention.run_retention(lambda: _KeepOpen(db), now=NOW)
    assert _sessions(db) == 0
    detail = db.execute(text("SELECT detail FROM audit_log WHERE resource = 'user_sessions'")).scalar()
    assert detail == "deleted 5 sign-in sessions expired for over a day"


def test_a_closed_ticket_is_found_whatever_the_case_of_its_status(db, machine, run):
    ticket = _ticket(db, machine, "Closed", 800)
    run()
    assert not _exists(db, Ticket, ticket)


def test_a_failed_rule_logs_the_error_type_and_not_its_text(caplog):
    class _Session:
        def execute(self, *a, **k):
            raise ValueError("secret value from a row")

        def rollback(self):
            pass

    with caplog.at_level("WARNING"):
        assert retention._purge(_Session(), "tickets", "tickets", "x < :cutoff", NOW, "closed tickets") is None
    assert "ValueError" in caplog.text
    assert "secret value" not in caplog.text


def test_the_scheduler_runs_in_utc(monkeypatch):
    made = {}

    class _Scheduler:
        def __init__(self, **kwargs):
            made.update(kwargs)

        def add_job(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(retention, "BackgroundScheduler", _Scheduler)
    retention.start_retention_scheduler()
    assert made["timezone"] == "UTC" and made["daemon"] is True


def test_used_invitation_records_older_than_three_days_are_deleted(db, run):
    for name, days in (("old1", 4), ("old2", 10), ("recent", 1)):
        db.execute(text("INSERT INTO used_invites (token_hash, used_at) VALUES (:h, :t)"), {"h": name, "t": _ago(days)})
    done = run()
    assert done["used_invites"] == 2
    assert [r[0] for r in db.execute(text("SELECT token_hash FROM used_invites"))] == ["recent"]


def test_invitations_expired_for_over_thirty_days_are_deleted_whatever_became_of_them(db, run):
    from app.models.invitation import Invitation

    def invite(name, expired_days_ago, **extra):
        row = Invitation(token_hash=name * 8, email=f"{name}@example.com", role="viewer", expires_at=_ago(expired_days_ago), **extra)
        db.add(row)
        return row

    invite("aaaaaaaa", 31)
    invite("bbbbbbbb", 90, used_at=_ago(91))
    invite("cccccccc", 45, cancelled_at=_ago(46))
    invite("dddddddd", 29)
    invite("eeeeeeee", -2)
    done = run()
    assert done["invitations"] == 3
    left = sorted(r[0] for r in db.execute(text("SELECT email FROM invitations")))
    assert left == ["dddddddd@example.com", "eeeeeeee@example.com"]


def test_the_scheduler_also_runs_the_nightly_model_retrain(monkeypatch):
    jobs = {}

    class _Scheduler:
        def __init__(self, **kwargs):
            pass

        def add_job(self, func, **kwargs):
            jobs[kwargs.get("id")] = (func, kwargs)

        def start(self):
            pass

    from app.tasks import model_retrain
    monkeypatch.setattr(retention, "BackgroundScheduler", _Scheduler)
    retention.start_retention_scheduler()
    func, kwargs = jobs["model_retrain"]
    assert func is model_retrain.run_nightly_job
    assert (kwargs["hour"], kwargs["minute"]) == (model_retrain.RETRAIN_HOUR_UTC, model_retrain.RETRAIN_MINUTE_UTC)
    assert kwargs["max_instances"] == 1 and kwargs["coalesce"] is True


def test_the_invitation_purge_is_batched_and_audited(db, monkeypatch):
    monkeypatch.setattr(retention, "_BATCH_SIZE", 2)
    for i in range(5):
        db.execute(text("INSERT INTO used_invites (token_hash, used_at) VALUES (:h, :t)"), {"h": f"h{i}", "t": _ago(9)})
    db.flush()
    db.expunge_all()
    retention.run_retention(lambda: _KeepOpen(db), now=NOW)
    assert db.execute(text("SELECT count(*) FROM used_invites")).scalar() == 0
    detail = db.execute(text("SELECT detail FROM audit_log WHERE resource = 'used_invites'")).scalar()
    assert detail == "deleted 5 used invitation records older than 3 days"
