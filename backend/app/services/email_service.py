"""
Email service - the one place the API sends email, through Resend.

Every message (contact form, invitation, alert) goes through send_email, with
FROM_EMAIL as the sender. send_email never raises: it returns whether the
message was handed to Resend, so a caller decides what a failure means.
"""

import html
import logging
import re

import resend

from app.config import settings

_log = logging.getLogger(__name__)

_UNSET = {"", "placeholder"}

# a slow vendor must not hold a worker open, so the call gives up quickly
EMAIL_TIMEOUT_SECONDS = 5
# Resend accepts at most 50 recipients in one request
MAX_RECIPIENTS = 50
SUBJECT_MAX_LENGTH = 200

# every control character, including line breaks, tabs and DEL
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# the same set without tab and newline, which a message body may keep
_BODY_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_line(value: str, max_length: int) -> str:
    """Make a one-line value safe for a subject or a name: no control characters, capped."""
    return " ".join(_CONTROL.sub(" ", value).split())[:max_length]


def clean_body(value: str, max_length: int) -> str:
    """Strip control characters from a message body but keep its line breaks."""
    return _BODY_CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))[:max_length]


_SAFE_CODE = re.compile(r"[^A-Za-z0-9_.-]")


def safe_code(value: object) -> str:
    """Reduce a vendor error code to a short harmless token for the log."""
    return _SAFE_CODE.sub("", str(value))[:60] or "unknown"


def parse_recipients(raw: str) -> list[str]:
    """Split a comma-separated address list, trim each entry and drop the empty ones."""
    return [part.strip() for part in raw.split(",") if part.strip()]


def is_configured() -> bool:
    return settings.resend_api_key.strip() not in _UNSET


def skipped_in_development() -> bool:
    """True when nothing can be sent and the environment is development, so callers carry on."""
    return not is_configured() and settings.is_development


def send_email(
    to: list[str],
    subject: str,
    text: str,
    html_body: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """Send one email from FROM_EMAIL. Returns True only when Resend accepted it."""
    recipients = [r for r in to if r][:MAX_RECIPIENTS]
    subject = clean_line(subject, SUBJECT_MAX_LENGTH)
    if not recipients:
        _log.error("email not sent: no recipients are configured")
        return False

    if not is_configured():
        if skipped_in_development():
            # the body is logged so the flow can be tried locally without a Resend account.
            masked = ", ".join(mask_address(r) for r in recipients)
            if settings.log_email_bodies:
                _log.info("Resend not configured - would send to %s: %s\n%s", masked, subject, text)
            else:
                # the subject and body can hold a stranger's own words or a link with a token and an address is personal data,
                # so by default only a masked recipient is logged. LOG_EMAIL_BODIES turns the rest on in development
                _log.info("Resend not configured - an email to %s was not sent (subject and body withheld)", masked)
        else:
            _log.error("email not sent: RESEND_API_KEY is not set")
        return False

    params: dict = {
        "from": settings.from_email,
        "to": recipients,
        "subject": subject,
        "text": text,
    }
    if html_body:
        params["html"] = html_body
    if reply_to:
        params["reply_to"] = clean_line(reply_to, 254)

    try:
        resend.api_key = settings.resend_api_key.strip()
        client_class = getattr(resend, "RequestsClient", None)
        if client_class is not None:
            resend.default_http_client = client_class(timeout=EMAIL_TIMEOUT_SECONDS)
        resend.Emails.send(params)
    except Exception as exc:
        # the vendor's code and error type say why it failed. The message text is left
        # out because it can carry an address.
        _log.warning(
            "Resend email delivery failed (%s, code %s, type %s)",
            type(exc).__name__,
            safe_code(getattr(exc, "code", None)),
            safe_code(getattr(exc, "error_type", None)),
        )
        return False
    return True


def send_invite(to_email: str, invite_link: str, role: str) -> bool:
    """Email an invitation. Returns whether it was sent."""
    if not is_configured() and skipped_in_development():
        # the one deliberate log of a link: it is how the flow is tried locally.
        if settings.log_email_bodies:
            _log.info("Resend not configured - invite link for %s (%s): %s", mask_address(to_email), role, invite_link)
        else:
            _log.info("Resend not configured - invitation for %s (%s) not sent. The admin is shown the link", mask_address(to_email), role)
        return False

    safe_role = html.escape(role)
    safe_link = html.escape(invite_link, quote=True)
    html_body = (
        f"<p>You have been invited to join PHAEMOS as a <strong>{safe_role}</strong>.</p>"
        f'<p><a href="{safe_link}">Accept invitation</a></p>'
        "<p>This link expires in 48 hours.</p>"
        "<p>If you did not request this invitation, you can ignore this email.</p>"
    )
    text = (
        f"You have been invited to join PHAEMOS as a {role}.\n\n"
        f"Accept the invitation: {invite_link}\n\n"
        "This link expires in 48 hours.\n"
        "If you did not request this invitation, you can ignore this email."
    )
    return send_email(
        [to_email],
        "You have been invited to PHAEMOS",
        text,
        html_body=html_body,
        reply_to="support@phaemos.com",
    )


def mask_address(address: str) -> str:
    """j***@example.com: enough for the owner to recognise the address, not enough to use it."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def send_email_changed_notice(old_email: str, new_email: str, when: str) -> bool:
    """Tell the OLD address that the sign-in address was changed. Returns whether it was sent."""
    new_masked = mask_address(new_email)
    text = (
        f"The sign-in address on your PHAEMOS account was changed to {new_masked} on {when} (UTC).\n\n"
        "If you made this change, you do not need to do anything.\n"
        "If you did not, someone else may have your password. Contact support@phaemos.com at once and change "
        "your password. We have signed your account out everywhere else.\n"
    )
    html_body = (
        f"<p>The sign-in address on your PHAEMOS account was changed to <strong>{html.escape(new_masked)}</strong> "
        f"on {html.escape(when)} (UTC).</p>"
        "<p>If you made this change, you do not need to do anything.</p>"
        "<p>If you did not, someone else may have your password. Contact support@phaemos.com at once and change "
        "your password. We have signed your account out everywhere else.</p>"
    )
    return send_email(
        [old_email],
        "The sign-in address on your PHAEMOS account was changed",
        text,
        html_body=html_body,
        reply_to="support@phaemos.com",
    )


def send_signin_attempts_notice(to_email: str) -> bool:
    """Tell an account's owner that it is being guessed at from several places. Sent at most once a day."""
    text = (
        "We have seen many failed sign-in attempts on your PHAEMOS account from several places.\n\n"
        "Your account is not locked and your password has not been guessed. If this was not you, change your password "
        "and turn on two-step sign-in and contact support@phaemos.com if you want help.\n"
    )
    html_body = (
        "<p>We have seen many failed sign-in attempts on your PHAEMOS account from several places.</p>"
        "<p>Your account is not locked and your password has not been guessed. If this was not you, change your password "
        "and turn on two-step sign-in and contact support@phaemos.com if you want help.</p>"
    )
    return send_email([to_email], "Failed sign-in attempts on your PHAEMOS account", text, html_body=html_body, reply_to="support@phaemos.com")


def send_password_reset(to_email: str, reset_link: str) -> bool:
    """Email a one-time password reset link to an account's own address. Returns whether it was sent."""
    safe_link = html.escape(reset_link, quote=True)
    text = (
        "An administrator has sent you a link to choose a new PHAEMOS password.\n\n"
        f"Choose a new password: {reset_link}\n\n"
        "The link works once and expires in 2 hours. If you did not expect this, you can ignore this email.\n"
    )
    html_body = (
        "<p>An administrator has sent you a link to choose a new PHAEMOS password.</p>"
        f'<p><a href="{safe_link}">Choose a new password</a></p>'
        "<p>The link works once and expires in 2 hours. If you did not expect this, you can ignore this email.</p>"
    )
    return send_email([to_email], "Choose a new PHAEMOS password", text, html_body=html_body, reply_to="support@phaemos.com")
