"""
SMS service - sends critical-severity alerts via Brevo Transactional SMS.
Graceful no-op when brevo_api_key is empty or not yet configured.
"""

import logging

from app.config import settings

_log = logging.getLogger(__name__)

# Placeholder sentinel values that mean "not configured yet"
_UNSET = {"", "placeholder"}


def send_sms(to_number: str, message: str) -> None:
    """Send an SMS to to_number. Silently skips if Brevo is not configured."""
    if settings.brevo_api_key in _UNSET:
        # I omit the recipient from this log because phone numbers are PII.
        _log.warning("Brevo API key not configured - SMS not sent")
        return
    if not to_number:
        return

    # I import sib_api_v3_sdk lazily so a missing package does not crash the
    # whole app on startup - teams that have not installed the SDK still get
    # all other features; only SMS is disabled.
    try:
        import sib_api_v3_sdk  # type: ignore[import]
        from sib_api_v3_sdk.rest import ApiException  # type: ignore[import]
    except ImportError:
        _log.warning("sib_api_v3_sdk not installed - SMS not sent")
        return

    config = sib_api_v3_sdk.Configuration()
    config.api_key["api-key"] = settings.brevo_api_key
    client = sib_api_v3_sdk.ApiClient(config)
    api = sib_api_v3_sdk.TransactionalSMSApi(client)

    sms = sib_api_v3_sdk.SendTransacSms(
        sender=settings.brevo_sms_sender,
        recipient=to_number,
        content=message,
    )

    try:
        api.send_transac_sms(sms)
    except ApiException as exc:
        _log.warning("Brevo SMS delivery failed: %s", exc)


def notify_critical(phone_number: str | None, device_name: str, metric: str, value: float, threshold: float) -> None:
    """Send a critical-alert SMS if the user has a phone number configured."""
    if not phone_number:
        return
    message = (
        f"[PHAEMOS] CRITICAL: {metric} on {device_name} = {value} "
        f"(threshold: {threshold})"
    )
    send_sms(phone_number, message)
