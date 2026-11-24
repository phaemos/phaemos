import html
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from app.errors import ApiError, Code
from app.config import settings
from app.limiter import _real_ip, limiter
from app.services import email_service

logger = logging.getLogger(__name__)

router = APIRouter()

_SUBJECT_PREFIX = "[Contact] "

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# a slow Cloudflare must not hold a worker open, so the call gives up quickly
TURNSTILE_TIMEOUT_SECONDS = 5.0


class ContactRequest(BaseModel):
    # stripped first, so a value of only spaces counts as empty
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    email: EmailStr
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    # empty when the dashboard has no site key (local development only).
    # 2048 is the longest token Cloudflare documents.
    turnstile_token: str = Field(default="", max_length=2048)


async def _verify_turnstile(token: str, remote_ip: str) -> bool:
    # verify the Turnstile token server-side so the captcha cannot be bypassed
    # by stripping it from the request.
    if not token:
        return False

    data = {"secret": settings.turnstile_secret_key, "response": token}
    # an empty remoteip is not a valid value for Cloudflare, so it is left out
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=TURNSTILE_TIMEOUT_SECONDS) as client:
            resp = await client.post(TURNSTILE_VERIFY_URL, data=data)
            resp.raise_for_status()
            result = resp.json()
            if not isinstance(result, dict):
                raise ValueError("unexpected reply shape")
    except (httpx.HTTPError, ValueError):
        # a network fault, timeout or unreadable reply says nothing about the
        # visitor, so it is a 503 rather than a failed check or a 500.
        logger.warning("turnstile verification service could not be reached")
        raise ApiError(503, Code.CHALLENGE_UNAVAILABLE, "The security check is unavailable right now. Please try again shortly.")
    return result.get("success", False) is True


def _send_email(payload: ContactRequest) -> bool:
    # a blocking call, so the route runs it in a worker thread. Returns whether
    # the message reached Resend.
    name = email_service.clean_line(payload.name, 100)
    subject = email_service.clean_line(payload.subject, 200)
    sender = email_service.clean_line(str(payload.email), 254)
    message = email_service.clean_body(payload.message, 5000)

    text = f"Name: {name}\nEmail: {sender}\nSubject: {subject}\n\n{message}"
    # every visitor value is escaped before it goes into markup
    html_body = (
        f"<p><strong>Name:</strong> {html.escape(name)}<br>"
        f"<strong>Email:</strong> {html.escape(sender)}<br>"
        f"<strong>Subject:</strong> {html.escape(subject)}</p>"
        f"<p>{html.escape(message).replace(chr(10), '<br>')}</p>"
    )
    return email_service.send_email(
        email_service.parse_recipients(settings.contact_email_to),
        # the prefix counts towards the 200 character subject cap, so the visitor's part gives way
        f"{_SUBJECT_PREFIX}{subject[: email_service.SUBJECT_MAX_LENGTH - len(_SUBJECT_PREFIX)]}",
        text,
        html_body=html_body,
        reply_to=sender,
    )


@router.post("/contact", status_code=204)
@limiter.limit("3/hour")
async def submit_contact(request: Request, payload: ContactRequest):
    # the visitor's address, not the proxy's: the limiter already resolves it
    remote_ip = _real_ip(request)

    if settings.turnstile_secret_key:
        ok = await _verify_turnstile(payload.turnstile_token, remote_ip)
        if not ok:
            raise ApiError(422, Code.CHALLENGE_FAILED, "Turnstile verification failed")
    elif not settings.is_development:
        # fail closed: without a secret the check cannot run;
        # skipping it would leave the form open to bots. Only an exact development
        # environment may skip it, so a name such as staging or prod is refused.
        logger.error("TURNSTILE_SECRET_KEY is not set: refusing contact form requests outside development")
        raise ApiError(503, Code.CONTACT_UNAVAILABLE, "The contact form is not available right now. Please email us directly.")
    # in development an empty secret skips the check so the form can be tried locally

    sent = await run_in_threadpool(_send_email, payload)
    # in development with no Resend key the message is logged and the form carries on;
    # anywhere else an undelivered message must not look delivered to the visitor.
    if not sent and not email_service.skipped_in_development():
        raise ApiError(503, Code.CONTACT_NOT_SENT, "We could not send your message right now. Please email us directly.")
