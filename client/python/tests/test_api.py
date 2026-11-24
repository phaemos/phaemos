import json
import shutil
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from phaemos_client import api
from phaemos_client.api import PhaemosClient, ReplayRefused, ReplyTooLarge, check_base_url, is_duplicate


def make_client(handler, api_key="key-123"):
    client = PhaemosClient("https://phaemos.test", api_key=api_key)
    client._http = httpx.Client(
        base_url="https://phaemos.test",
        transport=httpx.MockTransport(handler),
        headers={"X-API-Key": api_key},
    )
    return client


def test_send_reading_posts_with_the_device_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("X-API-Key")
        return httpx.Response(201, json={"anomaly_score": 0.12, "is_anomaly": False})

    with make_client(handler) as client:
        stored = client.send_reading({"device_id": "d1", "temperature": 24.0})
    assert seen == {"path": "/api/v1/telemetry", "key": "key-123"}
    assert stored["is_anomaly"] is False


def test_errors_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid API key"})

    with make_client(handler) as client:
        try:
            client.send_reading({"device_id": "d1"})
        except httpx.HTTPStatusError as error:
            assert error.response.status_code == 401
        else:
            raise AssertionError("expected an HTTP error")


def test_https_and_local_http_are_accepted():
    assert check_base_url("https://api.example.org/") == "https://api.example.org"
    for url in (
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ):
        assert check_base_url(url) == url


def test_names_that_only_look_local_are_not_local():
    for url in ("http://dev.localhost:8000", "http://localhost.example.org", "http://127.0.0.1.example.org"):
        with pytest.raises(ValueError, match="unencrypted"):
            check_base_url(url)


def test_plain_http_to_a_remote_host_needs_the_flag():
    with pytest.raises(ValueError, match="unencrypted"):
        check_base_url("http://192.168.1.50:8000")
    with pytest.raises(ValueError):
        PhaemosClient("http://api.example.org", api_key="k")
    assert check_base_url("http://192.168.1.50:8000", allow_insecure_http=True) == "http://192.168.1.50:8000"


def test_other_addresses_are_refused():
    for bad in ("ftp://x", "api.example.org", "https://user:pw@api.example.org", "https://"):
        with pytest.raises(ValueError):
            check_base_url(bad)


def test_client_checks_certificates_and_does_not_follow_redirects():
    client = PhaemosClient("https://api.example.org", api_key="k")
    assert client._http.follow_redirects is False
    client.close()


def test_a_redirect_is_an_error_and_the_key_is_not_resent():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://elsewhere.example/api/v1/telemetry"})

    with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
        client.send_reading({"device_id": "d1"})
    assert seen == ["phaemos.test"]


def test_error_text_does_not_hold_the_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid API key"})

    client = make_client(handler, api_key="very-secret-key")
    with client, pytest.raises(httpx.HTTPStatusError) as caught:
        client.send_reading({"device_id": "d1"})
    assert "very-secret-key" not in str(caught.value)


class Dripping(httpx.SyncByteStream):
    """A reply body that never ends: one small chunk after another, each taking `pause` seconds."""

    def __init__(self, pause, chunk=b"x"):
        self.pause = pause
        self.chunk = chunk
        self.sent = 0

    def __iter__(self):
        while True:
            time.sleep(self.pause)
            self.sent += len(self.chunk)
            yield self.chunk


def test_an_endless_reply_stops_at_the_cap():
    stream = Dripping(0, chunk=b"y" * 65536)

    def handler(request):
        return httpx.Response(200, stream=stream)

    with make_client(handler) as client, pytest.raises(ReplyTooLarge):
        client.status()
    assert stream.sent <= api.MAX_REPLY_BYTES + 2 * 65536


def test_a_reply_just_under_the_cap_is_read():
    body = json.dumps({"a": "y" * (api.MAX_REPLY_BYTES - 20)}).encode()

    def handler(request):
        return httpx.Response(200, content=body)

    with make_client(handler) as client:
        assert len(client.status()["a"]) == api.MAX_REPLY_BYTES - 20


def test_a_dripped_reply_ends_at_the_wall_clock_deadline():
    stream = Dripping(0.02)

    def handler(request):
        return httpx.Response(200, stream=stream)

    client = make_client(handler)
    client._deadline = 0.3
    began = time.monotonic()
    with client, pytest.raises(TimeoutError):
        client.status()
    assert time.monotonic() - began < 2.0


def test_conflict_is_a_replay_refusal_and_duplicate_is_delivered():
    answers = [
        httpx.Response(409, json={"detail": "older"}),
        httpx.Response(200, json={"status": "duplicate", "stored": False}),
    ]

    def handler(request):
        return answers.pop(0)

    with make_client(handler) as client:
        with pytest.raises(ReplayRefused, match="accept a new counter"):
            client.send_reading({"device_id": "d1"})
        reply = client.send_reading({"device_id": "d1"})
    assert is_duplicate(reply)
    assert not is_duplicate({"status": "ok"})


def test_readings_carry_boot_seq_and_up_and_seq_rises():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={})

    with make_client(handler) as client:
        for _ in range(3):
            client.send_reading({"device_id": "d1"})
    assert [b["seq"] for b in seen] == [0, 1, 2]
    assert len({b["boot"] for b in seen}) == 1
    assert all(isinstance(b["up"], int) for b in seen)


def test_a_pair_the_caller_chose_is_kept():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={})

    with make_client(handler) as client:
        client.send_reading({"device_id": "d1", "boot": 5, "seq": 9})
    assert (seen[0]["boot"], seen[0]["seq"]) == (5, 9)
    assert "up" not in seen[0]


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is needed to make a certificate")
def test_a_certificate_that_is_not_trusted_is_refused(tmp_path):
    # a real TLS server with a self-signed certificate. A client that verifies must refuse it. With
    # verify=False the same request would succeed, so this fails if checking is switched off
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    reached = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            reached.append(1)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = PhaemosClient(f"https://localhost:{server.server_port}", api_key="k")
        with client, pytest.raises(httpx.ConnectError):
            client.status()
        assert not reached
        # the same server is reachable when verification is off, which proves the test can fail
        with httpx.Client(verify=False) as loose:
            assert loose.get(f"https://localhost:{server.server_port}/").status_code == 200
    finally:
        server.shutdown()


def test_no_error_path_puts_the_key_in_the_message():
    key = "very-secret-key"
    cases = {
        "401": lambda r: httpx.Response(401, text="bad " + r.headers["x-api-key"]),
        "409": lambda r: httpx.Response(409),
        "500": lambda r: httpx.Response(500, text=r.headers["x-api-key"]),
        "redirect": lambda r: httpx.Response(302, headers={"location": "https://x.example/"}),
        "not json": lambda r: httpx.Response(200, text="nope " + r.headers["x-api-key"]),
        "too big": lambda r: httpx.Response(200, content=b"x" * (api.MAX_REPLY_BYTES + 10)),
    }
    for name, handler in cases.items():
        client = make_client(lambda r, h=handler: h(r), api_key=key)
        with client, pytest.raises(Exception) as caught:  # noqa: PT011
            client.send_reading({"device_id": "d"})
        assert key not in str(caught.value), name
        assert key not in repr(caught.value), name
