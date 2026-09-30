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
