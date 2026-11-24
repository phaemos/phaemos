"""
The nightly retrain (tasks/model_retrain.py), run with an injected clock and an injected trainer so no model is fitted.
The guard of the retrain itself (a refused model never replaces one in service) is tested in test_ml_model.py.
"""
from datetime import datetime, timezone

import pytest

from app.services import cooldown
from app.tasks import model_retrain as mr

NIGHT = datetime(2031, 5, 4, 3, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _free_locks():
    def clear():
        cooldown.release(mr.RUNNING_KEY)
        for day in range(1, 8):
            cooldown.release(mr.DAY_KEY.format(day=f"2031050{day}"))
    clear()
    yield
    clear()


class _Spy:
    def __init__(self, action="retrain", fail=False):
        self.calls, self.audits, self.action, self.fail = [], [], action, fail

    def trainer(self, trigger, now):
        self.calls.append((trigger, now))
        if self.fail:
            raise RuntimeError("boom")
        return self.action, "summary"

    def audit(self, actor, action, detail):
        self.audits.append((actor, action, detail))


def test_the_job_retrains_once_a_night_however_many_workers_wake():
    spy = _Spy()
    assert mr.run_nightly_job(NIGHT, spy.trainer, spy.audit) is True
    assert mr.run_nightly_job(NIGHT, spy.trainer, spy.audit) is False
    assert len(spy.calls) == 1 and spy.calls[0] == ("nightly", NIGHT)
    assert spy.audits == [("system", "retrain", "summary")]


def test_the_next_night_runs_again():
    spy = _Spy()
    assert mr.run_nightly_job(NIGHT, spy.trainer, spy.audit)
    next_night = NIGHT.replace(day=5)
    assert mr.run_nightly_job(next_night, spy.trainer, spy.audit)
    assert len(spy.calls) == 2


def test_a_refused_retrain_is_recorded_and_the_lock_is_freed():
    spy = _Spy(action="retrain_refused")
    assert mr.run_nightly_job(NIGHT, spy.trainer, spy.audit)
    assert spy.audits[0][1] == "retrain_refused"
    # the running lock is free again, so a manual retrain may follow
    assert mr.run_retrain("admin", "manual", trainer=spy.trainer, audit=spy.audit) is True


def test_a_retrain_that_is_already_running_blocks_the_nightly_one_and_the_manual_one():
    assert cooldown.acquire(mr.RUNNING_KEY, 60)
    spy = _Spy()
    assert mr.run_nightly_job(NIGHT, spy.trainer, spy.audit) is False
    assert mr.run_retrain("admin", "manual", trainer=spy.trainer, audit=spy.audit) is False
    assert spy.calls == []
    assert [a[1] for a in spy.audits] == ["retrain_skipped", "retrain_skipped"]
    cooldown.release(mr.RUNNING_KEY)
    # the night was not used up by the blocked attempt
    assert mr.run_nightly_job(NIGHT, spy.trainer, spy.audit) is True


def test_the_running_lock_is_freed_when_the_trainer_fails():
    spy = _Spy(fail=True)
    with pytest.raises(RuntimeError):
        mr.run_retrain("admin", "manual", trainer=spy.trainer, audit=spy.audit)
    assert cooldown.acquire(mr.RUNNING_KEY, 60)


def test_the_schedule_is_a_quiet_hour_and_the_next_run_is_computed_from_the_clock():
    assert (mr.RETRAIN_HOUR_UTC, mr.RETRAIN_MINUTE_UTC) == (3, 30)
    before = datetime(2031, 5, 4, 1, 0, tzinfo=timezone.utc)
    after = datetime(2031, 5, 4, 4, 0, tzinfo=timezone.utc)
    assert mr.next_run(before) == NIGHT
    assert mr.next_run(after) == NIGHT.replace(day=5)
    assert mr.next_run(NIGHT) == NIGHT.replace(day=5)
    assert mr.schedule(before) == {"nightly_utc": "03:30", "next_at": NIGHT.isoformat()}


def test_the_default_trainer_keeps_the_serving_model_when_the_fleet_cannot_be_read(monkeypatch):
    monkeypatch.setattr(mr, "fleet", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    action, detail = mr.train_and_save("nightly")
    assert action == "retrain_error" and "untouched" in detail and "RuntimeError" in detail


def test_the_default_trainer_with_no_machines_saves_nothing(monkeypatch, tmp_path):
    from app.services import ml_service
    monkeypatch.setattr(ml_service, "MODEL_PATH", str(tmp_path / "model.pkl"))
    monkeypatch.setattr(mr, "fleet", lambda: [])
    action, _ = mr.train_and_save("nightly", NIGHT)
    assert action == "retrain_refused"
    assert not (tmp_path / "model.pkl").exists()
    assert ml_service.last_retrain()["trigger"] == "nightly"
