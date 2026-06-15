"""
Webhook Service - delivers alert notifications to configured URLs.

Supports Slack (hooks.slack.com), Discord (discord.com/api/webhooks), and
Microsoft Teams (webhook.office.com / teams.microsoft.com) endpoints.
Auto-detects the platform from the URL and formats accordingly.

All delivery is fire-and-forget: failure is logged but never raises so the
alert ingest flow is never blocked by a broken webhook.
"""

import logging
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.models.webhook import Webhook

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATE = "[PHAEMOS] {severity}: {metric} on {device_name} = {value} (threshold: {threshold})"

_DISCORD_COLOURS = {
    "critical": 0xEF4444,
    "warning":  0xF97316,
    "info":     0x0EA5E9,
}


def _build_text(webhook: Webhook, context: dict) -> str:
    tpl = webhook.template or _DEFAULT_TEMPLATE
    return tpl.format_map(context)


def _host(url: str) -> str:
    # I extract only the netloc so downstream checks cannot be fooled by the
    # target domain appearing in the path or query string of a malicious URL.
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_discord(url: str) -> bool:
    host = _host(url)
    return host == "discord.com" or host.endswith(".discord.com")


def _is_teams(url: str) -> bool:
    host = _host(url)
    return (
        host == "webhook.office.com"
        or host.endswith(".webhook.office.com")
        or host == "teams.microsoft.com"
        or host.endswith(".teams.microsoft.com")
    )


def _build_payload(webhook: Webhook, text: str, severity: str) -> dict:
    if _is_discord(webhook.url):
        colour = _DISCORD_COLOURS.get(severity, 0x94A3B8)
        return {
            "content": text,
            "embeds": [{
                "title": f"PHAEMOS Alert [{severity.upper()}]",
                "description": text,
                "color": colour,
            }],
        }
    if _is_teams(webhook.url):
        # Adaptive Card format for Teams incoming webhooks
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": text,
            "themeColor": "EF4444" if severity == "critical" else "F97316",
            "text": text,
        }
    # Default: Slack-compatible {"text": "..."} format
    return {"text": text}


def _deliver(webhook: Webhook, payload: dict) -> None:
    try:
        with httpx.Client(timeout=5) as client:
            res = client.post(webhook.url, json=payload)
            if not res.is_success:
                # Retry once on transient failure
                res = client.post(webhook.url, json=payload)
                res.raise_for_status()
    except Exception as exc:
        logger.warning("Webhook delivery failed for %s (%s): %s", webhook.name, webhook.url, exc)


def notify_all(db: Session, alert_context: dict) -> None:
    """
    Fire all enabled webhooks with the given alert context dict.

    alert_context keys: device_name, metric, value, threshold, severity.
    Called as a FastAPI BackgroundTask so it runs after the response is sent.
    """
    webhooks = db.query(Webhook).filter(Webhook.enabled.is_(True)).all()
    for wh in webhooks:
        text = _build_text(wh, alert_context)
        payload = _build_payload(wh, text, alert_context.get("severity", "info"))
        _deliver(wh, payload)


def test_webhook(webhook: Webhook) -> bool:
    """Send a test payload to a single webhook. Returns True on success."""
    payload = _build_payload(
        webhook,
        "[PHAEMOS] Test notification - webhook is configured correctly.",
        "info",
    )
    try:
        with httpx.Client(timeout=5) as client:
            res = client.post(webhook.url, json=payload)
            return res.is_success
    except Exception as exc:
        logger.warning("Test webhook failed for %s: %s", webhook.name, exc)
        return False
