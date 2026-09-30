"""Streams realistic readings from a simulated PHAEMOS node, healthy or developing a fault.

Usage:
  phaemos-sim --node esp32 --count 20 --dry-run
  phaemos-sim --node esp32 --fault bearing --api-url http://localhost:8000 --api-key <device key>
"""

import argparse
import json
import random
import time
from collections.abc import Iterator
from typing import Any

from .api import PhaemosClient
from .nodes import FAULTS, HEALTHY, NODES


def readings(
    node_type: str, device_id: str, count: int, fault: str | None = None, seed: int | None = None
) -> Iterator[dict[str, Any]]:
    """Yield `count` readings. A fault ramps from nothing to full severity over the run."""
    if node_type not in NODES:
        raise ValueError(f"unknown node type {node_type!r}, choose from {sorted(NODES)}")
    if fault is not None and fault not in FAULTS:
        raise ValueError(f"unknown fault {fault!r}, choose from {sorted(FAULTS)}")
    rng = random.Random(seed)
    node = NODES[node_type]
    for i in range(count):
        severity = i / max(count - 1, 1) if fault else 0.0
        reading: dict[str, Any] = {"device_id": device_id, "node_type": node.node_type}
        for field in node.fields:
            mean, sd = HEALTHY[field]
            factor = 1.0 + (FAULTS.get(fault or "", {}).get(field, 1.0) - 1.0) * severity
            reading[field] = round(rng.gauss(mean * factor, sd), 3)
        if "gas_level" in reading:
            reading["gas_alert"] = reading["gas_level"] > 600
        if "moisture_level" in reading:
            reading["water_detected"] = reading["moisture_level"] > 85
        yield reading


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="phaemos-sim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--node", default="esp32", choices=sorted(NODES))
    parser.add_argument("--fault", choices=sorted(FAULTS))
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between readings")
    parser.add_argument("--device-id", default="sim-node")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--api-key", help="the device API key from registering the device")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dry-run", action="store_true", help="print readings instead of sending them")
    args = parser.parse_args(argv)

    stream = readings(args.node, args.device_id, args.count, args.fault, args.seed)
    if args.dry_run:
        for reading in stream:
            print(json.dumps(reading))
        return
    if not args.api_key:
        parser.error("--api-key is required unless --dry-run is set")
    with PhaemosClient(args.api_url, api_key=args.api_key) as client:
        for n, reading in enumerate(stream, start=1):
            stored = client.send_reading(reading)
            flag = "ANOMALY" if stored.get("is_anomaly") else "ok"
            print(f"{n:>4} {args.node} score={stored.get('anomaly_score')} {flag}")
            if n < args.count:
                time.sleep(args.interval)


if __name__ == "__main__":
    main()
