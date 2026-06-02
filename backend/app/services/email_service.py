"""
Email service - sends transactional emails via Resend.
Graceful no-op when resend_api_key is absent or placeholder.
"""

import logging

from app.config import settings

_log = logging.getLogger(__name__)

_UNSET = {"", "placeholder"}


def send_invite(to_email: str, invite_link: str, role: str) -> None:
    """Send an invitation email via Resend. Falls back to logging the link when unconfigured."""
    if settings.resend_api_key in _UNSET:
        # I log the invite link at INFO so developers can still test the flow
        # locally without needing a Resend account.
        _log.info(
            "Resend not configured - invite link for %s (%s): %s",
            to_email,
            role,
            invite_link,
        )
        return

    # I import resend lazily so a missing package does not crash the app on startup.
    try:
        import resend  # type: ignore[import]
    except ImportError:
        _log.warning("resend package not installed - invite email not sent to %s", to_email)
        return

    resend.api_key = settings.resend_api_key

    html_body = f"""
    <p>You have been invited to join PHAEMOS as a <strong>{role}</strong>.</p>
    <p><a href="{invite_link}">Accept invitation</a></p>
    <p>This link expires in 48 hours.</p>
    <p>If you did not request this invitation, you can ignore this email.</p>
    """

    try:
        resend.Emails.send({
            "from": settings.from_email,
            "to": [to_email],
            "subject": "You have been invited to PHAEMOS",
            "html": html_body,
        })
    except Exception as exc:
        _log.warning("Resend email delivery failed: %s", exc)
