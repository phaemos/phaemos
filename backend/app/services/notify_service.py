"""
Notification Service - sends Discord webhook and email alerts when a
critical or warning alert is triggered. Both channels fail gracefully
so a broken webhook never crashes the telemetry ingest flow.
"""

import logging

import httpx

from app.config import settings
from app.services import email_service

logger = logging.getLogger(__name__)

# only notify for these severities - info would cause alert fatigue.
_NOTIFY_SEVERITIES = {"critical", "warning"}


def discord_wanted(severity: str) -> bool:
    """True when a Discord message would be sent for this severity, so a caller can skip its repeat window."""
    return bool(settings.discord_webhook_url) and severity in _NOTIFY_SEVERITIES


def send_discord_alert(message: str, severity: str) -> bool:
    """POST a message to the configured Discord webhook channel. True once Discord accepted it."""
    if not discord_wanted(severity):
        return False  # webhook not configured or an info alert, skip silently

    # Discord embeds use colour codes - red for critical, yellow for warning.
    colour = 0xFF0000 if severity == "critical" else 0xFFA500
    payload = {
        "embeds": [{
            "title": f"PHAEMOS Alert [{severity.upper()}]",
            "description": message,
            "color": colour,
        }]
    }
    try:
        # use a short timeout - notification failure must not block the request.
        with httpx.Client(timeout=5) as client:
            res = client.post(settings.discord_webhook_url, json=payload)
            res.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        # the exception text carries the webhook URL, which is a secret, so only the status is logged
        logger.warning("Discord notification failed (HTTP %s)", exc.response.status_code)
    except Exception as exc:
        logger.warning("Discord notification failed (%s)", type(exc).__name__)
    return False


def send_email_alert(subject: str, body: str) -> bool:
    """Email an alert to ALERT_EMAIL_TO through Resend. Never raises."""
    recipients = email_service.parse_recipients(settings.alert_email_to)
    if not recipients:
        return False  # no alert address configured, skip silently
    try:
        return email_service.send_email(recipients, subject, body)
    except Exception as exc:
        # a failed alert email must never break telemetry ingest.
        logger.warning("Email notification failed (%s)", type(exc).__name__)
        return False
