"""
Webhook delivery checks, the heavy-read limits, the uvicorn log filter, IPv6 rate-limit keys and the
start-up flags and proxy settings that protect the live socket.
"""

import logging
import re
import threading
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings
from app.limiter import _real_ip, normalise_address
from app.logging_config import StripQueryStrings, configure_logging
from app.models.webhook import Webhook
from app.services import heavy_reads, url_safety, webhook_service
from app.services.webhook_service import WebhookTarget, deliver_all

REPO = Path(__file__).resolve().parents[2]

# the test container mounts backend/ only, so the Dockerfile and the Nginx file are not there. These checks run
# from a checkout of the whole repo (python -m pytest backend/tests/test_hardening.py from the repo root) and in
# CI. They skip where the file is absent
_DOCKERFILE = REPO / "backend" / "Dockerfile"
_NGINX = REPO / "infra" / "nginx" / "api.phaemos.com.conf"
needs_dockerfile = pytest.mark.skipif(not _DOCKERFILE.is_file(), reason="backend/Dockerfile is not present in this environment")
needs_nginx = pytest.mark.skipif(not _NGINX.is_file(), reason="infra/nginx/api.phaemos.com.conf is not present in this environment")


def _resolves_to(monkeypatch, *addresses):
    def fake(host, port, *args, **kwargs):
        return [(2, 1, 6, "", (a, port or 443)) for a in addresses]
    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fake)


# ── webhook delivery ────────────────────────────────────────────────────────

class _FakeClient:
    posts: list = []
    status = 200

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, content=None, headers=None, extensions=None):
        _FakeClient.posts.append({"url": url, "headers": headers, "extensions": extensions, "body": content})
        return httpx.Response(_FakeClient.status, request=httpx.Request("POST", url))


@pytest.fixture
def fake_http(monkeypatch):
    _FakeClient.posts = []
    _FakeClient.status = 200
    monkeypatch.setattr("app.services.webhook_service.httpx.Client", _FakeClient)
    return _FakeClient


class _KeepOpen:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


CONTEXT = {"device_name": "Press", "metric": "temperature", "value": 90, "threshold": 80, "severity": "critical"}


def test_pinning_swaps_the_name_for_the_checked_address_and_keeps_the_name_for_tls(monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    url, headers, ext = url_safety.pin_outbound_url("https://hooks.example.org:8443/a/b?x=1")
    assert url == "https://8.8.8.8:8443/a/b?x=1"
    assert headers == {"Host": "hooks.example.org:8443"}
    assert ext == {"sni_hostname": "hooks.example.org"}


def test_pinning_brackets_an_ipv6_address_and_leaves_a_literal_alone(monkeypatch):
    _resolves_to(monkeypatch, "2001:4860:4860::8888")
    assert url_safety.pin_outbound_url("https://hooks.example.org/a")[0] == "https://[2001:4860:4860::8888]/a"
    assert url_safety.pin_outbound_url("https://8.8.8.8/a") == ("https://8.8.8.8/a", {}, {})


def test_http_in_development_is_pinned_without_a_tls_name(monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    monkeypatch.setattr(settings, "environment", "development")
    url, headers, ext = url_safety.pin_outbound_url("http://hooks.example.org/a")
    assert (url, headers, ext) == ("http://8.8.8.8/a", {"Host": "hooks.example.org"}, {})


def test_delivery_connects_to_the_checked_address(monkeypatch, fake_http):
    _resolves_to(monkeypatch, "8.8.8.8")
    deliver_all([WebhookTarget(name="ok", url="https://hooks.example.org/x", template=None)], CONTEXT)
    (post,) = fake_http.posts
    assert post["url"] == "https://8.8.8.8/x"
    assert post["headers"]["Host"] == "hooks.example.org"
    assert post["extensions"] == {"sni_hostname": "hooks.example.org"}


@pytest.fixture(autouse=True)
def forget_unsafe_sightings():
    webhook_service._unsafe_since.clear()
    yield
    webhook_service._unsafe_since.clear()


class _Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr("app.services.webhook_service.time.monotonic", clock)
    return clock


def test_a_webhook_is_switched_off_only_when_the_finding_holds_for_a_minute(db, monkeypatch, fake_http, clock):
    _resolves_to(monkeypatch, "10.0.0.9")
    monkeypatch.setattr("app.services.webhook_service.SessionLocal", lambda: _KeepOpen(db))
    row = Webhook(name="moved", url="https://hooks.example.org/x", enabled=True)
    db.add(row)
    db.flush()
    target = WebhookTarget(name="moved", url=row.url, template=None, id=str(row.id))
    # the first sighting is not enough and is a failed send so the next reading tries again
    assert deliver_all([target], CONTEXT) is False
    db.refresh(row)
    assert row.enabled is True and row.disabled_reason is None
    # a second sighting inside the minute is still not enough
    clock.now += 30
    assert deliver_all([target], CONTEXT) is False
    db.refresh(row)
    assert row.enabled is True
    # held for a minute: now it is switched off, with the reason
    clock.now += 31
    assert deliver_all([target], CONTEXT) is True
    db.refresh(row)
    assert row.enabled is False
    assert "private or reserved" in row.disabled_reason
    assert fake_http.posts == []


def test_a_safe_result_in_between_clears_the_sighting(db, monkeypatch, fake_http, clock):
    monkeypatch.setattr("app.services.webhook_service.SessionLocal", lambda: _KeepOpen(db))
    row = Webhook(name="blip", url="https://hooks.example.org/x", enabled=True)
    db.add(row)
    db.flush()
    target = WebhookTarget(name="blip", url=row.url, template=None, id=str(row.id))
    _resolves_to(monkeypatch, "10.0.0.9")
    deliver_all([target], CONTEXT)
    clock.now += 40
    _resolves_to(monkeypatch, "8.8.8.8")
    assert deliver_all([target], CONTEXT) is True
    # the next bad result is a first sighting again, not the second
    clock.now += 40
    _resolves_to(monkeypatch, "10.0.0.9")
    deliver_all([target], CONTEXT)
    db.refresh(row)
    assert row.enabled is True


def test_a_dns_failure_never_switches_a_webhook_off(db, monkeypatch, fake_http, clock):
    import socket

    def fail(*args, **kwargs):
        raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", fail)
    monkeypatch.setattr("app.services.webhook_service.SessionLocal", lambda: _KeepOpen(db))
    row = Webhook(name="dns", url="https://hooks.example.org/x", enabled=True)
    db.add(row)
    db.flush()
    target = WebhookTarget(name="dns", url=row.url, template=None, id=str(row.id))
    # however many times and however far apart, it is only a failed send
    for _ in range(4):
        assert deliver_all([target], CONTEXT) is False
        clock.now += 120
    db.refresh(row)
    assert row.enabled is True and row.disabled_reason is None
    assert fake_http.posts == []


def test_a_row_saved_before_the_check_existed_is_covered_at_delivery(db, monkeypatch, fake_http, clock):
    monkeypatch.setattr("app.services.webhook_service.SessionLocal", lambda: _KeepOpen(db))
    row = Webhook(name="old", url="https://127.0.0.1/hook", enabled=True)
    db.add(row)
    db.flush()
    targets = webhook_service.enabled_targets(db)
    deliver_all(targets, CONTEXT)
    clock.now += 61
    deliver_all(targets, CONTEXT)
    assert fake_http.posts == []
    db.refresh(row)
    assert row.enabled is False and row.disabled_reason


def test_candidates_put_ipv4_first_and_cover_every_checked_address(monkeypatch):
    _resolves_to(monkeypatch, "2603:1036:1::5", "52.96.10.1")
    urls = [c[0] for c in url_safety.outbound_candidates("https://hooks.example.org/a")]
    assert urls == ["https://52.96.10.1/a", "https://[2603:1036:1::5]/a"]
    assert url_safety.pin_outbound_url("https://hooks.example.org/a")[0] == "https://52.96.10.1/a"


def test_one_forbidden_address_among_public_ones_still_refuses_the_host(monkeypatch):
    _resolves_to(monkeypatch, "52.96.10.1", "10.0.0.2")
    with pytest.raises(url_safety.UnsafeUrl):
        url_safety.outbound_candidates("https://hooks.example.org/a")


def test_delivery_falls_back_to_the_next_address_when_one_cannot_be_reached(monkeypatch):
    _resolves_to(monkeypatch, "52.96.10.1", "2603:1036:1::5")
    tried = []

    class Flaky(_FakeClient):
        def post(self, url, json=None, content=None, headers=None, extensions=None):
            tried.append(url)
            if "52.96.10.1" in url:
                raise httpx.ConnectError("no route")
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.webhook_service.httpx.Client", Flaky)
    assert deliver_all([WebhookTarget(name="dual", url="https://hooks.example.org/a", template=None)], CONTEXT) is True
    assert tried == ["https://52.96.10.1/a", "https://[2603:1036:1::5]/a"]


def test_delivery_stops_at_a_server_that_answered(monkeypatch):
    _resolves_to(monkeypatch, "52.96.10.1", "2603:1036:1::5")
    tried = []

    class Refusing(_FakeClient):
        def post(self, url, json=None, content=None, headers=None, extensions=None):
            tried.append(url)
            return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.webhook_service.httpx.Client", Refusing)
    assert deliver_all([WebhookTarget(name="down", url="https://hooks.example.org/a", template=None)], CONTEXT) is False
    # three tries on the same address (a 500 may pass) and no move to the other, which would reach the same server
    assert tried == ["https://52.96.10.1/a"] * 3


def test_an_address_with_a_user_name_and_password_is_refused(monkeypatch):
    _resolves_to(monkeypatch, "8.8.8.8")
    with pytest.raises(url_safety.UnsafeUrl) as refused:
        url_safety.check_outbound_url("https://user:secret@hooks.example.org/a")
    assert "user name" in str(refused.value)


def test_a_bad_template_does_not_stop_the_webhooks_after_it(monkeypatch, fake_http):
    _resolves_to(monkeypatch, "8.8.8.8")
    targets = [
        WebhookTarget(name="bad", url="https://a.example.org/x", template="{no_such_placeholder}"),
        WebhookTarget(name="good", url="https://b.example.org/x", template=None),
    ]
    assert deliver_all(targets, CONTEXT) is True
    assert [p["headers"]["Host"] for p in fake_http.posts] == ["b.example.org"]


def test_the_test_send_is_pinned_and_refuses_an_unsafe_address(monkeypatch, fake_http):
    _resolves_to(monkeypatch, "8.8.8.8")
    assert webhook_service.test_webhook(Webhook(name="t", url="https://hooks.example.org/x")).ok is True
    assert fake_http.posts[0]["url"] == "https://8.8.8.8/x"
    _resolves_to(monkeypatch, "192.168.0.4")
    assert webhook_service.test_webhook(Webhook(name="t", url="https://hooks.example.org/x")).ok is False


def test_switching_a_webhook_back_on_checks_its_address_and_clears_the_reason(client, db, monkeypatch):
    from app.models.user import User
    from app.routes.auth import hash_password
    admin = User(name="A", email="wh-admin@test.com", password_hash=hash_password("Passw0rd!x"), role="admin")
    db.add(admin)
    row = Webhook(name="off", url="https://hooks.example.org/x", enabled=False, disabled_reason="was private")
    db.add(row)
    db.flush()
    from app.routes.auth import create_access_token
    headers = {"Authorization": f"Bearer {create_access_token({'sub': str(admin.id), 'role': 'admin'})}"}
    _resolves_to(monkeypatch, "10.1.1.1")
    proof = {"password": "Passw0rd!x"}
    assert client.patch(f"/api/v1/webhooks/{row.id}", json={"enabled": True, **proof}, headers=headers).status_code == 422
    _resolves_to(monkeypatch, "8.8.8.8")
    res = client.patch(f"/api/v1/webhooks/{row.id}", json={"enabled": True, **proof}, headers=headers)
    assert res.status_code == 200 and res.json()["enabled"] is True and res.json()["disabled_reason"] is None


# ── heavy reads ─────────────────────────────────────────────────────────────

def test_an_export_is_limited_per_person_per_minute():
    for _ in range(heavy_reads.RATES["export"]):
        with heavy_reads.heavy_read("u1", "export"):
            pass
    with pytest.raises(HTTPException) as refused:
        with heavy_reads.heavy_read("u1", "export"):
            pass
    assert refused.value.status_code == 429
    # another person has their own allowance
    with heavy_reads.heavy_read("u2", "export"):
        pass


def test_one_person_cannot_run_more_than_two_at_once_and_the_slot_is_freed(monkeypatch):
    monkeypatch.setitem(heavy_reads.RATES, "bucket", 1000)
    with heavy_reads.heavy_read("u3", "bucket"):
        with heavy_reads.heavy_read("u3", "bucket"):
            with pytest.raises(HTTPException) as refused:
                with heavy_reads.heavy_read("u3", "bucket"):
                    pass
            assert refused.value.status_code == 429
    # both released, so a new one starts
    with heavy_reads.heavy_read("u3", "bucket"):
        pass


def test_a_failed_read_still_frees_its_slot(monkeypatch):
    monkeypatch.setitem(heavy_reads.RATES, "bucket", 1000)
    for _ in range(5):
        with pytest.raises(RuntimeError):
            with heavy_reads.heavy_read("u4", "bucket"):
                raise RuntimeError("the query failed")


def test_the_process_wide_ceiling_applies_across_people(monkeypatch):
    monkeypatch.setitem(heavy_reads.RATES, "bucket", 1000)
    stack = []
    try:
        for n in range(heavy_reads.MAX_AT_ONCE_TOTAL):
            cm = heavy_reads.heavy_read(f"user-{n}", "bucket")
            cm.__enter__()
            stack.append(cm)
        with pytest.raises(HTTPException) as refused:
            with heavy_reads.heavy_read("someone-else", "bucket"):
                pass
        assert refused.value.status_code == 429
    finally:
        for cm in reversed(stack):
            cm.__exit__(None, None, None)


def test_heavy_reads_hold_up_under_threads():
    results = []

    def work():
        try:
            with heavy_reads.heavy_read("u5", "bucket"):
                results.append("ran")
        except HTTPException:
            results.append("refused")

    threads = [threading.Thread(target=work) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 10 and "ran" in results


# ── the uvicorn connection line ─────────────────────────────────────────────

def test_a_query_string_never_reaches_the_uvicorn_log(caplog):
    configure_logging(settings.environment)
    logger = logging.getLogger("uvicorn.error")
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logger.info('%s - "WebSocket %s" [accepted]', ("127.0.0.1", 49475), "/ws/telemetry/abc?token=SECRET.ACCESS.TOKEN")
    assert "SECRET.ACCESS.TOKEN" not in caplog.text
    assert "token=" not in caplog.text
    # the rest of the line is kept
    assert "/ws/telemetry/abc" in caplog.text and "[accepted]" in caplog.text


def test_the_filter_strips_every_query_string_in_any_message(caplog):
    configure_logging(settings.environment)
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info("GET /a?x=1&y=2 and /b?z=3 done")
    assert "x=1" not in caplog.text and "z=3" not in caplog.text and "/a and /b done" in caplog.text


def test_the_filter_is_added_once_however_often_logging_is_configured():
    for _ in range(3):
        configure_logging(settings.environment)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert sum(isinstance(f, StripQueryStrings) for f in logging.getLogger(name).filters) == 1


def test_a_message_with_no_query_string_is_untouched(caplog):
    configure_logging(settings.environment)
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logging.getLogger("uvicorn.error").info("Started server process [%d]", 7)
    assert "Started server process [7]" in caplog.text


# ── rate limits keyed on the /64 ────────────────────────────────────────────

def test_ipv6_clients_are_keyed_on_their_64():
    assert normalise_address("2001:db8:1:2:aaaa::1") == normalise_address("2001:db8:1:2:bbbb:cccc:dddd:eeee")
    assert normalise_address("2001:db8:1:2::1") != normalise_address("2001:db8:1:3::1")
    assert normalise_address("203.0.113.9") == "203.0.113.9"
    assert normalise_address("::ffff:203.0.113.9") == "203.0.113.9"
    assert normalise_address("testclient") == "testclient"


def _request(peer, real_ip=None):
    headers = [(b"x-real-ip", real_ip.encode())] if real_ip else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/"})


def test_the_limiter_key_for_a_proxied_ipv6_client_is_its_64():
    a = _real_ip(_request("127.0.0.1", "2001:db8:5:6::1"))
    b = _real_ip(_request("127.0.0.1", "2001:db8:5:6:ffff::9"))
    assert a == b == "2001:db8:5:6::/64"


def test_an_untrusted_peer_cannot_choose_its_key():
    assert _real_ip(_request("203.0.113.50", "198.51.100.1")) == "203.0.113.50"


# ── start-up flags and the proxy ────────────────────────────────────────────

def _dockerfile_command():
    text = _DOCKERFILE.read_text()
    line = next(row for row in text.splitlines() if row.startswith("CMD"))
    return re.findall(r'"([^"]*)"', line)


@needs_dockerfile
def test_uvicorn_starts_with_the_socket_and_concurrency_limits():
    cmd = _dockerfile_command()
    assert cmd[0] == "uvicorn"
    assert int(cmd[cmd.index("--ws-max-size") + 1]) <= 8192
    assert cmd[cmd.index("--ws-per-message-deflate") + 1] == "false"
    assert 0 < int(cmd[cmd.index("--limit-concurrency") + 1]) <= 200
    assert "--no-access-log" in cmd


@needs_dockerfile
def test_the_frame_size_cap_is_not_below_what_the_auth_frame_needs():
    from app.routes.ws import FIRST_FRAME_MAX_CHARS
    cmd = _dockerfile_command()
    # the first frame arrives whole, so the server's own cap must be at least the cap the app applies
    assert int(cmd[cmd.index("--ws-max-size") + 1]) >= FIRST_FRAME_MAX_CHARS


@needs_dockerfile
def test_the_image_refuses_to_build_on_a_python_older_than_3_12_4():
    assert "sys.version_info >= (3, 12, 4)" in _DOCKERFILE.read_text()


@needs_nginx
def test_nginx_limits_connections_per_address_for_sockets_and_for_the_api():
    conf = _NGINX.read_text()
    assert re.search(r"limit_conn_zone \$binary_remote_addr zone=ws_per_addr", conf)
    assert re.search(r"location /ws/ \{[^}]*limit_conn ws_per_addr 10;", conf, re.S)
    assert re.search(r"location / \{[^}]*limit_conn api_per_addr 100;", conf, re.S)
