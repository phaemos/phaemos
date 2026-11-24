"""
Liveness Service - notices a node that has gone silent.

Every post is a heartbeat. A sweep, run by the scheduler that also runs the retention task, reads the age of each
device's last post and sets its link state:

    online   the last post is at most 4 expected intervals old
    late     older than 4 intervals
    offline  older than 12 intervals

Once a device has been silent for 2 minutes the sweep opens one monitoring alert for it. A post sets the link state
back to online at once and resolves that alert, with the outage length in its message. The sweep also resolves a
restart-loop alert once the boots have stopped.

devices.status keeps the two words older clients know. A post sets it to "online" as it always did. The sweep sets
it to "offline" when the link state becomes offline, whatever it held before (a status set by hand to warning or
fault is replaced then) and back to "online" when the link state recovers.

The state always comes from the real age of the last post. The start-up grace only holds back bad news: while this
process is younger than the offline threshold a device is never moved towards late or offline and no alert opens,
so an API that was down or restarted does not make live nodes look silent. It never moves a device towards online,
never closes an alert and never restarts the age used for the 24 hour limit, so a node that was already dead stays
dead across a restart.

The pass reads only the devices that can need a change (not online, late by age or with an open alert), takes a
FOR NO KEY UPDATE lock on them so posts are not blocked and runs a fixed number of queries whatever the fleet size.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import DateTime, bindparam, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.db import engine
from app.models.alert import Alert
from app.models.device import Device
from app.models.device_health import DeviceHealth
from app.models.maintenance import MaintenanceWindow
from app.services import alert_service, cooldown
from app.services.health_service import (
    HAND_RESOLVED_HOLD_S, HAND_RESOLVED_SUFFIX, RESET_LOOP_SUFFIX, open_alert_of_kind,
)

logger = logging.getLogger(__name__)

# a device is late after this many expected intervals without a post and offline after this many
LATE_AFTER_INTERVALS = 4
OFFLINE_AFTER_INTERVALS = 12
# the monitoring alert opens once a device has been silent this long and its text says so
OFFLINE_ALERT_AFTER_S = 120
OFFLINE_SUFFIX = "has not reported for 2 minutes"
# a device silent for longer than this is shown as offline but raises no new alert, judged by its real age. The first
# sweep after an upgrade finds machines that stopped long ago (the old status never went back to offline) and must
# not report each of them as news
OFFLINE_ALERT_MAX_AGE_S = 24 * 3600
# how often the scheduler runs the sweep
SWEEP_INTERVAL_S = 15
# the lock is shorter than the interval, so the next run is never blocked and longer than the spread between two
# workers' timers, so only one of them runs each round. If the timers drift further apart a second pass may run,
# which the row locks make harmless
LOCK_KEY = "phaemos:liveness-sweep"
LOCK_SECONDS = 10

_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# when this process started. While it is younger than a device's offline threshold the sweep holds back bad news for
# that device. See the module note and mark_started
_started_at: datetime | None = None

_RANK = {"online": 0, "late": 1, "offline": 2}


def mark_started(now: datetime | None = None) -> None:
    global _started_at
    _started_at = now or datetime.now(timezone.utc)


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def link_state_for(age_s: float, interval_s: int) -> str:
    interval = max(1, interval_s or 5)
    if age_s > OFFLINE_AFTER_INTERVALS * interval:
        return "offline"
    if age_s > LATE_AFTER_INTERVALS * interval:
        return "late"
    return "online"


def effective_link_state(stored: str, last_seen: datetime | None, interval_s: int, now: datetime) -> str:
    """
    The link state to show: the worse of the one the sweep stored and the one the age of the last post implies.

    The stored state lags by up to a sweep (15 seconds) and a device that has never posted has no age, so its stored state
    stands. This is the rule the summary uses so its counts agree with a machine's own read.
    """
    stored = stored if stored in _RANK else "offline"
    if last_seen is None:
        return stored
    implied = link_state_for((now - _aware(last_seen)).total_seconds(), interval_s)
    return implied if _RANK[implied] > _RANK[stored] else stored


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


def close_alert(alert: Alert, silent_since: datetime | None, now: datetime, ended: datetime | None = None) -> None:
    """
    Resolve a silent-node alert and put how long the node was silent in its message.

    The outage runs from silent_since (the alert's own time when unknown) to `ended`, which is `now` unless the node
    is known to have come back earlier.
    """
    since = _aware(silent_since) if silent_since is not None else _aware(alert.triggered_at)
    alert.resolved = True
    alert.resolved_at = now
    length = ((ended or now) - since).total_seconds()
    alert.message = f"{alert.message} (back online after {format_duration(length)})"


def resolve_offline_alert(db: Session, device: Device, silent_since: datetime | None, now: datetime) -> bool:
    """Close the device's open silent-node alert and record how long it was silent. True when one was open."""
    alert = open_alert_of_kind(db, device.id, OFFLINE_SUFFIX)
    if alert is None:
        return False
    close_alert(alert, silent_since, now)
    return True


def _suppressed(db: Session, now: datetime) -> tuple[bool, set]:
    """The maintenance windows active at `now`, read once per pass: whether one covers every machine and the ids."""
    rows = db.query(MaintenanceWindow.device_id).filter(
        MaintenanceWindow.start_at <= now,
        MaintenanceWindow.end_at >= now,
        MaintenanceWindow.suppress_alerts.is_(True),
    ).all()
    return any(r[0] is None for r in rows), {r[0] for r in rows if r[0] is not None}


def sweep(
    db: Session,
    now: datetime | None = None,
    started_at: datetime | None = None,
    background_tasks=None,
) -> dict:
    """
    Run one pass over the devices that can need a change. The clock is a parameter so a test needs no waiting.

    Row locks (FOR NO KEY UPDATE, which does not block a post's insert or its device update) keep a node's own post
    and this pass from overwriting each other: a device a post is writing is skipped and is fresh anyway.
    Notifications go out after the commit, so no lock is held across a vendor call. A fault on one device is logged
    and does not stop the others.
    """
    now = now or datetime.now(timezone.utc)
    started = started_at if started_at is not None else _started_at

    # a device needs a look when it is not online, when its last post is older than the late threshold or when it
    # has a node-wide monitoring alert open (a silent node or a restart loop). Sensor alerts are run by the post
    late_by_age = text(
        "devices.last_seen < :now - make_interval(secs => devices.expected_interval_s * :late)"
    ).bindparams(
        bindparam("now", value=now, type_=DateTime(timezone=True)),
        bindparam("late", value=LATE_AFTER_INTERVALS),
    )
    open_alert_devices = select(Alert.device_id).where(
        Alert.category == "monitoring", Alert.resolved.is_(False), Alert.sensor_key.is_(None)
    )
    devices = (
        db.query(Device)
        .filter(
            Device.last_seen.isnot(None),
            or_(Device.link_state != "online", late_by_age, Device.id.in_(open_alert_devices)),
        )
        # lock the devices rows only. Device loads its owner with a LEFT OUTER JOIN and PostgreSQL refuses to lock
        # the nullable side of an outer join
        .with_for_update(key_share=True, skip_locked=True, of=Device)
        .all()
    )
    summary = {"online": 0, "late": 0, "offline": 0, "alerts_opened": 0, "alerts_resolved": 0}
    # a rule alert whose readings stopped (a silent node, a faulted sensor) must not stay open as "still occurring" for ever;
    # it shows as not occurring once its last_seen_at is old and one statement closes it after STALE_CLOSE_SECONDS
    stale = db.execute(
        update(Alert)
        .where(
            Alert.kind == "rule",
            Alert.resolved.is_(False),
            Alert.last_seen_at < now - timedelta(seconds=alert_service.STALE_CLOSE_SECONDS),
        )
        .values(
            resolved=True, resolved_at=now,
            message=Alert.message.concat(" (closed: no reading met the condition for an hour)"),
        )
    ).rowcount
    summary["alerts_resolved"] += stale
    if not devices:
        if stale:
            db.commit()
        return summary
    ids = [d.id for d in devices]

    health = {h.device_id: h for h in db.query(DeviceHealth).filter(DeviceHealth.device_id.in_(ids))}
    # every open node-wide monitoring alert in one query, so the pass costs no query per device
    open_alerts: dict[tuple, Alert] = {}
    for alert in db.query(Alert).filter(
        Alert.device_id.in_(ids), Alert.category == "monitoring", Alert.resolved.is_(False), Alert.sensor_key.is_(None)
    ):
        for suffix in (OFFLINE_SUFFIX, RESET_LOOP_SUFFIX):
            if (alert.message or "").endswith(suffix):
                open_alerts[(alert.device_id, suffix)] = alert
    everywhere, held = _suppressed(db, now)
    # a silent-node alert that a person resolved by hand is not raised again for an hour, whatever the node does meanwhile
    by_hand = {
        row[0] for row in db.query(Alert.device_id).filter(
            Alert.device_id.in_(ids), Alert.kind == "offline", Alert.resolved.is_(True),
            Alert.resolved_at >= now - timedelta(seconds=HAND_RESOLVED_HOLD_S),
            Alert.message.endswith(HAND_RESOLVED_SUFFIX),
        )
    }

    to_notify: list[tuple[object, str, str]] = []
    for device in devices:
        try:
            _sweep_device(
                db, device, now, started, health.get(device.id), open_alerts,
                everywhere or device.id in held or device.id in by_hand, summary, to_notify,
            )
        except Exception as exc:
            logger.warning("Liveness sweep skipped one device (%s)", type(exc).__name__)

    if to_notify:
        # one INSERT for every new alert. ON CONFLICT DO NOTHING is the database's own refusal of a second open alert of
        # the kind for a device (migration 020), so a pass that raced a post or another worker adds nothing for it and
        # only the devices that really got an alert are told about
        opened = {
            row[0] for row in db.execute(
                insert(Alert).values([
                    {
                        "id": uuid.uuid4(), "device_id": who.id, "rule_id": None, "message": message,
                        "severity": "warning", "resolved": False, "category": "monitoring", "kind": "offline",
                    }
                    for who, _, message in to_notify
                ]).on_conflict_do_nothing().returning(Alert.device_id)
            )
        }
        to_notify = [item for item in to_notify if item[0].id in opened]
        summary["alerts_opened"] = len(to_notify)
    db.commit()
    for snapshot, kind, message in to_notify:
        alert_service.notify_monitoring(background_tasks, snapshot, kind, message)
    return summary


def _sweep_device(db, device, now, started, row, open_alerts, in_maintenance, summary, to_notify) -> None:
    interval = max(1, device.expected_interval_s or 5)
    age = (now - _aware(device.last_seen)).total_seconds()
    real = link_state_for(age, interval)
    was = device.link_state
    state = real
    # the start-up grace holds back bad news only: a device is never moved towards late or offline while this
    # process is younger than the offline threshold. Good news needs a real post, so it is never held back
    in_grace = started is not None and (now - started).total_seconds() < OFFLINE_AFTER_INTERVALS * interval
    if in_grace and _RANK[real] > _RANK.get(was, 0):
        state = was
    summary[state] = summary.get(state, 0) + 1

    if state != was:
        device.link_state = state
    if state == "offline":
        if device.status != "offline":
            device.status = "offline"
    elif was == "offline" and device.status == "offline":
        device.status = "online"

    offline_alert = open_alerts.get((device.id, OFFLINE_SUFFIX))
    if state == "offline":
        if (
            offline_alert is None
            and not in_grace
            and OFFLINE_ALERT_AFTER_S <= age <= OFFLINE_ALERT_MAX_AGE_S
            and not in_maintenance
        ):
            # collected and inserted together at the end of the pass, in one statement
            to_notify.append((SimpleNamespace(id=device.id, name=device.name), "offline", f"{device.name} {OFFLINE_SUFFIX}"))
    elif offline_alert is not None and real != "offline":
        # the node is back by some route other than a post (a longer interval was set, say). Judged by the real age
        # and never by the grace, so a restart cannot close an alert for a node that is still silent. The outage
        # ran from two minutes before the alert opened to the node's latest post
        close_alert(
            offline_alert,
            _aware(offline_alert.triggered_at) - timedelta(seconds=OFFLINE_ALERT_AFTER_S),
            now,
            ended=_aware(device.last_seen),
        )
        summary["alerts_resolved"] += 1

    # a restart loop clears once ten minutes pass without three boots
    loop_alert = open_alerts.get((device.id, RESET_LOOP_SUFFIX))
    if loop_alert is not None and (row is None or not row.in_reset_loop(now)):
        loop_alert.resolved = True
        loop_alert.resolved_at = now
        loop_alert.message = f"{loop_alert.message} (no restart since)"
        summary["alerts_resolved"] += 1


def run_sweep_job(session_factory=_SessionLocal, now: datetime | None = None) -> bool:
    """
    The scheduled job. Takes the lock first, so two API workers running it do not both act. The lock falls back to
    process memory when Redis is unreachable (see cooldown.py) and the row locks and the one-open-alert check in
    sweep still keep a second pass from doing harm. True when this call ran the sweep.
    """
    if not cooldown.acquire(LOCK_KEY, LOCK_SECONDS):
        return False
    db = session_factory()
    try:
        sweep(db, now=now)
        return True
    except Exception as exc:
        db.rollback()
        logger.warning("Liveness sweep failed (%s)", type(exc).__name__)
        return False
    finally:
        db.close()
