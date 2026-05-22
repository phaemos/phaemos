"""
Notification Service — sends Discord webhook and email alerts when a
critical or warning alert is triggered. Both channels fail gracefully
so a broken webhook never crashes the telemetry ingest flow.
"""

import logging
import smtplib
from email.mime.text import MIMEText

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Only notify for these severities — info would cause alert fatigue.
_NOTIFY_SEVERITIES = {"critical", "warning"}


def send_discord_alert(message: str, severity: str) -> None:
    """POST a message to the configured Discord webhook channel."""
    if not settings.discord_webhook_url:
        return  # webhook not configured, skip silently
    if severity not in _NOTIFY_SEVERITIES:
        return

    # Discord embeds use colour codes — red for critical, yellow for warning.
    colour = 0xFF0000 if severity == "critical" else 0xFFA500
    payload = {
        "embeds": [{
            "title": f"PHAEMOS Alert [{severity.upper()}]",
            "description": message,
            "color": colour,
        }]
    }
    try:
        # Use a short timeout — notification failure must not block the request.
        with httpx.Client(timeout=5) as client:
            res = client.post(settings.discord_webhook_url, json=payload)
            res.raise_for_status()
    except Exception as exc:
        logger.warning("Discord notification failed: %s", exc)


def send_email_alert(subject: str, body: str) -> None:
    """Send a plain-text alert email via SMTP."""
    if not settings.smtp_host or not settings.alert_email_to:
        return  # email not configured, skip silently

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user or "phaemos@noreply.local"
    msg["To"] = settings.alert_email_to

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_user and settings.smtp_password:
                server.starttls()  # encrypt the connection before sending credentials
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception as exc:
        logger.warning("Email notification failed: %s", exc)
