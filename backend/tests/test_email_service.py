import logging

import pytest

from app.config import settings
from app.services import email_service, notify_service


@pytest.fixture
def resend_calls(monkeypatch):
    # replaces the SDK call at the boundary, so no test reaches the network;
    # each call's params are recorded and the behaviour dict can force a failure.
    calls = []
    behaviour = {"error": None}

    def fake_send(params):
        calls.append(params)
        if behaviour["error"]:
            raise behaviour["error"]
        return {"id": "email-id"}

    monkeypatch.setattr(email_service.resend.Emails, "send", staticmethod(fake_send))
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "from_email", "no-reply@example.com")
    return behaviour, calls


def test_sends_from_the_configured_address_with_every_field(resend_calls):
    _, calls = resend_calls
    sent = email_service.send_email(
        ["a@example.com", "b@example.com"], "Hello", "plain", html_body="<p>html</p>", reply_to="visitor@example.com"
    )
    assert sent is True
    assert calls == [{
        "from": "no-reply@example.com",
        "to": ["a@example.com", "b@example.com"],
        "subject": "Hello",
        "text": "plain",
        "html": "<p>html</p>",
        "reply_to": "visitor@example.com",
    }]


def test_optional_fields_are_left_out(resend_calls):
    _, calls = resend_calls
    email_service.send_email(["a@example.com"], "Hello", "plain")
    assert "html" not in calls[0]
    assert "reply_to" not in calls[0]


def test_subject_loses_control_characters_and_is_capped(resend_calls):
    _, calls = resend_calls
    email_service.send_email(["a@example.com"], "Hi\r\nBcc: evil@example.com\n" + "x" * 500, "plain")
    subject = calls[0]["subject"]
    assert "\n" not in subject and "\r" not in subject
    assert len(subject) == 200


@pytest.mark.parametrize("raw, expected", [
    ("a@example.com", ["a@example.com"]),
    (" a@example.com , b@example.com ", ["a@example.com", "b@example.com"]),
    ("a@example.com,,  ,b@example.com,", ["a@example.com", "b@example.com"]),
    ("", []),
    (" , ", []),
])
def test_recipient_parsing(raw, expected):
    assert email_service.parse_recipients(raw) == expected


def test_no_recipients_is_not_sent(resend_calls):
    _, calls = resend_calls
    assert email_service.send_email([], "Hello", "plain") is False
    assert calls == []


@pytest.mark.parametrize("key", ["", "placeholder", "  "])
def test_unconfigured_in_development_logs_and_carries_on(monkeypatch, resend_calls, caplog, key):
    _, calls = resend_calls
    monkeypatch.setattr(settings, "resend_api_key", key)
    monkeypatch.setattr(settings, "environment", "development")
    # the body can hold a link with a token, so it is logged only when asked for
    monkeypatch.setattr(settings, "log_email_bodies", True)
    with caplog.at_level(logging.INFO):
        sent = email_service.send_email(["a@example.com"], "Hello", "the body")
    assert sent is False
    assert calls == []
    assert email_service.skipped_in_development() is True
    assert "would send" in caplog.text
    assert "the body" in caplog.text


@pytest.mark.parametrize("environment", ["production", "staging", ""])
def test_unconfigured_outside_development_is_not_sent_and_not_skipped(monkeypatch, resend_calls, caplog, environment):
    _, calls = resend_calls
    monkeypatch.setattr(settings, "resend_api_key", "placeholder")
    monkeypatch.setattr(settings, "environment", environment)
    with caplog.at_level(logging.INFO):
        assert email_service.send_email(["a@example.com"], "Hello", "the body") is False
    assert calls == []
    assert email_service.skipped_in_development() is False
    # INFO capture is on above, so an absent body is not an artefact of the level
    assert "RESEND_API_KEY is not set" in caplog.text
    assert "the body" not in caplog.text


class FakeResendError(Exception):
    # shaped like the SDK's error: a code and a type next to the message text
    def __init__(self):
        super().__init__("rejected a@example.com")
        self.code = 403
        self.error_type = "validation_error"


def test_resend_error_code_and_type_are_logged_but_not_the_message(resend_calls, caplog):
    behaviour, _ = resend_calls
    behaviour["error"] = FakeResendError()
    with caplog.at_level(logging.WARNING):
        assert email_service.send_email(["a@example.com"], "Hello", "plain") is False
    assert "code 403" in caplog.text
    assert "type validation_error" in caplog.text
    assert "a@example.com" not in caplog.text


def test_resend_failure_returns_false_and_logs_no_address(resend_calls, caplog):
    behaviour, _ = resend_calls
    behaviour["error"] = RuntimeError("rejected a@example.com")
    with caplog.at_level(logging.WARNING):
        assert email_service.send_email(["a@example.com"], "Hello", "plain") is False
    assert "a@example.com" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_invite_escapes_the_role_and_the_link(resend_calls):
    _, calls = resend_calls
    link = 'https://example.com/accept?token=a"><script>alert(1)</script>'
    assert email_service.send_invite("new@example.com", link, "<b>admin</b>") is True
    html_body = calls[0]["html"]
    assert "<script>" not in html_body
    assert "<b>admin</b>" not in html_body
    assert "&lt;b&gt;admin&lt;/b&gt;" in html_body
    assert calls[0]["to"] == ["new@example.com"]


def test_invite_unconfigured_in_development_logs_the_link(monkeypatch, caplog):
    monkeypatch.setattr(settings, "resend_api_key", "placeholder")
    monkeypatch.setattr(settings, "environment", "development")
    with caplog.at_level(logging.INFO):
        assert email_service.send_invite("new@example.com", "https://example.com/accept?token=abc", "viewer") is False
    # by default neither the link nor the full address is logged, only a masked address
    assert "token=abc" not in caplog.text and "new@example.com" not in caplog.text and "n***@example.com" in caplog.text
    caplog.clear()
    monkeypatch.setattr(settings, "log_email_bodies", True)
    with caplog.at_level(logging.INFO):
        email_service.send_invite("new@example.com", "https://example.com/accept?token=abc", "viewer")
    assert "https://example.com/accept?token=abc" in caplog.text and "new@example.com" not in caplog.text


def test_invite_unconfigured_in_production_does_not_log_the_link(monkeypatch, caplog):
    monkeypatch.setattr(settings, "resend_api_key", "placeholder")
    monkeypatch.setattr(settings, "environment", "production")
    with caplog.at_level(logging.INFO):
        assert email_service.send_invite("new@example.com", "https://example.com/accept?token=abc", "viewer") is False
    assert "token=abc" not in caplog.text


def test_invite_route_says_so_when_the_email_was_sent(client, auth_headers, resend_calls):
    res = client.post("/api/v1/auth/invite", json={"email": "new@example.com", "role": "viewer"}, headers=auth_headers)
    assert res.status_code == 201
    assert res.json()["email_sent"] is True
    assert res.json()["detail"] == "Invitation sent"


def test_invite_route_does_not_pretend_when_the_email_failed(client, auth_headers, resend_calls):
    behaviour, _ = resend_calls
    behaviour["error"] = RuntimeError("down")
    res = client.post("/api/v1/auth/invite", json={"email": "new@example.com", "role": "viewer"}, headers=auth_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["email_sent"] is False
    assert "could not be sent" in body["detail"]
    # the token is in the fragment, which a browser never sends to a server
    assert "accept-invite#token=" in body["invite_link"]
    assert "?" not in body["invite_link"]


def test_invite_link_is_built_from_the_dashboard_url(client, auth_headers, resend_calls, monkeypatch):
    monkeypatch.setattr(settings, "dashboard_url", "https://phaemos.example.com/")
    res = client.post("/api/v1/auth/invite", json={"email": "new@example.com", "role": "viewer"}, headers=auth_headers)
    assert res.json()["invite_link"].startswith("https://phaemos.example.com/accept-invite#token=")


def test_invite_route_needs_a_token(client, resend_calls):
    res = client.post("/api/v1/auth/invite", json={"email": "new@example.com", "role": "viewer"})
    assert res.status_code in (401, 403)


def test_invite_route_refuses_a_viewer(client, db, resend_calls):
    from app.models.user import User
    from app.routes.auth import create_access_token
    viewer = User(name="Viewer", email="viewer@test.com", password_hash="x", role="viewer")
    db.add(viewer)
    db.flush()
    token = create_access_token({"sub": str(viewer.id), "role": viewer.role})
    res = client.post("/api/v1/auth/invite", json={"email": "new@example.com", "role": "viewer"},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_the_dashboard_url_defaults_to_local_development():
    assert type(settings).model_fields["dashboard_url"].default == "http://localhost:3000"


def test_alert_email_goes_to_every_listed_recipient(monkeypatch, resend_calls):
    _, calls = resend_calls
    monkeypatch.setattr(settings, "alert_email_to", " ops@example.com, ,oncall@example.com ")
    assert notify_service.send_email_alert("PHAEMOS [CRITICAL] Pump", "temperature is 99") is True
    assert calls[0]["to"] == ["ops@example.com", "oncall@example.com"]
    assert calls[0]["text"] == "temperature is 99"


def test_alert_email_with_no_address_sends_nothing(monkeypatch, resend_calls):
    _, calls = resend_calls
    monkeypatch.setattr(settings, "alert_email_to", " , ")
    assert notify_service.send_email_alert("subject", "body") is False
    assert calls == []


def test_alert_email_failure_does_not_raise(monkeypatch, resend_calls):
    behaviour, _ = resend_calls
    behaviour["error"] = RuntimeError("down")
    monkeypatch.setattr(settings, "alert_email_to", "ops@example.com")
    assert notify_service.send_email_alert("subject", "body") is False
