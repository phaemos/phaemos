"""
Alert Service - evaluates a new telemetry reading against all alert rules for a device and keeps one alert for each rule
that is breached and decides the model's anomaly alert from the machine's recent scored readings.

A rule alert is one row for as long as its condition lasts. It is raised once the condition has held for the rule's
for_seconds, it is updated in place while the condition goes on (occurrences, last and peak value) and it resolves by itself
once the value has been back inside the limit by the rule's margin for at least 60 seconds. People are told on the raise, on a
rise to critical and as a reminder once an hour and never for each reading.
"""

import functools
import logging
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertRule, RuleState
from app.models.device import Device
from app.models.maintenance import MaintenanceWindow
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.models.user import User
from app.services.maintenance_service import is_in_maintenance
from app.config import settings
from app.services.alert_state import add_alert, lock_device
from app.services import anomaly_decision, detector_store, ml_service, cooldown, rule_metrics, email_service, notify_pool, notify_service, sms_service, webhook_service


logger = logging.getLogger(__name__)

_CONDITIONS = {
    "gt": lambda val, threshold: val > threshold,
    "lt": lambda val, threshold: val < threshold,
    "eq": lambda val, threshold: val == threshold,
}


# a rule that stays breached notifies when its alert is raised, when it rises to critical and then as a reminder and each
# channel (email, SMS, Discord and webhooks) also repeats at most once an hour for the same device, metric and severity
NOTIFY_COOLDOWN_SECONDS = 60 * 60
# how long an open rule alert goes without a notification before it sends a reminder
REMINDER_SECONDS = 60 * 60
# what a channel's notify function answers: queued a send or held back by its repeat window. Anything else (not set up,
# not wanted, over its daily cap) is None
_SENT, _HELD = "sent", "held"
# the value must be back inside the limit for at least this long before the alert resolves, whatever for_seconds is
MIN_CLEAR_HOLD_SECONDS = 60
# a gap between readings longer than this many intervals (and at least 30 seconds) breaks a hold, so a silent stretch is not
# counted as the condition lasting
GAP_INTERVALS = 3
# an open rule alert whose readings stopped (a silent node, a faulted sensor) is closed after this long with no reading that
# carried the metric. Until then it shows as not still occurring
STALE_CLOSE_SECONDS = 60 * 60
# a rule alert that a person resolved by hand while the condition went on is not raised again for this long
HAND_RESOLVED_HOLD_SECONDS = 60 * 60
# info alerts stay silent on email and SMS to avoid alert fatigue
_EMAIL_SEVERITIES = {"critical", "warning"}
# the metric name an anomaly alert uses in its window key
ANOMALY_METRIC = "anomaly"


def _dispatch(background_tasks: BackgroundTasks | None, fn, *args, _critical: bool = False, _undo=None, **kwargs) -> None:
    """
    Hand a vendor call to the notify pool (services/notify_pool.py), after the response when there is one.

    The request thread only queues a small job that submits to the pool, so a send that waits for its whole timeout never
    holds a request thread. A critical job is taken before the others and never dropped. `_undo` runs if the pool drops
    the job, so a daily-cap reservation is given back.
    """
    job = functools.partial(fn, *args, **kwargs)

    def hand_over() -> None:
        notify_pool.submit(job, critical=_critical, undo=_undo)

    if background_tasks is not None:
        background_tasks.add_task(hand_over)
    else:
        hand_over()


# the window a target is held for from the moment its send is queued and the wait after a send that failed. A window of
# the whole hour is taken only once the vendor has accepted the message. Freeing the window after a failure would try a dead
# endpoint on every reading and holding the hour from the start would hide the alert for that long after a blip or a store
# that could not be reached
FAILED_SEND_RETRY_SECONDS = 60


def _forget_notification(alert_id) -> None:
    """Mark an alert as not yet notified, so the next reading that finds it open sends again. Its own short session."""
    from sqlalchemy import update

    from app.db import SessionLocal

    db = SessionLocal()
    try:
        db.execute(update(Alert).where(Alert.id == alert_id).values(notified_at=None))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not reset an alert's notification time (%s)", type(exc).__name__)
    finally:
        db.close()


# the function above under a name nothing replaces, so a test can run the real one while the others stand it in
_REAL_FORGET_NOTIFICATION = _forget_notification


def _failure_hook(alert_id):
    return functools.partial(_forget_notification, alert_id) if alert_id is not None else None


def _run_guarded(key: str, fn, _reserved=None, _on_failure=None, **kwargs) -> None:
    # the window starts at FAILED_SEND_RETRY_SECONDS when the send is queued. A send that goes through extends it to the
    # hour. One that fails leaves it to run out after a minute, so a vendor blip does not silence the alert for the
    # hour and a dead endpoint is tried once a minute and not on every reading.
    # _reserved is (channel, amount): the daily cap was reserved before the send and a failed send gives it back
    try:
        sent = fn(**kwargs)
    except Exception as exc:
        logger.warning("alert notification failed (%s)", type(exc).__name__)
        sent = False
    if sent:
        cooldown.extend(key, NOTIFY_COOLDOWN_SECONDS)
        return
    if _reserved:
        # one reservation (channel, amount) or a list of them (the site's count and the machine's own)
        for held in ([_reserved] if isinstance(_reserved, tuple) else _reserved):
            cooldown.give_back_daily(*held)
    # a rule alert whose notification failed is marked unnotified, so the next reading sends it again (the 60 second window
    # keeps that to one try a minute)
    if _on_failure is not None:
        _on_failure()


def _write_cap_audit(channel: str, cap: int) -> None:
    # its own short session: this can run on the ingest path, which has no session of its own to spare
    from app.db import SessionLocal
    from app.services import audit_service

    db = SessionLocal()
    try:
        audit_service.log_action(
            db, "system", "alert_cap_reached", channel, None,
            f"{channel} alerts paused until 00:00 UTC: the daily limit of {cap} was reached",
        )
    finally:
        db.close()


# the writer above under a name nothing replaces, so a test can run the real one while the others stand it in
_REAL_WRITE_CAP_AUDIT = _write_cap_audit


def _cap_reached(channel: str, cap: int) -> None:
    """
    Say so, once a day, when a channel's daily limit stops alerts.

    Alert rows belong to a machine, so there is no device-free alert row to raise for the deployment. The warning goes
    to the log and an entry to the audit log, which the admin reads. It is written once per channel per UTC day.
    """
    now = datetime.now(timezone.utc)
    seconds = int((cooldown._end_of_utc_day(now) - now).total_seconds()) + 1
    if not cooldown.acquire(f"phaemos:cap-notice:{channel}:{now:%Y%m%d}", seconds):
        return
    logger.warning("alert %s paused until 00:00 UTC: the daily limit of %s was reached", channel, cap)
    try:
        _write_cap_audit(channel, cap)
    except Exception as exc:
        logger.warning("could not record the alert limit in the audit log (%s)", type(exc).__name__)


def reserve_daily_send(channel: str, device: Device, amount: int, cap: int, critical: bool):
    """
    Reserve amount of today's allowance for a send: the machine's own share and the site's total.

    Returns the list of reservations made (to give back if the send fails) or None when the send must not go, with the reason
    in _CAP_REFUSED. A machine may use its share and no more, so one noisy or hostile machine cannot spend the site's
    allowance. A warning may use the site's allowance only up to the part left after the critical reserve, so a machine
    that is in real trouble can still be told about even when the others have been chatty.
    """
    machine_cap = min(cap, max(int(cap * settings.alert_machine_share), 10))
    reserve = int(cap * settings.alert_critical_reserve) if cap >= 10 else 0
    site_cap = cap if critical else max(0, cap - reserve)
    machine_channel = f"{channel}:{device.id}"
    if not cooldown.reserve_daily(machine_channel, amount, machine_cap):
        return None, machine_channel, machine_cap
    if not cooldown.reserve_daily(channel, amount, site_cap):
        cooldown.give_back_daily(machine_channel, amount)
        return None, channel, site_cap
    return [(channel, amount), (machine_channel, amount)], None, None


def _window_key(channel: str, device: Device, metric: str, severity: str) -> str:
    return f"phaemos:alert-notify:{channel}:{device.id}:{metric}:{severity}"


def _notify_email(background_tasks, device: Device, metric: str, severity: str, message: str, _alert_id=None) -> None:
    recipients = email_service.parse_recipients(settings.alert_email_to)
    # nothing is checked or sent unless email is configured and an alert address is set
    if severity not in _EMAIL_SEVERITIES or not recipients or not email_service.is_configured():
        return
    key = _window_key("email", device, metric, severity)
    if not cooldown.acquire(key, FAILED_SEND_RETRY_SECONDS):
        return _HELD
    # each recipient counts, as Resend counts them against its daily quota. The count is reserved before the send, in one
    # atomic step, so sends in flight at the same moment cannot together pass the cap and a failed send gives it back
    amount = len(recipients)
    held, refused, limit = reserve_daily_send("email", device, amount, settings.alert_email_daily_cap, severity == "critical")
    if held is None:
        cooldown.release(key)
        _cap_reached(refused, limit)
        return
    _dispatch(
        background_tasks,
        _run_guarded,
        key,
        notify_service.send_email_alert,
        _critical=severity == "critical",
        _undo=lambda: [cooldown.give_back_daily(*h) for h in held],
        _reserved=held,
        _on_failure=_failure_hook(_alert_id),
        subject=f"PHAEMOS [{severity.upper()}] {device.name}",
        body=message,
    )
    return _SENT


def _notify_discord(background_tasks, device: Device, metric: str, severity: str, message: str, _alert_id=None) -> None:
    # Discord is called from a background task for the same reason as email: it can hold the request for up to
    # its timeout and a node waits only a couple of seconds for its reply
    if not notify_service.discord_wanted(severity):
        return
    key = _window_key("discord", device, metric, severity)
    if not cooldown.acquire(key, FAILED_SEND_RETRY_SECONDS):
        return _HELD
    _dispatch(
        background_tasks, _run_guarded, key, notify_service.send_discord_alert,
        _critical=severity == "critical", _on_failure=_failure_hook(_alert_id), message=message, severity=severity,
    )
    return _SENT


def _notify_webhooks(background_tasks, db: Session, device: Device, metric: str, context: dict, _alert_id=None) -> None:
    # the webhooks are read here, while the session is open and delivered later from plain copies;
    # they are read before the window is taken so a deployment with none never spends a window on nothing
    targets = webhook_service.enabled_targets(db)
    if not targets:
        return
    key = _window_key("webhook", device, metric, context["severity"])
    if not cooldown.acquire(key, FAILED_SEND_RETRY_SECONDS):
        return _HELD
    _dispatch(
        background_tasks, _run_guarded, key, webhook_service.deliver_all,
        _critical=context["severity"] == "critical", _on_failure=_failure_hook(_alert_id),
        targets=targets, alert_context=context,
    )
    return _SENT


def notify_monitoring(background_tasks, device: Device, kind: str, message: str) -> None:
    """
    Tell people that monitoring has failed (a silent node, a restart loop), by email as a warning.

    It follows the same repeat window as any alert and never sends the critical text message: nothing here says the
    machine is in danger, only that it is not being watched.
    """
    _notify_email(background_tasks, device, f"monitoring-{kind}", "warning", message)


def notify_machine_warning(background_tasks, device: Device, metric: str, message: str) -> None:
    """Tell people about a warning on the machine itself that no rule raised (vibration beyond the sensor's range)."""
    _notify_discord(background_tasks, device, metric, "warning", message)
    _notify_email(background_tasks, device, metric, "warning", message)


def _phone_confirmed(owner: User) -> bool:
    """
    True when texts may go to the owner's number: it has been confirmed by a code sent to it. A number nobody confirmed could be
    anyone's and a technician could aim up to a day's texts at it. The confirmation is part of the account routes. Until the
    User model carries it (`phone_confirmed_at`) there is nothing to check and the number is trusted as before.
    """
    if not hasattr(owner, "phone_confirmed_at"):
        return True
    return getattr(owner, "phone_confirmed_at", None) is not None


def _notify_sms(background_tasks, db: Session, device: Device, window_metric: str, severity: str, send, _alert_id=None, **kwargs) -> None:
    # window_metric names the quiet window. It is not called metric because the
    # sender for a rule alert takes its own metric keyword through kwargs.
    # only critical alerts text - warning and info would cost too much on a paid channel;
    # the owner's phone number is fetched lazily so the query only runs for a critical alert.
    if severity != "critical" or not device.owner_id or not sms_service.is_configured():
        return
    owner = db.query(User).filter(User.id == device.owner_id).first()
    phone_number = owner.phone_number if owner else None
    if not phone_number or getattr(owner, "is_service", False) or not _phone_confirmed(owner):
        return
    key = _window_key("sms", device, window_metric, severity)
    if not cooldown.acquire(key, FAILED_SEND_RETRY_SECONDS):
        return _HELD
    held, refused, limit = reserve_daily_send("sms", device, 1, settings.alert_sms_daily_cap, True)
    if held is None:
        cooldown.release(key)
        _cap_reached(refused, limit)
        return
    _dispatch(
        background_tasks,
        _run_guarded,
        key,
        send,
        _critical=True,
        _undo=lambda: [cooldown.give_back_daily(*h) for h in held],
        _reserved=held,
        _on_failure=_failure_hook(_alert_id),
        phone_number=phone_number,
        device_name=device.name,
        **kwargs,
    )
    return _SENT


default_for_seconds = rule_metrics.default_for_seconds


def effective_for_seconds(rule: AlertRule) -> int:
    return rule.for_seconds if rule.for_seconds is not None else default_for_seconds(rule.metric)


default_clear_margin = rule_metrics.default_clear_margin


def effective_clear_margin(rule: AlertRule) -> float:
    return rule.clear_margin if rule.clear_margin is not None else default_clear_margin(rule.threshold)


def _back_inside(rule: AlertRule, value: float) -> bool:
    """True when the value is back inside the limit by the margin (an equality rule only needs the value to differ)."""
    margin = effective_clear_margin(rule)
    if rule.condition == "gt":
        return value <= rule.threshold - margin
    if rule.condition == "lt":
        return value >= rule.threshold + margin
    return value != rule.threshold


def _more_extreme(rule: AlertRule, value: float, peak: float | None) -> float:
    if peak is None:
        return value
    return min(peak, value) if rule.condition == "lt" else max(peak, value)


def _number(value) -> float:
    return float(value)


def _raised_by_hand_recently(db: Session, device: Device, rule: AlertRule, now: datetime) -> bool:
    return (
        db.query(Alert.id)
        .filter(
            Alert.device_id == device.id,
            Alert.rule_id == rule.id,
            Alert.kind == "rule",
            Alert.resolved.is_(True),
            Alert.resolved_at >= now - timedelta(seconds=HAND_RESOLVED_HOLD_SECONDS),
            Alert.message.endswith(" (resolved by hand)"),
        )
        .first()
    ) is not None


def daily_limits(now: datetime | None = None) -> dict:
    """
    Where today's daily email and text limits stand, for every signed-in role to see: the limit, how many are counted today, whether
    it is reached and when it resets (00:00 UTC). It carries no recipient and no address. Once a limit is reached no more of that
    channel go until it resets, so this is how an operator learns that messages have stopped.
    """
    now = now or datetime.now(timezone.utc)
    resets = cooldown._end_of_utc_day(now)
    out = {}
    for channel, limit in (("email", settings.alert_email_daily_cap), ("sms", settings.alert_sms_daily_cap)):
        used = cooldown.daily_used(channel, now)
        out[channel] = {
            "limit": limit, "count": used, "reached": used >= limit,
            "resets_at": resets.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
    return out


def _event_context(device: Device, alert: Alert, rule: AlertRule | None, reason: str) -> dict:
    """The figures a json webhook's event body carries about an alert and its machine."""
    return {
        "reason": reason,
        "device_id": str(device.id),
        "alert_id": str(alert.id),
        "kind": alert.kind or "rule",
        "condition": rule.condition if rule is not None else None,
        "peak_value": alert.peak_value,
        "occurrences": alert.occurrences,
        "message": alert.message,
        "triggered_at": alert.triggered_at,
        "first_seen_at": alert.first_seen_at,
    }


def notify_resolved(background_tasks, db: Session, device: Device, alert: Alert, rule: AlertRule | None = None) -> None:
    """
    Tell the json webhooks that an alert resolved (`alert.resolved`). Chat webhooks are not told: a resolve is not a new message
    anyone asked for. No repeat window: a resolve happens once. The delivery is a notify pool job like every other send.
    """
    targets = webhook_service.enabled_targets(db, only_json=True)
    if not targets:
        return
    context = {
        "device_name": device.name, "metric": rule.metric if rule is not None else None, "value": alert.last_value,
        "threshold": rule.threshold if rule is not None else None, "severity": alert.severity,
        **_event_context(device, alert, rule, "resolved"),
    }
    _dispatch(background_tasks, webhook_service.deliver_all, targets=targets, alert_context=context, event="alert.resolved")


def _tell_about_rule_alert(
    background_tasks, db: Session, device: Device, rule: AlertRule, alert: Alert, text: str, now: datetime,
    reason: str = "raised",
) -> None:
    """
    Notify on every channel for a rule alert and remember when. The hourly windows still apply to each channel.

    The time is kept only when something was queued or no channel was held back. When every channel was held by a window
    (a failed send waits a minute before its retry) the alert is still due its notification. Stamping it now would push
    the retry out to the next hourly reminder.
    """
    value = alert.last_value
    # the text goes first and is a critical job, so it is taken ahead of every other send and never waits behind a slow webhook
    results = [
        _notify_sms(
            background_tasks, db, device, rule.metric, alert.severity,
            sms_service.notify_critical,
            _alert_id=alert.id,
            metric=rule.metric,
            value=value,
            threshold=rule.threshold,
        ),
        _notify_discord(background_tasks, device, rule.metric, alert.severity, text, _alert_id=alert.id),
        _notify_email(background_tasks, device, rule.metric, alert.severity, text, _alert_id=alert.id),
        _notify_webhooks(background_tasks, db, device, rule.metric, {
            "device_name": device.name,
            "metric":      rule.metric,
            "value":       value,
            "threshold":   rule.threshold,
            "severity":    alert.severity,
            # what a json webhook adds to its event body (a chat webhook ignores it)
            **_event_context(device, alert, rule, reason),
        }, _alert_id=alert.id),
    ]
    if _SENT in results or _HELD not in results:
        alert.notified_at = now


def evaluate_rules(
    device: Device,
    reading: dict,
    db: Session,
    background_tasks: BackgroundTasks | None = None,
    now: datetime | None = None,
) -> None:
    """
    Keep each of the device's rule alerts up to date from one reading.

    For each rule: a value that meets the condition starts (or continues) a hold. Once it has held for for_seconds, without
    a gap in the readings, one alert is raised. While it goes on the one open alert is updated in place. When the value is back
    inside the limit by the margin it starts a clear hold and after the hold (for_seconds, at least 60 seconds) the alert
    resolves. A reading that does not carry the metric (the sensor is faulted or the node left it out) is no evidence either
    way: it breaks a pending hold and leaves an open alert as it is, its last_seen_at stops moving and the sweep closes it
    after STALE_CLOSE_SECONDS. A machine in a maintenance window is not evaluated.
    """
    rules = db.query(AlertRule).filter(AlertRule.device_id == device.id).all()

    # skip all alert processing while the device is in an active maintenance window
    # so planned downtime does not generate noise that technicians would have to dismiss.
    if is_in_maintenance(db, device.id):
        return
    if not rules:
        return

    now = now or datetime.now(timezone.utc)
    interval = max(1, device.expected_interval_s or 5)
    gap_limit = timedelta(seconds=max(30, GAP_INTERVALS * interval))
    states = {st.rule_id: st for st in db.query(RuleState).filter(RuleState.device_id == device.id)}
    open_alerts = {
        a.rule_id: a for a in db.query(Alert).filter(
            Alert.device_id == device.id, Alert.kind == "rule", Alert.resolved.is_(False)
        )
    }

    resolved_now: list = []
    for rule in rules:
        raw = reading.get(rule.metric)
        state = states.get(rule.id)
        if raw is None:
            # no evidence either way. A pending hold must not carry across the gap
            if state is not None and state.breach_since is not None:
                _reset_hold(state)
            continue
        value = _number(raw)
        if state is None:
            state = RuleState(rule_id=rule.id, device_id=device.id)
            db.add(state)
            states[rule.id] = state
        # a gap in the readings breaks both holds: it is not the condition lasting, nor the value being back inside
        if state.last_eval_at is not None and now - _aware(state.last_eval_at) > gap_limit:
            _reset_hold(state)
            state.clear_since = None
        state.last_eval_at = now

        check = _CONDITIONS.get(rule.condition)
        if check is None:
            continue
        alert = open_alerts.get(rule.id)
        for_s = effective_for_seconds(rule)

        if check(value, rule.threshold):
            state.clear_since = None
            if alert is None:
                if state.breach_since is None:
                    state.breach_since = now
                    state.hold_count, state.hold_peak = 0, None
                # the readings of the hold are counted as they come, so the alert's count and peak cover the qualifying period
                state.hold_count = (state.hold_count or 0) + 1
                state.hold_peak = _more_extreme(rule, value, state.hold_peak)
                if (now - _aware(state.breach_since)).total_seconds() < for_s:
                    continue
                # a person resolved this one by hand while it went on. It is not raised again for an hour and then it says so
                by_hand = _raised_by_hand_recently(db, device, rule, now)
                if by_hand:
                    continue
                raised = _raise_rule_alert(db, device, rule, value, now, state)
                if raised is None:
                    continue
                open_alerts[rule.id] = raised
                _tell_about_rule_alert(background_tasks, db, device, rule, raised, raised.message, now)
                continue
            # the alert goes on: update it in place
            alert.occurrences = (alert.occurrences or 0) + 1
            alert.last_value = value
            alert.peak_value = _more_extreme(rule, value, alert.peak_value)
            alert.last_seen_at = now
            escalated = rule.severity == "critical" and alert.severity != "critical"
            if escalated:
                alert.severity = "critical"
                _tell_about_rule_alert(background_tasks, db, device, rule, alert, f"{alert.message} (now critical)", now, "escalated")
            elif alert.notified_at is None or (now - _aware(alert.notified_at)).total_seconds() >= REMINDER_SECONDS:
                _tell_about_rule_alert(
                    background_tasks, db, device, rule, alert,
                    f"{alert.message} (still occurring: {alert.occurrences} readings, peak {alert.peak_value})",
                    now,
                    "reminder",
                )
            continue

        # the condition does not hold
        _reset_hold(state)
        if alert is None:
            state.clear_since = None
            continue
        if not _back_inside(rule, value):
            # between the threshold and the margin: neither occurring nor clear
            state.clear_since = None
            continue
        if state.clear_since is None:
            state.clear_since = now
        if (now - _aware(state.clear_since)).total_seconds() >= max(for_s, MIN_CLEAR_HOLD_SECONDS):
            alert.resolved = True
            alert.resolved_at = now
            alert.message = f"{alert.message} (resolved: back inside the limit)"
            state.clear_since = None
            open_alerts.pop(rule.id, None)
            resolved_now.append((alert, rule))

    db.commit()
    for alert, rule in resolved_now:
        # told after the commit, so a receiver that asks the API finds the alert resolved
        try:
            notify_resolved(background_tasks, db, device, alert, rule)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not queue the resolved event (%s)", type(exc).__name__)


def _reset_hold(state: RuleState) -> None:
    state.breach_since = None
    state.hold_count = 0
    state.hold_peak = None


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def _raise_rule_alert(db: Session, device: Device, rule: AlertRule, value: float, now: datetime, state: RuleState) -> Alert | None:
    """Open the one alert for the rule. None when the database already holds an open one (another post got there first)."""
    alert = Alert(
        device_id=device.id,
        rule_id=rule.id,
        message=f"{rule.metric} is {value} ({rule.condition} {rule.threshold}) on {device.name}",
        severity=rule.severity,
        resolved=False,
        kind="rule",
        # the hold's own readings count too: the machine was already outside the limit for as long as the hold lasted, so an
        # operator reading the peak sees the highest value of that spell and not only of the readings after the raise
        occurrences=max(1, state.hold_count or 1),
        last_value=value,
        peak_value=_more_extreme(rule, value, state.hold_peak),
        last_seen_at=now,
        triggered_at=now,
        first_seen_at=state.breach_since or now,
    )
    _reset_hold(state)
    if not add_alert(db, alert):
        return None
    return alert


ANOMALY_PREFIX = "Anomaly detected"
# the most scored readings one evaluation reads, so a very fast node cannot make the query large
ANOMALY_POINTS_LIMIT = 2000
# the longest the decision looks back: its clear window is the larger of 300 seconds and 60 intervals
ANOMALY_HISTORY_MIN_SECONDS = 300
ANOMALY_HISTORY_INTERVALS = 60


def _notify_anomaly(background_tasks, db: Session, device: Device, severity: str, message: str, peak: float) -> None:
    # the same window and daily caps as a rule, under the metric name "anomaly". The text goes first
    _notify_sms(
        background_tasks, db, device, ANOMALY_METRIC, severity,
        sms_service.notify_anomaly,
        score=peak,
    )
    _notify_discord(background_tasks, device, ANOMALY_METRIC, severity, message)
    _notify_email(background_tasks, device, ANOMALY_METRIC, severity, message)


def anomaly_history_seconds(interval: float) -> float:
    """How far back the decision needs the machine's scored readings: the module's own answer when it gives one."""
    own = getattr(anomaly_decision, "history_seconds", None)
    if callable(own):
        return own(interval)
    return max(ANOMALY_HISTORY_MIN_SECONDS, ANOMALY_HISTORY_INTERVALS * interval)


def _open_anomaly_alert(db: Session, device: Device) -> Alert | None:
    return (
        db.query(Alert)
        .filter(Alert.device_id == device.id, Alert.kind == "anomaly", Alert.resolved.is_(False))
        .first()
    )


def _explain_newest_over_boundary(db: Session, device: Device, points: list, cutoff: datetime) -> dict | None:
    """The per-sensor explanation of the newest over-boundary reading in the window or None when there is nothing to explain."""
    if not any(score >= anomaly_decision.BOUNDARY for _, score in points):
        return None
    row = (
        db.query(Telemetry)
        .filter(
            Telemetry.device_id == device.id,
            Telemetry.anomaly_score >= anomaly_decision.BOUNDARY,
            Telemetry.recorded_at >= cutoff,
        )
        .order_by(Telemetry.recorded_at.desc())
        .first()
    )
    if row is None:
        return None
    reading = {c.name: getattr(row, c.name) for c in Telemetry.__table__.columns}
    try:
        # explain reads the detector's stored state and never steps it, so it is called straight after the scoring, through the same store
        with detector_store.use(db):
            return ml_service.explain_reading(reading, device.id)
    except Exception:  # noqa: BLE001
        # an explanation is a nicety: the alert stands without it
        return None


def evaluate_anomaly(
    device: Device,
    db: Session,
    background_tasks: BackgroundTasks | None = None,
    now: datetime | None = None,
) -> None:
    """
    Raise, escalate, resolve or leave alone the model's anomaly alert for a device, as services/anomaly_decision.py decides.

    It gathers the machine's scored readings over the window the decision needs (a reading the model could not score is not
    evidence and is left out), asks `decide` and acts on the answer: raise opens one alert (and one ticket) and notifies,
    escalate turns the open warning into a critical alert and notifies once, resolve closes the open alert and none only
    keeps the open alert's figures current. A machine in a maintenance window is not evaluated. The device lock is held for
    the evaluation and the unique index refuses a second open alert, so two posts at once raise one.
    """
    if is_in_maintenance(db, device.id):
        return
    # one evaluation at a time for the device, so two posts at once cannot raise the alert and its ticket twice. The lock
    # is released by this function's commit
    lock_device(db, device.id)
    now = now or datetime.now(timezone.utc)
    interval = max(1, getattr(device, "expected_interval_s", None) or 5)
    cutoff = now - timedelta(seconds=anomaly_history_seconds(interval))
    rows = (
        db.query(Telemetry.recorded_at, Telemetry.anomaly_score)
        .filter(
            Telemetry.device_id == device.id,
            Telemetry.anomaly_score.isnot(None),
            Telemetry.recorded_at >= cutoff,
        )
        .order_by(Telemetry.recorded_at.desc())
        .limit(ANOMALY_POINTS_LIMIT)
        .all()
    )
    points = [(_aware(when), float(score)) for when, score in reversed(rows)]
    # a reading taken inside a maintenance window is not evidence about the machine, so the window's end cannot raise on it
    windows = [(_aware(a), _aware(b)) for a, b in db.query(MaintenanceWindow.start_at, MaintenanceWindow.end_at).filter(
        MaintenanceWindow.end_at >= cutoff, MaintenanceWindow.suppress_alerts.is_(True),
        or_(MaintenanceWindow.device_id == device.id, MaintenanceWindow.device_id.is_(None))).all()]
    if windows:
        points = [p for p in points if not any(a <= p[0] <= b for a, b in windows)]
    open_alert = _open_anomaly_alert(db, device)
    last_resolved = None
    if open_alert is None:
        last_resolved = (
            db.query(func.max(Alert.resolved_at))
            .filter(Alert.device_id == device.id, Alert.kind == "anomaly", Alert.resolved.is_(True))
            .scalar()
        )
    # which sensor made the score high. The newest over-boundary reading of the window is explained once (about 0.1 ms) and the note
    # stands for every over-boundary point, which is what the decision names in its reason
    extra = {}
    note = _explain_newest_over_boundary(db, device, points, cutoff)
    if note is not None:
        extra["details"] = [note if score >= anomaly_decision.BOUNDARY else None for _, score in points]
    decision = anomaly_decision.decide(
        points,
        _aware(open_alert.triggered_at) if open_alert is not None and open_alert.triggered_at else (now if open_alert else None),
        _aware(last_resolved) if last_resolved else None,
        now,
        interval,
        **extra,
    )
    peak = max((score for _, score in points), default=0.0)

    if decision.action == "resolve":
        if open_alert is not None:
            open_alert.resolved = True
            open_alert.resolved_at = now
            open_alert.message = f"{open_alert.message} (resolved: {decision.reason})" if decision.reason else open_alert.message
            db.commit()
        return

    if decision.action == "escalate":
        if open_alert is not None and open_alert.severity != "critical":
            open_alert.severity = "critical"
            open_alert.message = f"{ANOMALY_PREFIX} on {device.name}: {decision.reason}"
            open_alert.evidence = decision.evidence or None
            open_alert.peak_value = max(open_alert.peak_value or 0.0, peak)
            open_alert.last_seen_at = now
            ticket = (
                db.query(Ticket)
                .filter(Ticket.device_id == device.id, Ticket.alert_id == open_alert.id, Ticket.status != "closed")
                .first()
            )
            if ticket is not None:
                ticket.priority = "critical"
            db.commit()
            _notify_anomaly(background_tasks, db, device, "critical", open_alert.message, peak)
            return
        decision = anomaly_decision.Decision("none")

    if decision.action == "raise" and open_alert is None:
        _raise_anomaly_alert(db, device, decision, peak, now, background_tasks)
        return

    # nothing to do about the alert itself. An open one keeps its figures current (the latest evaluation and the highest score)
    if open_alert is not None:
        open_alert.last_seen_at = now
        open_alert.peak_value = max(open_alert.peak_value or 0.0, peak)
    db.commit()


def _raise_anomaly_alert(db: Session, device: Device, decision, peak: float, now: datetime, background_tasks) -> None:
    severity = decision.severity if decision.severity in ("warning", "critical") else "warning"
    alert = Alert(
        device_id=device.id,
        rule_id=None,
        message=f"{ANOMALY_PREFIX} on {device.name}: {decision.reason}",
        severity=severity,
        resolved=False,
        kind="anomaly",
        evidence=decision.evidence or None,
        peak_value=peak,
        last_seen_at=now,
        triggered_at=now,
    )
    # the database refuses a second open model alert for the device. A post that lost the race stops here and raises
    # neither the alert nor a second ticket
    if not add_alert(db, alert):
        db.commit()
        return
    # a fault that comes and goes as it develops keeps one ticket until someone closes it
    open_ticket = (
        db.query(Ticket)
        .filter(Ticket.device_id == device.id, Ticket.status != "closed", Ticket.title == f"Inspect {device.name}")
        .first()
    )
    if open_ticket:
        open_ticket.alert_id = alert.id
        if severity == "critical":
            open_ticket.priority = "critical"
        db.commit()
        _notify_anomaly(background_tasks, db, device, severity, alert.message, peak)
        return
    db.add(Ticket(
        device_id=device.id,
        alert_id=alert.id,
        title=f"Inspect {device.name}",
        description=(
            f"The anomaly model flagged {device.name} ({device.location or 'no location'}): {decision.reason}. "
            + ("This is well outside normal: inspect before the next shift." if severity == "critical"
               else "Check the machine and the recent readings on its device page.")
        ),
        status="open",
        priority="critical" if severity == "critical" else "high",
    ))
    db.commit()
    _notify_anomaly(background_tasks, db, device, severity, alert.message, peak)
