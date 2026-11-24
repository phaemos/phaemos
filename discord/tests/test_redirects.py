"""The bot token is never sent anywhere else: a redirect is not followed."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from serverkit.http import ApiError, Client


def _serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_redirect_is_refused_and_the_token_never_reaches_the_target():
    seen: list[str | None] = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    target = _serve(Target)

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/stolen")
            self.end_headers()

        def log_message(self, *args):
            pass

    redirector = _serve(Redirector)
    try:
        client = Client(f"http://127.0.0.1:{redirector.server_port}", "secret-token", "DiscordBot (https://example.org, 1.0)", sleep=lambda s: None)
        with pytest.raises(ApiError) as err:
            client.request("GET", "/users/@me")
        assert err.value.status == 302
        assert seen == []
    finally:
        redirector.shutdown()
        target.shutdown()
