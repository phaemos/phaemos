"""
Alert Service - evaluates a new telemetry reading against all
alert rules for a device and inserts Alert rows when rules are triggered.
"""

from sqlalchemy.orm import Session

from app.models.alert import Alert, AlertRule
from app.models.device import Device
from app.services import notify_service


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
            # I only notify on warning/critical - info alerts stay silent to avoid noise.
            notify_service.send_discord_alert(alert.message, rule.severity)
            notify_service.send_email_alert(
                subject=f"PHAEMOS [{rule.severity.upper()}] {device.name}",
                body=alert.message,
            )
            db.add(alert)

    db.commit()
