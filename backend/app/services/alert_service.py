"""
Alert Service - evaluates a new telemetry reading against all
alert rules for a device and inserts Alert rows when rules are triggered.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.models.telemetry import Telemetry
from app.models.ticket import Ticket
from app.models.user import User
from app.routes.maintenance import is_in_maintenance
from app.services import notify_service, sms_service, webhook_service


_CONDITIONS = {
    "gt": lambda val, threshold: val > threshold,
    "lt": lambda val, threshold: val < threshold,
    "eq": lambda val, threshold: val == threshold,
}


def evaluate_rules(device: Device, reading: dict, db: Session) -> None:
    rules = (
        db.query(AlertRule)
        .filter(AlertRule.device_id == device.id)
        .all()
    )

    # skip all alert processing while the device is in an active maintenance window
    # so planned downtime does not generate noise that technicians would have to dismiss.
    if is_in_maintenance(db, device.id):
        return

    for rule in rules:
        value = reading.get(rule.metric)
        if value is None:
            continue

        check = _CONDITIONS.get(rule.condition)
        if check and check(value, rule.threshold):
            alert = Alert(
                device_id=device.id,
                rule_id=rule.id,
                message=(
                    f"{rule.metric} is {value} "
                    f"({rule.condition} {rule.threshold}) on {device.name}"
                ),
                severity=rule.severity,
                resolved=False,
            )
            # only notify on warning/critical - info alerts stay silent to avoid noise.
            notify_service.send_discord_alert(alert.message, rule.severity)
            notify_service.send_email_alert(
                subject=f"PHAEMOS [{rule.severity.upper()}] {device.name}",
                body=alert.message,
            )
            webhook_service.notify_all(db, {
                "device_name": device.name,
                "metric":      rule.metric,
                "value":       value,
                "threshold":   rule.threshold,
                "severity":    rule.severity,
            })
            # only send SMS for critical alerts - warning/info would generate too much noise
            # on a paid SMS channel. The owner's phone number is fetched lazily from the DB
            # so the query only happens when there is actually a critical alert to send.
            if rule.severity == "critical" and device.owner_id:
                owner = db.query(User).filter(User.id == device.owner_id).first()
                sms_service.notify_critical(
                    phone_number=owner.phone_number if owner else None,
                    device_name=device.name,
                    metric=rule.metric,
                    value=value,
                    threshold=rule.threshold,
                )
            db.add(alert)

    db.commit()


# an anomaly alert needs this many anomalous readings in a row. It clears after as many normal ones.
# Healthy readings are flagged about 5% of the time by design, so three in a row by chance is
# roughly one in 8,000 while a developing fault keeps the run going.
ANOMALY_RUN = 3
# a score at or above this marks the alert critical
CRITICAL_SCORE = 0.85
ANOMALY_PREFIX = "Anomaly detected"


def evaluate_anomaly(device: Device, db: Session) -> None:
    """Raise or clear the model's anomaly alert for a device from its latest scored readings."""
    if is_in_maintenance(db, device.id):
        return
    latest = (
        db.query(Telemetry)
        .filter(Telemetry.device_id == device.id)
        .order_by(Telemetry.recorded_at.desc())
        .limit(ANOMALY_RUN)
        .all()
    )
    if len(latest) < ANOMALY_RUN:
        return
    open_alert = (
        db.query(Alert)
        .filter(Alert.device_id == device.id, Alert.rule_id.is_(None), Alert.resolved.is_(False),
                Alert.message.startswith(ANOMALY_PREFIX))
        .first()
    )

    if all(not r.is_anomaly for r in latest):
        if open_alert:
            open_alert.resolved = True
            open_alert.resolved_at = datetime.now(timezone.utc)
            db.commit()
        return
    if open_alert or not all(r.is_anomaly for r in latest):
        return

    peak = max(r.anomaly_score or 0.0 for r in latest)
    severity = "critical" if peak >= CRITICAL_SCORE else "warning"
    alert = Alert(
        device_id=device.id,
        rule_id=None,
        message=f"{ANOMALY_PREFIX} on {device.name}: {ANOMALY_RUN} readings in a row outside its normal range (score {peak:.2f})",
        severity=severity,
        resolved=False,
    )
    db.add(alert)
    db.flush()
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
        notify_service.send_discord_alert(alert.message, severity)
        notify_service.send_email_alert(subject=f"PHAEMOS [{severity.upper()}] {device.name}", body=alert.message)
        return
    db.add(Ticket(
        device_id=device.id,
        alert_id=alert.id,
        title=f"Inspect {device.name}",
        description=(
            f"The anomaly model flagged {ANOMALY_RUN} consecutive readings from {device.name}"
            f" ({device.location or 'no location'}), peaking at {peak:.2f}. "
            + ("This is well outside normal: inspect before the next shift." if severity == "critical"
               else "Check the machine and the recent readings on its device page.")
        ),
        status="open",
        priority="critical" if severity == "critical" else "high",
    ))
    db.commit()
    notify_service.send_discord_alert(alert.message, severity)
    notify_service.send_email_alert(subject=f"PHAEMOS [{severity.upper()}] {device.name}", body=alert.message)
