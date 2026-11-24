"""
Webhook Service - delivers alert notifications to configured URLs.

Two formats. chat: a message for Slack (hooks.slack.com), Discord (discord.com/api/webhooks) or Microsoft Teams
(webhook.office.com / teams.microsoft.com), chosen from the address. json: the event body below, signed, for a program to read.

    {"id": "evt_<hex>", "type": "alert.raised" | "alert.resolved" | "webhook.test", "version": 1, "created_at": "<UTC, Z>",
     "data": {"reason": "raised" | "escalated" | "reminder" | "resolved", "alert": {...}, "device": {"id", "name"}}}

A json delivery carries `X-Phaemos-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>" under the webhook's secret>`. A
receiver recomputes it over the raw body and refuses a `t` more than five minutes from its own clock (docs/api-reference.md has a
worked example). Each attempt is signed with its own `t`.

Delivery makes up to three tries with back-off (a pause of 2 s and then 8 s) inside the notify pool job and keeps the outcome on
the webhook: last_delivery_at, last_status, last_error and consecutive_failures. A 4xx other than 408 and 429 is not tried again
because it will not change. All delivery is fire-and-forget: failure is logged but never raises so the alert ingest flow is never
blocked by a broken webhook. Every destination check (https only, public addresses only, the connection pinned to the checked
address, no redirects) applies to every attempt.
"""

import hashlib
import hmac
import json
import logging
import string
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.webhook import Webhook
from app.services.url_safety import CannotResolve, UnsafeUrl, outbound_candidates

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATE = "[PHAEMOS] {severity}: {metric} on {device_name} = {value} (threshold: {threshold})"

_DISCORD_COLOURS = {
    "critical": 0xEF4444,
    "warning":  0xF97316,
    "info":     0x0EA5E9,
}


# the only names a chat template may use. A template is checked against them when it is saved
TEMPLATE_FIELDS = ("device_name", "metric", "value", "threshold", "severity")
# delivery tries and the pauses between them (seconds) and the longest one attempt may take
ATTEMPTS = 3
BACKOFF_SECONDS = (2, 8)
_ATTEMPT_SECONDS = 5


def check_template(template: str | None) -> None:
    """Raise ValueError saying what is wrong with a template. A good one uses only {device_name}, {metric}, {value}, {threshold}, {severity}."""
    if template is None:
        return
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ValueError(f"the template has a stray brace ({exc}). Write a placeholder as {{device_name}}") from None
    for _, field, spec, conversion in parts:
        if field is None:
            continue
        if field not in TEMPLATE_FIELDS or spec or conversion:
            raise ValueError(
                f"{{{field}}} is not a placeholder. Use only: " + ", ".join("{" + f + "}" for f in TEMPLATE_FIELDS)
            )


def _build_text(webhook: Webhook, context: dict) -> str:
    tpl = webhook.template or _DEFAULT_TEMPLATE
    # a template saved before it was checked may name something else: it is refused here and not formatted
    check_template(tpl)
    return tpl.format_map(context)


def _iso(when) -> str | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_event(event_type: str, context: dict) -> dict:
    """The json event body for an alert event. `context` is what the alert service passes (see alert_service)."""
    now = _iso(datetime.now(timezone.utc))
    if event_type == "webhook.test":
        return {"id": f"evt_{uuid.uuid4().hex}", "type": event_type, "version": 1, "created_at": now,
                "data": {"message": "This is a test delivery from PHAEMOS."}}
    return {
        "id": f"evt_{uuid.uuid4().hex}", "type": event_type, "version": 1, "created_at": now,
        "data": {
            "reason": context.get("reason", "raised"),
            "alert": {
                "id": context.get("alert_id"),
                "kind": context.get("kind", "rule"),
                "severity": context.get("severity"),
                "metric": context.get("metric"),
                "condition": context.get("condition"),
                "value": context.get("value"),
                "threshold": context.get("threshold"),
                "peak_value": context.get("peak_value"),
                "occurrences": context.get("occurrences"),
                "message": context.get("message"),
                "resolved": event_type == "alert.resolved",
                "triggered_at": _iso(context.get("triggered_at")),
                "first_seen_at": _iso(context.get("first_seen_at")),
            },
            "device": {"id": context.get("device_id"), "name": context.get("device_name")},
        },
    }


def sign(secret: str, body: bytes, at: int | None = None) -> str:
    """The X-Phaemos-Signature value for a body: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>">."""
    stamp = int(time.time()) if at is None else int(at)
    mac = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={stamp},v1={mac}"


def _host(url: str) -> str:
    # extract only the netloc so downstream checks cannot be fooled by the
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
            # a machine name holding @everyone must not ping a channel
            "allowed_mentions": {"parse": []},
            "embeds": [{
                "title": f"PHAEMOS Alert [{severity.upper()}]",
                "description": text,
                "color": colour,
            }],
        }
    if _is_teams(webhook.url):
        # adaptive Card format for Teams incoming webhooks
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": text,
            "themeColor": "EF4444" if severity == "critical" else "F97316",
            "text": text,
        }
    # default: Slack-compatible {"text": "..."} format
    return {"text": text}


def _disable(webhook_id: str | None, reason: str) -> None:
    # a webhook whose address is no longer safe stops delivering, with the reason kept for an admin;
    # delivery runs after the request's session closed, so this opens its own
    if not webhook_id:
        return
    db = SessionLocal()
    try:
        row = db.query(Webhook).filter(Webhook.id == webhook_id).first()
        if row is not None:
            row.enabled = False
            row.disabled_reason = reason
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Could not switch off an unsafe webhook (%s)", type(exc).__name__)
    finally:
        db.close()


# a webhook is switched off only on a positive finding that stays true: the name resolved and an address is in a
# forbidden range, seen on two checks at least this long apart. A resolver fault is never such a finding
_UNSAFE_CONFIRM_SECONDS = 60
_unsafe_since: dict[str, float] = {}

# one delivery, however many addresses it tries, ends within this long. Each connect gets a short try of its own
_DELIVERY_SECONDS = 8
_CONNECT_SECONDS = 2


def _note_unsafe(webhook, reason: str) -> bool:
    """Record a positive finding. Returns True once it has held for a minute and the webhook is switched off."""
    key = str(getattr(webhook, "id", None) or "")
    if not key:
        return False  # nothing to remember it by, so it is never switched off on one sighting
    now = time.monotonic()
    first = _unsafe_since.setdefault(key, now)
    if now - first < _UNSAFE_CONFIRM_SECONDS:
        logger.warning("Webhook %s looks unsafe (%s). It will be checked again before it is switched off", webhook.name, reason)
        return False
    _unsafe_since.pop(key, None)
    logger.warning("Webhook %s switched off: %s", webhook.name, reason)
    _disable(key, reason)
    return True


def _record(webhook_id: str | None, status: int | None, error: str | None, ok: bool) -> None:
    """Keep the outcome of a delivery on the webhook. Its own short session: delivery runs after the request's closed."""
    if not webhook_id:
        return
    db = SessionLocal()
    try:
        row = db.query(Webhook).filter(Webhook.id == webhook_id).first()
        if row is not None:
            row.last_delivery_at = datetime.now(timezone.utc)
            row.last_status = status
            row.last_error = None if ok else (error or "failed")[:40]
            row.consecutive_failures = 0 if ok else (row.consecutive_failures or 0) + 1
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Could not record a webhook delivery (%s)", type(exc).__name__)
    finally:
        db.close()


@dataclass
class Outcome:
    ok: bool
    status: int | None = None
    error: str | None = None
    elapsed_ms: int = 0
    attempts: int = 0
    # true when the address check switched the webhook off or refused it: trying again cannot help
    final: bool = False


def _retryable(status: int) -> bool:
    # a server error, a timeout or a slow-down may pass. Any other 4xx is the receiver saying no and will not change
    return status >= 500 or status in (408, 429)


def _attempt(webhook, body: bytes, content_type: str, secret: str | None, event: str | None, delivery_id: str) -> Outcome:
    """One try, checking the address afresh and posting to the checked address. Never raises."""
    try:
        # the address is checked again now, because a name can resolve somewhere else than when it was
        # saved and the request connects to an address that passed. A row saved before the check
        # existed is covered the first time it is used
        candidates = outbound_candidates(webhook.url)
    except CannotResolve:
        # a name that did not resolve may be a passing fault. It is a failed send like any other
        logger.warning("Webhook delivery failed for %s (the name did not resolve)", webhook.name)
        return Outcome(False, None, "dns")
    except UnsafeUrl as exc:
        return Outcome(_note_unsafe(webhook, str(exc)), None, "unsafe address", final=True)
    _unsafe_since.pop(str(getattr(webhook, "id", None) or ""), None)

    deadline = time.monotonic() + _ATTEMPT_SECONDS
    last_error = None
    # each checked address in turn, so a host with an address this machine cannot reach still works
    for url, headers, extensions in candidates:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sent = {**headers, "Content-Type": content_type, "User-Agent": "PHAEMOS-Webhooks/1"}
        if secret:
            sent["X-Phaemos-Signature"] = sign(secret, body)
            sent["X-Phaemos-Event"] = event or ""
            sent["X-Phaemos-Delivery"] = delivery_id
        timeout = httpx.Timeout(remaining, connect=min(_CONNECT_SECONDS, remaining))
        try:
            # no redirects are followed: a redirect could point at an address the check never saw
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                res = client.post(url, content=body, headers=sent, extensions=extensions)
            if res.is_success:
                return Outcome(True, res.status_code)
            # a server answered, so another address would reach the same one. The address and the exception
            # text carry the secret URL, so only the name and the status are logged
            logger.warning("Webhook delivery failed for %s (HTTP %s)", webhook.name, res.status_code)
            return Outcome(False, res.status_code, f"http {res.status_code}", final=not _retryable(res.status_code))
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
            continue
        except httpx.TimeoutException:
            logger.warning("Webhook delivery failed for %s (timeout)", webhook.name)
            return Outcome(False, None, "timeout")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook delivery failed for %s (%s)", webhook.name, type(exc).__name__)
            return Outcome(False, None, type(exc).__name__)
    logger.warning("Webhook delivery failed for %s (%s)", webhook.name, type(last_error).__name__ if last_error else "timeout")
    return Outcome(False, None, "connect" if last_error else "timeout")


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _deliver(webhook, body: bytes, content_type: str = "application/json", secret: str | None = None,
             event: str | None = None, record: bool = True) -> Outcome:
    """
    Send one body, up to ATTEMPTS times with BACKOFF_SECONDS pauses and keep the outcome on the webhook.

    The result is what the caller's repeat window needs: ok is True once a try went through or when the address check switched the
    webhook off (trying again cannot help). The pauses run in the notify pool's worker, which bounds a delivery to about 25 seconds.
    """
    delivery_id = f"dlv_{uuid.uuid4().hex}"
    started = time.monotonic()
    outcome = Outcome(False)
    for attempt in range(1, ATTEMPTS + 1):
        outcome = _attempt(webhook, body, content_type, secret, event, delivery_id)
        outcome.attempts = attempt
        if outcome.ok or outcome.final or attempt == ATTEMPTS:
            break
        _sleep(BACKOFF_SECONDS[attempt - 1])
    outcome.elapsed_ms = int((time.monotonic() - started) * 1000)
    if record:
        _record(getattr(webhook, "id", None), outcome.status, outcome.error, outcome.ok)
    return outcome


@dataclass(frozen=True)
class WebhookTarget:
    # a plain copy of the columns delivery needs. A background task runs after the request's session has closed
    # and its rows have expired, so it must not hold the ORM objects
    name: str
    url: str
    template: str | None
    id: str | None = None
    format: str = "chat"
    secret: str | None = None


def enabled_targets(db: Session, only_json: bool = False) -> list[WebhookTarget]:
    """Read the enabled webhooks now, while the session is open, as plain values for a later delivery."""
    q = db.query(Webhook).filter(Webhook.enabled.is_(True))
    if only_json:
        q = q.filter(Webhook.format == "json")
    return [
        WebhookTarget(name=w.name, url=w.url, template=w.template, id=str(w.id), format=w.format or "chat", secret=w.secret)
        for w in q.all()
    ]


def _body_for(wh, alert_context: dict, event: str) -> tuple[bytes, str]:
    if (getattr(wh, "format", "chat") or "chat") == "json":
        return json.dumps(build_event(event, alert_context), separators=(",", ":")).encode(), "application/json"
    text = _build_text(wh, alert_context)
    return json.dumps(_build_payload(wh, text, alert_context.get("severity", "info"))).encode(), "application/json"


def deliver_all(targets: list[WebhookTarget], alert_context: dict, event: str = "alert.raised") -> bool:
    """
    Deliver an alert to each target. alert_context keys: device_name, metric, value, threshold, severity (and for a json webhook the
    alert and device ids and figures, see build_event).

    Meant to run as a background task, so a slow endpoint never holds a node's post. Returns True when at least one
    webhook was settled (delivered or switched off by the address check), so the caller's repeat window stays
    taken. When every send failed or a template could not be built it returns False and the caller frees the
    window so the next reading tries again. Each delivery logs its own failure.
    """
    settled = False
    for wh in targets:
        # one webhook with a bad template must not stop the ones after it
        try:
            body, ctype = _body_for(wh, alert_context, event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook %s skipped: its message could not be built (%s)", wh.name, type(exc).__name__)
            continue
        if _deliver(wh, body, ctype, getattr(wh, "secret", None), event).ok:
            settled = True
    return settled


def notify_all(db: Session, alert_context: dict) -> None:
    """Deliver an alert to every enabled webhook now, in the caller's thread."""
    deliver_all(enabled_targets(db), alert_context)


def test_webhook(webhook: Webhook) -> Outcome:
    """
    Send a test delivery to one webhook, once (no tries) and say what happened: the status and the time taken.

    A json webhook gets the signed webhook.test event. A chat webhook gets its chat message. The outcome is kept on the webhook.
    """
    started = time.monotonic()
    try:
        if (webhook.format or "chat") == "json":
            body = json.dumps(build_event("webhook.test", {}), separators=(",", ":")).encode()
        else:
            body = json.dumps(_build_payload(webhook, "[PHAEMOS] Test notification - webhook is configured correctly.", "info")).encode()
        outcome = _attempt(webhook, body, "application/json", webhook.secret if webhook.format == "json" else None, "webhook.test", f"dlv_{uuid.uuid4().hex}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Test webhook failed for %s (%s)", webhook.name, type(exc).__name__)
        outcome = Outcome(False, None, type(exc).__name__)
    outcome.attempts = 1
    outcome.elapsed_ms = int((time.monotonic() - started) * 1000)
    _record(str(webhook.id), outcome.status, outcome.error, outcome.ok)
    return outcome
