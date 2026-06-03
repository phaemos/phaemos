import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr

from app.config import settings
from app.limiter import limiter

router = APIRouter()

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v1/siteverify"


class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str
    turnstile_token: str


async def _verify_turnstile(token: str, remote_ip: str) -> bool:
    # I verify the Turnstile token server-side so the captcha cannot be bypassed
    # by stripping it from the request.
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TURNSTILE_VERIFY_URL,
            data={
                "secret": settings.turnstile_secret_key,
                "response": token,
                "remoteip": remote_ip,
            },
        )
    data = resp.json()
    return data.get("success", False)


def _send_email(payload: ContactRequest) -> None:
    # I only attempt SMTP when credentials are configured - missing creds are a
    # no-op rather than a crash so the dev environment works without real mail.
    if not settings.smtp_host or not settings.smtp_user:
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Contact] {payload.subject}"
    msg["From"] = settings.smtp_user
    msg["To"] = settings.contact_email_to
    msg["Reply-To"] = payload.email

    body = (
        f"Name: {payload.name}\n"
        f"Email: {payload.email}\n"
        f"Subject: {payload.subject}\n\n"
        f"{payload.message}"
    )
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, settings.contact_email_to, msg.as_string())


@router.post("/contact", status_code=204)
@limiter.limit("3/hour")
async def submit_contact(request: Request, payload: ContactRequest):
    remote_ip = request.client.host if request.client else ""

    ok = await _verify_turnstile(payload.turnstile_token, remote_ip)
    if not ok:
        raise HTTPException(status_code=422, detail="Turnstile verification failed")

    try:
        _send_email(payload)
    except Exception:
        # I swallow SMTP errors here - the message was valid, and a mail
        # delivery failure should not surface a 500 to the visitor.
        pass
