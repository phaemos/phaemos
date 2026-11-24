import logging

import httpx
import pytest

from app.config import settings
from app.services import notify_service

SECRET_URL = "https://discord.com/api/webhooks/123/very-secret-token"


@pytest.fixture
def discord(monkeypatch):
    # backs the HTTP client with a mock transport, so no test reaches the network
    behaviour = {"handler": lambda request: httpx.Response(204)}
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: behaviour["handler"](request))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(notify_service.httpx, "Client", factory)
    monkeypatch.setattr(settings, "discord_webhook_url", SECRET_URL)
    return behaviour


def test_error_status_logs_the_status_and_not_the_webhook_url(discord, caplog):
    discord["handler"] = lambda request: httpx.Response(401, text="no")
    with caplog.at_level(logging.WARNING):
        notify_service.send_discord_alert("pump hot", "critical")
    assert "HTTP 401" in caplog.text
    assert "very-secret-token" not in caplog.text
    assert "discord.com" not in caplog.text


def test_network_error_logs_the_type_and_not_the_webhook_url(discord, caplog):
    def boom(request):
        raise httpx.ConnectTimeout(f"timed out calling {request.url}", request=request)

    discord["handler"] = boom
    with caplog.at_level(logging.WARNING):
        notify_service.send_discord_alert("pump hot", "critical")
    assert "ConnectTimeout" in caplog.text
    assert "very-secret-token" not in caplog.text
