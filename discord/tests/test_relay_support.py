"""Shared helpers for the relay tests: a webhook receiver on 127.0.0.1 and a runner.

Nothing here reaches Discord or GitHub. The receiver is a small server written with
the standard library that records each request and answers from a script.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import threading
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# the poster is loaded from its own folder, which must not collect bytecode
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RELAY_FILE = ROOT / "relay" / "post.py"
FIXTURES = HERE / "relay_fixtures"
LAYOUT = FIXTURES / "layout.toml"

# the part of each address that tells the receiver which secret was used. The webhook
# path is built from two pieces so that no address-shaped text sits in a test file.
HOOK_PATH = "/api/" + "webhooks/1/"
TOKENS = {
    "DISCORD_WEBHOOK_ANNOUNCEMENTS": "announcetok123",
    "DISCORD_WEBHOOK_RELEASES": "releasestok123",
    "DISCORD_WEBHOOK_FEED": "feedtoken12345",
}


def load_relay() -> Any:
    spec = importlib.util.spec_from_file_location("relay_post_under_test", RELAY_FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their module up by name while the class is being built
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


relay = load_relay()


class Receiver:
    """Records every request. `script` maps a token to answers used in order, then 200."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.script: dict[str, list[tuple[int, dict[str, str], bytes]]] = {}
        self.api: dict[str, tuple[int, dict[str, str], bytes]] = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def _answer(self, record: dict[str, Any]) -> None:
                token = record["path"].rsplit("/", 1)[-1]
                queue = outer.script.get(token)
                if queue:
                    status, headers, body = queue.pop(0)
                else:
                    status, headers, body = 200, {}, b'{"id":"1"}'
                if status == 0:  # a dropped connection
                    self.connection.close()
                    return
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                path, _, query = self.path.partition("?")
                record = {
                    "path": path,
                    "query": query,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "raw": raw,
                    "json": json.loads(raw) if raw else None,
                }
                outer.requests.append(record)
                self._answer(record)

            def do_GET(self) -> None:
                path, _, query = self.path.partition("?")
                outer.requests.append(
                    {
                        "path": path,
                        "query": query,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "method": "GET",
                    }
                )
                status, headers, body = outer.api.get(path, (404, {}, b"{}"))
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def address(self, secret: str) -> str:
        return f"{self.base}{HOOK_PATH}{TOKENS[secret]}"

    def env(self, only: list[str] | None = None) -> dict[str, str]:
        names = only if only is not None else list(TOKENS)
        return {name: self.address(name) for name in names}

    def posts(self) -> list[dict[str, Any]]:
        by_token = {token: name for name, token in TOKENS.items()}
        out = []
        for item in self.requests:
            if item.get("method") == "GET":
                continue
            out.append(
                {
                    "secret": by_token.get(item["path"].rsplit("/", 1)[-1], "UNKNOWN"),
                    "query": item["query"],
                    "payload": item["json"],
                }
            )
        return out


@pytest.fixture
def receiver():
    server = Receiver()
    yield server
    server.close()


def api_env(recorded, receiver):
    """A recorded event may carry the answers GitHub would give. Only then is a token set."""
    api = recorded.get("api")
    if not api:
        return {}
    for path, answer in api.items():
        receiver.api[path] = (answer["status"], {}, json.dumps(answer["body"]).encode())
    return {
        "GITHUB_TOKEN": "token-for-the-api",
        "GITHUB_API_URL": receiver.base,
        "GITHUB_REPOSITORY": "example-org/example",
        "GITHUB_RUN_ID": "99",
    }


def skip_loudly(reason, module=False):
    """Skips and says why in a warning, which pytest prints whatever options are set."""
    warnings.warn(f"relay tests skipped: {reason}", stacklevel=2)
    pytest.skip(reason, allow_module_level=module)


class Run:
    def __init__(self, code: int, out: str, summary: str, sleeps: list[float]) -> None:
        self.code, self.out, self.summary, self.sleeps = code, out, summary, sleeps


def run_relay(
    tmp_path: Path,
    event_name: str,
    event: dict[str, Any],
    receiver: Receiver | None,
    *,
    secrets: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
    layout: Path = LAYOUT,
    clock: list[float] | None = None,
) -> Run:
    """Runs the poster in this process against a recorded event. Sleeping is recorded, not done."""
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(event))
    summary_file = tmp_path / "summary.md"
    summary_file.write_text("")
    env = {
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_EVENT_PATH": str(event_file),
        "GITHUB_STEP_SUMMARY": str(summary_file),
        "RELAY_ALLOW_LOOPBACK": "1",
        "PATH": os.environ.get("PATH", ""),
    }
    if receiver is not None:
        env.update(receiver.env() if secrets is None else secrets)
    elif secrets:
        env.update(secrets)
    env.update(extra_env or {})
    sleeps: list[float] = []
    now = clock if clock is not None else [0.0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    buffer = io.StringIO()
    with (
        mock.patch.dict(os.environ, env, clear=True),
        mock.patch.object(relay, "_sleep", fake_sleep),
        mock.patch.object(relay, "_now", lambda: now[0]),
        contextlib.redirect_stdout(buffer),
    ):
        code = relay.main(["--layout", str(layout)])
    return Run(code, buffer.getvalue(), summary_file.read_text(), sleeps)
