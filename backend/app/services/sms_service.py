"""
SMS service - sends critical-severity alerts through Brevo's transactional SMS API.

The call is a plain httpx request to the REST endpoint, so no vendor SDK is needed.
Reference: https://developers.brevo.com/docs/transactional-sms-endpoints
send_sms never raises: it returns whether Brevo accepted the message.
"""

import functools
import logging
import re
import unicodedata

import httpx

from app.config import settings
from app.services.email_service import safe_code

_log = logging.getLogger(__name__)

# placeholder sentinel values that mean "not configured yet"
_UNSET = {"", "placeholder"}

# the current endpoint. The older /v3/transactionalSMS/sms path is deprecated.
BREVO_SMS_URL = "https://api.brevo.com/v3/transactionalSMS/send"
# a slow vendor must not hold a worker open, so the call gives up quickly
SMS_TIMEOUT_SECONDS = 5.0
# one part of plain GSM text, so one alert is one message part
SMS_MAX_LENGTH = 160

# a plus sign then 8 to 15 digits
_E164 = re.compile(r"^\+[0-9]{8,15}$")
# Brevo allows an alphanumeric sender name of 11 characters or a numeric one of 15 digits
_SENDER = re.compile(r"^([A-Za-z0-9]{1,11}|[0-9]{1,15})$")
# characters that take two places in a GSM message, so they would break the length cap.
# the backtick is not in the basic GSM set either.
_GSM_EXTENDED = re.compile(r"[\^{}\\\[\]~|`]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def is_configured() -> bool:
    return settings.brevo_api_key.strip() not in _UNSET


@functools.lru_cache(maxsize=8)
def _sender_is_valid(sender: str) -> bool:
    # cached per value so a bad sender name is logged once, not on every alert.
    if _SENDER.match(sender):
        return True
    _log.error("BREVO_SMS_SENDER must be 11 letters or digits at most (a numeric name may have 15 digits) with no spaces: SMS alerts are disabled")
    return False


def _to_plain_text(message: str) -> str:
    # accents and symbols outside plain text would switch the message to unicode,
    # which allows only 70 characters per credit.
    ascii_only = unicodedata.normalize("NFKD", message).encode("ascii", "ignore").decode("ascii")
    return " ".join(_GSM_EXTENDED.sub(" ", _CONTROL.sub(" ", ascii_only)).split())


def cap_message(message: str, limit: int = SMS_MAX_LENGTH) -> str:
    """Cut a message to the limit without ending in the middle of a word or number."""
    message = _to_plain_text(message)
    if len(message) <= limit:
        return message
    cut = message[:limit]
    if message[limit] != " " and " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip()


def _brevo_code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "unknown"
    code = body.get("code") if isinstance(body, dict) else None
    return safe_code(code) if code is not None else "unknown"


def format_number(value: float) -> str:
    """At most three decimal places and no float noise: 0.30000000000000004 reads 0.3."""
    text = f"{round(float(value), 3):.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def send_sms(to_number: str, message: str) -> bool:
    """Send an SMS to to_number. Returns True only when Brevo accepted it."""
    if not is_configured():
        _log.warning("Brevo API key not configured - SMS not sent")
        return False
    if not to_number or not _E164.match(to_number):
        # the number is left out of the log because phone numbers are PII.
        _log.warning("SMS not sent: the recipient is not an E.164 phone number")
        return False
    sender = settings.brevo_sms_sender.strip()
    if not _sender_is_valid(sender):
        return False

    body = {
        "sender": sender,
        # Brevo's documented examples give the number with no plus sign
        "recipient": to_number.lstrip("+"),
        "content": cap_message(message),
        "type": "transactional",
    }
    headers = {
        "api-key": settings.brevo_api_key.strip(),
        "accept": "application/json",
        "content-type": "application/json",
    }
    try:
        with httpx.Client(timeout=SMS_TIMEOUT_SECONDS) as client:
            res = client.post(BREVO_SMS_URL, json=body, headers=headers)
            res.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # the status and Brevo's error code are logged. The body is not, because it can echo the number.
        _log.warning(
            "Brevo SMS delivery failed (HTTP %s, code %s)",
            exc.response.status_code,
            _brevo_code(exc.response),
        )
        return False
    except Exception as exc:
        _log.warning("Brevo SMS delivery failed (%s)", type(exc).__name__)
        return False
    return True


def _alert_text(device_name: str, subject: str, tail: str) -> str:
    # the readings are what matters, so a long device name is the part that gives way
    head = "PHAEMOS CRITICAL: "
    name = _to_plain_text(device_name) or "device"
    room = SMS_MAX_LENGTH - len(head) - len(f"{subject} on ") - len(tail)
    if len(name) > room:
        name = name[: max(room - 3, 0)].rstrip() + "..."
    return f"{head}{subject} on {name}{tail}"


def notify_critical(phone_number: str | None, device_name: str, metric: str, value: float, threshold: float) -> bool:
    """Send a critical-alert SMS if the user has a phone number configured."""
    if not phone_number:
        return False
    tail = f" = {format_number(value)} (threshold: {format_number(threshold)})"
    return send_sms(phone_number, _alert_text(device_name, metric, tail))


def notify_anomaly(phone_number: str | None, device_name: str, score: float) -> bool:
    """Send a critical anomaly SMS if the user has a phone number configured."""
    if not phone_number:
        return False
    return send_sms(phone_number, _alert_text(device_name, "anomaly", f" (score {format_number(score)})"))
