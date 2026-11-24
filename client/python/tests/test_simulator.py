import json

import pytest

from phaemos_client.nodes import FAULTS, HEALTHY, NODES
from phaemos_client.simulator import main, readings


def test_every_node_field_has_a_healthy_range():
    for node in NODES.values():
        assert set(node.fields) <= set(HEALTHY)


def test_every_fault_targets_known_fields():
    for effects in FAULTS.values():
        assert set(effects) <= set(HEALTHY)


def test_healthy_readings_carry_only_the_nodes_fields():
    reading = next(readings("nano", "n1", 1, seed=1))
    assert set(reading) == {"device_id", "node_type", *NODES["nano"].fields, "water_detected"}


def test_bearing_fault_ramps_vibration_up():
    run = list(readings("esp32", "e1", 20, fault="bearing", seed=2))
    assert run[-1]["vib_magnitude"] > 5 * run[0]["vib_magnitude"]
    assert run[-1]["fft_peak_hz"] > 2 * run[0]["fft_peak_hz"]


def test_leak_sets_water_detected_by_the_end():
    run = list(readings("nano", "n1", 30, fault="leak", seed=3))
    assert run[0]["water_detected"] is False
    assert run[-1]["water_detected"] is True


def test_same_seed_same_stream():
    assert list(readings("pico_w", "p", 5, seed=9)) == list(readings("pico_w", "p", 5, seed=9))


def test_unknown_node_is_rejected():
    with pytest.raises(ValueError):
        next(readings("uno", "x", 1))


def test_dry_run_prints_json_lines(capsys):
    main(["--node", "stm32", "--count", "3", "--dry-run", "--seed", "4"])
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["node_type"] == "stm32"


def test_plain_http_to_a_remote_host_is_refused(capsys):
    with pytest.raises(SystemExit):
        main(["--api-url", "http://192.168.1.50:8000", "--api-key", "k", "--count", "1"])
    assert "unencrypted" in capsys.readouterr().err


def test_a_key_is_needed_unless_dry_run(monkeypatch, capsys):
    monkeypatch.delenv("PHAEMOS_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        main(["--count", "1"])
    assert "PHAEMOS_DEVICE_KEY" in capsys.readouterr().err


def test_key_can_come_from_the_environment_and_plain_http_can_be_allowed(monkeypatch, capsys):
    sent = []

    class FakeClient:
        counter = None

        def __init__(self, url, api_key=None, allow_insecure_http=False):
            sent.append((url, api_key, allow_insecure_http))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def send_reading(self, reading):
            return {"anomaly_score": 0.1, "is_anomaly": False}

    monkeypatch.setattr("phaemos_client.simulator.PhaemosClient", FakeClient)
    monkeypatch.setenv("PHAEMOS_API_KEY", "from-env")
    main(["--api-url", "http://192.168.1.50:8000", "--allow-insecure-http", "--count", "1"])
    assert sent == [("http://192.168.1.50:8000", "from-env", True)]
    captured = capsys.readouterr()
    assert "WARNING: plain HTTP" in captured.err
    assert "from-env" not in captured.out + captured.err


def test_a_mistyped_key_option_does_not_echo_the_key(capsys):
    for argv in (
        ["--api-ky", "SECRETKEY123"],
        ["--api-keyy=SECRETKEY123"],
        ["--api-key", "SECRETKEY123", "--bogus"],
    ):
        with pytest.raises(SystemExit):
            main(argv + ["--dry-run"])
        err = capsys.readouterr().err
        assert "SECRETKEY123" not in err
        assert "unrecognised option" in err


def test_terminal_escape_codes_from_a_server_are_not_printed(monkeypatch, capsys):
    class Client:
        counter = None

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def send_reading(self, reading):
            return {"anomaly_score": "\x1b[31mRED\x1b]0;owned\x07", "is_anomaly": False}

    monkeypatch.setattr("phaemos_client.simulator.PhaemosClient", Client)
    main(["--api-url", "https://x.example", "--api-key", "k", "--count", "1"])
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "RED" in out


def test_a_refused_counter_says_so_and_exits_without_server_text(monkeypatch, capsys):
    import httpx

    from phaemos_client.api import ReplayRefused

    class Client:
        counter = None

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def send_reading(self, reading):
            request = httpx.Request("POST", "https://x.example/api/v1/telemetry")
            raise ReplayRefused(
                "the API refused this post (409)",
                request=request,
                response=httpx.Response(409, request=request),
            )

    monkeypatch.setattr("phaemos_client.simulator.PhaemosClient", Client)
    with pytest.raises(SystemExit) as caught:
        main(["--api-url", "https://x.example", "--api-key", "k", "--count", "2"])
    assert caught.value.code == 6
    assert "409" in capsys.readouterr().err


def test_simulated_posts_are_stamped_through_the_real_client(monkeypatch, capsys):
    import httpx

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={"anomaly_score": 0.1, "is_anomaly": False})

    from phaemos_client import api

    real = api.PhaemosClient.__init__

    def init(self, *a, **k):
        real(self, *a, **k)
        self._http = httpx.Client(
            base_url="https://x.example", transport=httpx.MockTransport(handler), headers={"X-API-Key": "k"}
        )

    monkeypatch.setattr(api.PhaemosClient, "__init__", init)
    main(["--api-url", "https://x.example", "--api-key", "k", "--count", "3", "--interval", "0"])
    assert [b["seq"] for b in seen] == [0, 1, 2]
    assert all("boot" in b and "up" in b for b in seen)
