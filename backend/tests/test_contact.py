import asyncio

import httpx
import pytest

from app.config import settings
from app.routes import contact
from app.services import email_service

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

PAYLOAD = {
    "name": "Jane Smith",
    "email": "jane@example.com",
    "subject": "Question",
    "message": "Hello there",
    "turnstile_token": "token-from-widget",
}


@pytest.fixture
def cloudflare(monkeypatch):
    # replaces the HTTP client used for the Turnstile call with one backed by a
    # mock transport, so no test ever reaches the network. The handler list
    # records each request for assertions.
    calls = []
    behaviour = {"handler": lambda request: httpx.Response(200, json={"success": True})}
    real_client = httpx.AsyncClient

    def handler(request):
        calls.append(request)
        return behaviour["handler"](request)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(contact.httpx, "AsyncClient", factory)
    monkeypatch.setattr(contact, "_send_email", lambda payload: True)
    return behaviour, calls


def test_skips_verification_in_development_with_no_secret(client, monkeypatch, cloudflare):
    _, calls = cloudflare
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    res = client.post("/api/v1/contact", json={**PAYLOAD, "turnstile_token": ""})
    assert res.status_code == 204
    assert calls == []


def test_refuses_in_production_with_no_secret(client, monkeypatch, cloudflare):
    _, calls = cloudflare
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 503
    assert "not available" in res.json()["detail"]
    assert calls == []


@pytest.mark.parametrize("name", ["staging", "prod", "Production", ""])
def test_refuses_any_environment_but_development_with_no_secret(client, monkeypatch, cloudflare, name):
    _, calls = cloudflare
    monkeypatch.setattr(settings, "environment", name)
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 503
    assert calls == []


def test_development_is_matched_after_trimming_and_lowercasing(client, monkeypatch, cloudflare):
    monkeypatch.setattr(settings, "environment", " Development ")
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    res = client.post("/api/v1/contact", json={**PAYLOAD, "turnstile_token": ""})
    assert res.status_code == 204


def test_reply_that_is_not_an_object_is_503(client, monkeypatch, cloudflare):
    behaviour, _ = cloudflare
    behaviour["handler"] = lambda request: httpx.Response(200, json=["success"])
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 503


def test_token_over_2048_characters_is_rejected(client, monkeypatch, cloudflare):
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    res = client.post("/api/v1/contact", json={**PAYLOAD, "turnstile_token": "a" * 2049})
    assert res.status_code == 422


def test_limit_counts_every_attempt(client, monkeypatch, cloudflare):
    # the limiter is enabled in the test set-up (it is only reset between tests)
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    codes = [client.post("/api/v1/contact", json=PAYLOAD).status_code for _ in range(4)]
    assert codes == [204, 204, 204, 429]


def test_refused_attempts_count_towards_the_limit(client, monkeypatch, cloudflare):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    codes = [client.post("/api/v1/contact", json=PAYLOAD).status_code for _ in range(4)]
    assert codes == [503, 503, 503, 429]


def test_failed_verification_is_422(client, monkeypatch, cloudflare):
    behaviour, _ = cloudflare
    behaviour["handler"] = lambda request: httpx.Response(200, json={"success": False})
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 422


def test_missing_token_is_422_without_calling_cloudflare(client, monkeypatch, cloudflare):
    _, calls = cloudflare
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    res = client.post("/api/v1/contact", json={**PAYLOAD, "turnstile_token": ""})
    assert res.status_code == 422
    assert calls == []


def test_network_error_is_503(client, monkeypatch, cloudflare):
    behaviour, _ = cloudflare

    def boom(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    behaviour["handler"] = boom
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 503
    assert "security check" in res.json()["detail"]


def test_cloudflare_error_status_is_503(client, monkeypatch, cloudflare):
    behaviour, _ = cloudflare
    behaviour["handler"] = lambda request: httpx.Response(500, text="oops")
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 503


def test_success_is_204(client, monkeypatch, cloudflare):
    _, calls = cloudflare
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 204
    assert len(calls) == 1
    assert str(calls[0].url) == VERIFY_URL
    body = calls[0].content.decode()
    assert "response=token-from-widget" in body
    assert "secret=test-secret" in body


def test_empty_remote_ip_is_not_sent(monkeypatch, cloudflare):
    _, calls = cloudflare
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    assert asyncio.run(contact._verify_turnstile("token", "")) is True
    assert str(calls[0].url) == VERIFY_URL
    assert "remoteip" not in calls[0].content.decode()


def test_known_remote_ip_is_sent(monkeypatch, cloudflare):
    _, calls = cloudflare
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    assert asyncio.run(contact._verify_turnstile("token", "203.0.113.7")) is True
    assert "remoteip=203.0.113.7" in calls[0].content.decode()


def test_route_sends_the_visitor_address_from_the_limiter(client, monkeypatch, cloudflare):
    _, calls = cloudflare
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    monkeypatch.setattr(contact, "_real_ip", lambda request: "198.51.100.9")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 204
    assert "remoteip=198.51.100.9" in calls[0].content.decode()


@pytest.fixture
def resend(monkeypatch):
    # the real _send_email runs, with the Resend SDK call replaced at the boundary
    # and Cloudflare mocked to pass.
    calls = []
    behaviour = {"error": None}

    def fake_send(params):
        calls.append(params)
        if behaviour["error"]:
            raise behaviour["error"]
        return {"id": "email-id"}

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        contact.httpx, "AsyncClient",
        lambda *a, **k: real_client(*a, **{**k, "transport": httpx.MockTransport(
            lambda request: httpx.Response(200, json={"success": True}))}),
    )
    monkeypatch.setattr(email_service.resend.Emails, "send", staticmethod(fake_send))
    monkeypatch.setattr(settings, "turnstile_secret_key", "test-secret")
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "from_email", "no-reply@example.com")
    monkeypatch.setattr(settings, "contact_email_to", "inbox@example.com, team@example.com")
    return behaviour, calls


def test_message_is_emailed_with_the_visitor_as_reply_to(client, resend):
    _, calls = resend
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 204
    assert len(calls) == 1
    sent = calls[0]
    assert sent["from"] == "no-reply@example.com"
    assert sent["to"] == ["inbox@example.com", "team@example.com"]
    assert sent["reply_to"] == "jane@example.com"
    assert sent["subject"] == "[Contact] Question"
    assert "Hello there" in sent["text"]


def test_visitor_text_is_escaped_in_the_html_body(client, resend):
    _, calls = resend
    res = client.post("/api/v1/contact", json={**PAYLOAD, "name": "<img src=x onerror=alert(1)>", "message": "<script>x</script>\nline two"})
    assert res.status_code == 204
    html_body = calls[0]["html"]
    assert "<img" not in html_body
    assert "<script>" not in html_body
    assert "&lt;script&gt;x&lt;/script&gt;<br>line two" in html_body


def test_a_newline_in_the_subject_or_name_cannot_add_headers_or_recipients(client, resend):
    _, calls = resend
    res = client.post("/api/v1/contact", json={
        **PAYLOAD,
        "subject": "Hi\r\nBcc: evil@example.com",
        "name": "Jane\nTo: evil@example.com",
    })
    assert res.status_code == 204
    sent = calls[0]
    assert "\n" not in sent["subject"] and "\r" not in sent["subject"]
    assert sent["to"] == ["inbox@example.com", "team@example.com"]
    assert "bcc" not in sent


@pytest.mark.parametrize("field, length", [("name", 101), ("subject", 201), ("message", 5001)])
def test_fields_over_their_limit_are_rejected(client, resend, field, length):
    res = client.post("/api/v1/contact", json={**PAYLOAD, field: "x" * length})
    assert res.status_code == 422


def test_fields_at_their_limit_are_accepted(client, resend):
    res = client.post("/api/v1/contact", json={**PAYLOAD, "name": "x" * 100, "subject": "y" * 200, "message": "z" * 5000})
    assert res.status_code == 204


def test_resend_failure_is_503_not_204(client, resend):
    behaviour, _ = resend
    behaviour["error"] = RuntimeError("down")
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 503
    assert "email us directly" in res.json()["detail"]


@pytest.mark.parametrize("environment", ["production", "staging", ""])
def test_no_resend_key_outside_development_is_503(client, resend, monkeypatch, environment):
    _, calls = resend
    monkeypatch.setattr(settings, "resend_api_key", "placeholder")
    monkeypatch.setattr(settings, "environment", environment)
    res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 503
    assert "email us directly" in res.json()["detail"]
    assert calls == []


def test_no_resend_key_in_development_is_204_and_logs(client, resend, monkeypatch, caplog):
    _, calls = resend
    monkeypatch.setattr(settings, "resend_api_key", "")
    monkeypatch.setattr(settings, "environment", " Development ")
    with caplog.at_level("INFO"):
        res = client.post("/api/v1/contact", json=PAYLOAD)
    assert res.status_code == 204
    assert calls == []
    # a visitor's message is a stranger's personal text, so by default it is not in the log at all
    assert "Hello there" not in caplog.text and "jane@example.com" not in caplog.text
    assert "was not sent" in caplog.text
    caplog.clear()
    monkeypatch.setattr(settings, "log_email_bodies", True)
    with caplog.at_level("INFO"):
        client.post("/api/v1/contact", json=PAYLOAD)
    assert "Hello there" in caplog.text


def test_no_recipient_configured_is_503(client, resend, monkeypatch):
    monkeypatch.setattr(settings, "contact_email_to", " , ")
    assert client.post("/api/v1/contact", json=PAYLOAD).status_code == 503


@pytest.mark.parametrize("field", ["name", "subject", "message"])
@pytest.mark.parametrize("value", ["", "   ", "\n\t "])
def test_empty_or_blank_fields_are_rejected(client, resend, field, value):
    res = client.post("/api/v1/contact", json={**PAYLOAD, field: value})
    assert res.status_code == 422


def test_a_200_character_subject_fits_the_cap_with_its_prefix(client, resend):
    _, calls = resend
    res = client.post("/api/v1/contact", json={**PAYLOAD, "subject": "s" * 200})
    assert res.status_code == 204
    assert calls[0]["subject"] == "[Contact] " + "s" * 190
    assert len(calls[0]["subject"]) == 200


def test_surrounding_spaces_are_stripped_from_the_fields(client, resend):
    _, calls = resend
    client.post("/api/v1/contact", json={**PAYLOAD, "subject": "  Question  "})
    assert calls[0]["subject"] == "[Contact] Question"
