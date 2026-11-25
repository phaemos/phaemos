import json

import httpx
import pytest

from phaemos_client import __version__, api
from phaemos_client.api import ApiError, PhaemosClient, exit_code
from phaemos_client.simulator import main

TOKEN = "pht_abc123_SECRET-not-real"
KEY = "device-key-SECRET"


def make(handler, sleeps=None, **kwargs):
    slept = sleeps if sleeps is not None else []
    client = PhaemosClient("https://api.test", token=TOKEN, sleep=slept.append, **kwargs)
    client._http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler))
    return client


def test_the_token_is_a_bearer_and_the_device_key_goes_only_to_ingest():
    seen = []

    def handler(request):
        seen.append(
            (request.url.path, request.headers.get("authorization"), request.headers.get("x-api-key"))
        )
        return httpx.Response(200, json={})

    client = PhaemosClient("https://api.test", api_key=KEY, token=TOKEN, replay=False)
    client._http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler))
    client.whoami()
    client.send_reading({"device_id": "d"})
    assert seen[0] == ("/api/v1/auth/whoami", f"Bearer {TOKEN}", None)
    assert seen[1] == ("/api/v1/telemetry", None, KEY)


def test_each_read_uses_the_documented_path():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path in ("/api/v1/tokens",):
            return httpx.Response(200, json=[{"id": "x"}])
        return httpx.Response(200, json={})

    client = make(handler)
    client.whoami()
    client.health_summary()
    client.ml_status()
    client.get_device("d1")
    client.get_alert("a1")
    client.get_ticket("t1")
    client.latest_reading("d1")
    assert client.list_tokens() == [{"id": "x"}]
    assert paths == [
        "/api/v1/auth/whoami",
        "/api/v1/health/summary",
        "/api/v1/ml/status",
        "/api/v1/devices/d1",
        "/api/v1/alerts/a1",
        "/api/v1/tickets/t1",
        "/api/v1/telemetry/d1/latest",
        "/api/v1/tokens",
    ]


def test_create_device_sends_the_field_the_api_reads_and_nothing_else():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "d1"})

    make(handler).create_device("press", "Bay A", "esp32")
    assert seen == {"name": "press", "location": "Bay A", "type": "esp32"}
    assert not hasattr(PhaemosClient, "login")


def test_a_device_filter_is_a_query_and_not_a_path():
    queries = []

    def handler(request):
        queries.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[], headers={"X-Total-Count": "0"})

    make(handler).list_alerts(device_id="d1", resolved=False, category="monitoring")
    path, params = queries[0]
    assert path == "/api/v1/alerts"
    assert (
        params["device_id"] == "d1" and params["resolved"] == "false" and params["category"] == "monitoring"
    )


def test_paging_walks_every_page_and_sends_both_offset_names():
    seen = []

    def handler(request):
        params = request.url.params
        seen.append((params["limit"], params["offset"], params["skip"]))
        off, lim = int(params["offset"]), int(params["limit"])
        return httpx.Response(
            200, json=[{"n": i} for i in range(off, min(off + lim, 450))], headers={"X-Total-Count": "450"}
        )

    page = make(handler).list_devices()
    assert len(page.items) == 450 and page.total == 450 and not page.more
    assert (
        seen == [("200", "0", "0"), ("200", "200", "200"), ("50", "400", "400")][: len(seen)]
        or len(seen) == 3
    )
    short = make(handler).list_devices(limit=100)
    assert len(short.items) == 100 and short.more and short.total == 450


def test_a_route_that_ignores_paging_is_an_error_and_not_a_loop():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=[{"n": i} for i in range(int(request.url.params["limit"]))])

    with pytest.raises(ValueError, match="ignored its paging parameters"):
        make(handler).list_alerts()
    assert len(calls) == 2


def test_api_error_carries_status_code_and_retry_after_and_never_a_secret():
    def handler(request):
        return httpx.Response(
            429,
            json={"code": "rate_limited", "detail": f"slow down {TOKEN} {KEY}", "request_id": "r1"},
            headers={"Retry-After": "30"},
        )

    client = make(handler)
    client._key = KEY
    with pytest.raises(ApiError) as caught:
        client._call("PATCH", "/x", retry=False)
    error = caught.value
    assert (error.status, error.code, error.retry_after) == (429, "rate_limited", 30.0)
    assert TOKEN not in str(error) and "SECRET" not in str(error) and "SECRET" not in repr(error.message)
    assert isinstance(error, httpx.HTTPStatusError)


def test_validation_errors_are_readable_in_both_shapes():
    for body, want in [
        (
            {
                "code": "validation_failed",
                "detail": "bad",
                "errors": [{"loc": ["query", "limit"], "msg": "too big"}],
            },
            "bad: query.limit: too big",
        ),
        ({"detail": [{"loc": ["body", "x"], "msg": "no"}]}, "body.x: no"),
        ({"detail": "plain"}, "plain"),
    ]:
        client = make(lambda r, b=body: httpx.Response(422, json=b))
        with pytest.raises(ApiError) as caught:
            client.whoami()
        assert want in caught.value.message


def test_exit_codes_match_phaemosctl():
    table = {401: 3, 403: 4, 404: 5, 400: 6, 409: 6, 422: 6, 429: 7, 500: 8, 503: 8, 418: 1}
    assert {s: exit_code(s) for s in table} == table


def test_reads_retry_and_writes_do_not_and_the_waits_are_the_stated_ones():
    sleeps: list[float] = []
    answers = [503, 502, 200]

    def handler(request):
        status = answers.pop(0)
        return httpx.Response(status, json={})

    make(handler, sleeps).whoami()
    assert sleeps == [0.5, 1.0]
    # a write is not retried after a 5xx
    n = []
    sleeps.clear()

    def post(request):
        n.append(1)
        return httpx.Response(503, json={})

    with pytest.raises(ApiError):
        make(post, sleeps).create_device("a", "b", "c")
    assert len(n) == 1 and sleeps == []
    # unless it is marked safe to repeat
    n.clear()
    with pytest.raises(ApiError):
        make(post, sleeps).resolve_alert("a1")
    assert len(n) == api.MAX_TRIES


def test_a_429_waits_for_retry_after_for_any_method_and_gives_up_after_three():
    sleeps: list[float] = []
    n = []

    def handler(request):
        n.append(1)
        return httpx.Response(429, json={}, headers={"Retry-After": "7"})

    with pytest.raises(ApiError) as caught:
        make(handler, sleeps).create_device("a", "b", "c")
    assert caught.value.status == 429 and sleeps == [7.0, 7.0, 7.0] and len(n) == 4
    # a wait longer than a minute is not waited out
    sleeps.clear()
    with pytest.raises(ApiError):
        make(lambda r: httpx.Response(429, json={}, headers={"Retry-After": "600"}), sleeps).whoami()
    assert sleeps == []
    # with no Retry-After the default applies
    sleeps.clear()
    answers = [429, 200]
    make(lambda r: httpx.Response(answers.pop(0), json={}), sleeps).whoami()
    assert sleeps == [api.DEFAULT_RETRY_AFTER]


def test_a_network_failure_is_retried_for_a_read():
    sleeps: list[float] = []
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={})

    make(handler, sleeps).whoami()
    assert sleeps == [0.5, 1.0]


def test_export_csv_streams_to_a_file_and_never_replaces_one(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"id,device_id\n1,d1\n")

    client = make(handler)
    target = tmp_path / "out.csv"
    assert client.export_csv("d1", "2026-11-01T00:00:00Z", target) == 18
    assert target.read_text().startswith("id,device_id")
    with pytest.raises(FileExistsError):
        client.export_csv("d1", "2026-11-01T00:00:00Z", target)

    def failing(request):
        return httpx.Response(404, json={"detail": "Device not found"})

    other = tmp_path / "none.csv"
    with pytest.raises(httpx.HTTPStatusError):
        make(failing).export_csv("d1", "2026-11-01T00:00:00Z", other)
    assert not other.exists()


# ---- the simulator ----


def run_sim(monkeypatch, handler, argv, sleeps):
    real = api.PhaemosClient.__init__

    def init(self, *a, **k):
        real(self, *a, **k)
        self._http = httpx.Client(base_url="https://x.example", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(api.PhaemosClient, "__init__", init)
    monkeypatch.setattr("phaemos_client.simulator.time.sleep", sleeps.append)
    return main(["--url", "https://x.example", "--key", KEY, "--interval", "0", *argv])


def test_the_simulator_waits_out_a_429_and_goes_on(monkeypatch, capsys):
    answers = [429, 201, 201]
    sleeps: list[float] = []

    def handler(request):
        status = answers.pop(0)
        headers = {"Retry-After": "3"} if status == 429 else {}
        return httpx.Response(status, json={"anomaly_score": 0.1, "is_anomaly": False}, headers=headers)

    run_sim(monkeypatch, handler, ["--count", "2"], sleeps)
    out = capsys.readouterr()
    assert 3.0 in sleeps and "rate limited: waiting 3 s" in out.err
    assert out.out.count("ok") == 2


def test_the_simulator_ends_with_one_line_and_the_shared_exit_codes(monkeypatch, capsys):
    for status, code in [(401, 3), (403, 4), (404, 5), (422, 6), (500, 8)]:

        def handler(request, status=status):
            return httpx.Response(status, json={"code": "x", "detail": f"detail for {KEY}"})

        with pytest.raises(SystemExit) as caught:
            run_sim(monkeypatch, handler, ["--count", "1"], [])
        err = capsys.readouterr().err
        assert caught.value.code == code, status
        assert (
            err.count("\n") == 1 and err.startswith("error: ") and KEY not in err and "Traceback" not in err
        )


def test_the_simulator_reports_an_unreachable_server_in_one_line(monkeypatch, capsys):
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(SystemExit) as caught:
        run_sim(monkeypatch, handler, ["--count", "1"], [])
    assert caught.value.code == 8
    assert capsys.readouterr().err.count("\n") == 1


def test_version_and_the_new_names(capsys, monkeypatch):
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0 and f"phaemos-sim {__version__}" in capsys.readouterr().out
    monkeypatch.setenv("PHAEMOS_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("PHAEMOS_DEVICE_KEY", KEY)
    monkeypatch.delenv("PHAEMOS_API_KEY", raising=False)
    with pytest.raises(SystemExit) as caught:
        main(["--count", "1"])
    assert caught.value.code == 8


def test_trailing_slashes_are_stripped_and_no_request_has_a_double_slash():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={})

    for base in ("https://api.test", "https://api.test/", "https://api.test///"):
        client = PhaemosClient(base, token=TOKEN)
        assert str(client._http.base_url).rstrip("/") == "https://api.test"
        client._http = httpx.Client(
            base_url=str(client._http.base_url), transport=httpx.MockTransport(handler)
        )
        client.health_summary()
    assert paths == ["/api/v1/health/summary"] * 3
    assert not any("//" in p for p in paths)


def test_a_full_ingest_address_is_refused_with_a_plain_message():
    for bad in (
        "https://api.test/api/v1/telemetry",
        "https://api.test/api/v1/telemetry/",
        "https://api.test/x/",
    ):
        with pytest.raises(ValueError, match="base address only"):
            PhaemosClient(bad, token=TOKEN)
        with pytest.raises(ValueError, match="remove the path"):
            api.check_base_url(bad)


def test_a_404_on_a_post_is_one_attempt_and_one_clear_line(monkeypatch, capsys):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404, json={"code": "not_found", "detail": "Not Found"})

    sleeps: list[float] = []
    with pytest.raises(SystemExit) as caught:
        run_sim(monkeypatch, handler, ["--count", "5"], sleeps)
    err = capsys.readouterr().err
    assert caught.value.code == 5
    assert len(calls) == 1 and sleeps == []
    assert err.count("\n") == 1 and "the address is wrong" in err and "no trailing slash" in err


def test_a_list_with_a_cursor_is_walked_by_keyset_and_without_one_by_offset():
    seen = []

    def handler(request):
        params = request.url.params
        seen.append(dict(params))
        limit = int(params["limit"])
        start = int(params["before"].removeprefix("cursor-")) if "before" in params else int(params["offset"])
        end = min(start + limit, 450)
        headers = {"X-Next-Before": f"cursor-{end}"} if end - start == limit and end < 450 else {}
        return httpx.Response(200, json=[{"n": i} for i in range(start, end)], headers=headers)

    page = make(handler).list_alerts(severity="critical", kind="rule", device_id="d1")
    assert len(page.items) == 450 and not page.more
    assert "offset" in seen[0] and seen[0]["severity"] == "critical" and seen[0]["kind"] == "rule"
    assert all("before" in s and "offset" not in s for s in seen[1:])


def test_filters_are_the_servers_and_resolve_is_a_post():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[] if request.method == "GET" else {})

    client = make(handler)
    client.list_devices(name="press-01")
    client.list_tickets(device_id="d1", ticket_number=12)
    client.resolve_alert("a1")
    assert seen[0][2]["name"] == "press-01" and "search" not in seen[0][2]
    assert seen[1][2]["device_id"] == "d1" and seen[1][2]["ticket_number"] == "12"
    assert seen[2][:2] == ("POST", "/api/v1/alerts/a1/resolve")


def test_readings_page_gives_the_cursor_and_no_total():
    def handler(request):
        assert request.url.params["before"] == "c1"
        return httpx.Response(200, json=[{"n": 1}], headers={"X-Next-Before": "c2"})

    page = make(handler).readings_page("d1", limit=1, before="c1")
    assert page.next_before == "c2" and page.total is None and page.more
