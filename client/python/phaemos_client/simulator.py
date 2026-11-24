"""Streams realistic readings from a simulated PHAEMOS node, healthy or developing a fault.

Usage:
  phaemos-sim --node esp32 --count 20 --dry-run
  PHAEMOS_DEVICE_KEY=<device key> phaemos-sim --node esp32 --fault bearing --api-url https://api.example.org
"""

import argparse
import json
import os
import random
import sys
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__
from .api import (
    DEFAULT_RETRY_AFTER,
    EXIT_CONFLICT,
    EXIT_UNAVAILABLE,
    MAX_429_WAITS,
    MAX_RETRY_AFTER,
    ApiError,
    PhaemosClient,
    ReplayRefused,
    ReplyTooLarge,
    check_base_url,
    error_line,
    exit_code,
    is_duplicate,
    is_local_host,
)
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
    parser.add_argument(
        "--url",
        "--api-url",
        dest="api_url",
        default=os.environ.get("PHAEMOS_URL") or "http://localhost:8000",
        help="the API address (default: PHAEMOS_URL, then http://localhost:8000). --api-url is the old name",
    )
    parser.add_argument(
        "--key",
        "--api-key",
        dest="api_key",
        help="the device key. Prefer the PHAEMOS_DEVICE_KEY environment variable: a key on the command "
        "line shows in the process list. --api-key is the old name",
    )
    parser.add_argument("--version", action="version", version=f"phaemos-sim {__version__}")
    parser.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="allow plain http:// to a host that is not local (bench testing only: the key is not encrypted)",
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dry-run", action="store_true", help="print readings instead of sending them")
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        # only the option names are shown: argparse would print the whole argument. A mistyped
        # key option such as --api-ky would then echo the key that follows it
        names = sorted({item.split("=", 1)[0] for item in unknown if item.startswith("-")})
        parser.error(f"unrecognised option(s): {', '.join(names) if names else '(values with no option)'}")

    stream = readings(args.node, args.device_id, args.count, args.fault, args.seed)
    if args.dry_run:
        for reading in stream:
            print(json.dumps(reading))
        return
    api_key = args.api_key or os.environ.get("PHAEMOS_DEVICE_KEY")
    if not api_key and os.environ.get("PHAEMOS_API_KEY"):
        api_key = os.environ["PHAEMOS_API_KEY"]
        print("warning: PHAEMOS_API_KEY is the old name: use PHAEMOS_DEVICE_KEY", file=sys.stderr)
    if not api_key:
        parser.error("a device key is required unless --dry-run is set: set PHAEMOS_DEVICE_KEY or --key")
    try:
        check_base_url(args.api_url, args.allow_insecure_http)
    except ValueError as error:
        parser.error(str(error))
    if args.api_url.startswith("http://") and not is_local_host(urlsplit(args.api_url).hostname or ""):
        print(
            "WARNING: plain HTTP to a non-local host: the key and readings are not encrypted", file=sys.stderr
        )
    with PhaemosClient(args.api_url, api_key=api_key, allow_insecure_http=args.allow_insecure_http) as client:
        if client.counter is not None and client.counter.warning:
            print(f"WARNING: {client.counter.warning}", file=sys.stderr)
        for n, reading in enumerate(stream, start=1):
            try:
                stored = _send(client, reading)
            except ReplayRefused as error:
                # the message is ours and holds no server text
                print(f"error: {error}", file=sys.stderr)
                raise SystemExit(EXIT_CONFLICT) from None
            except ApiError as error:
                if error.status == 404:
                    # a 404 on a post is a wrong address: reported once and never retried
                    print(
                        "error: the API answered 404 for the telemetry route: the address is wrong. "
                        "Give the base address only (for example https://api.example.org), "
                        "with no path and no trailing slash",
                        file=sys.stderr,
                    )
                    raise SystemExit(exit_code(404)) from None
                print(f"error: {error_line(error)}", file=sys.stderr)
                raise SystemExit(exit_code(error.status)) from None
            except (httpx.TransportError, TimeoutError, ReplyTooLarge) as error:
                print(f"error: cannot get an answer from the server: {type(error).__name__}", file=sys.stderr)
                raise SystemExit(EXIT_UNAVAILABLE) from None
            if is_duplicate(stored):
                print(f"{n:>4} {args.node} duplicate: the API already has this post")
            else:
                flag = "ANOMALY" if stored.get("is_anomaly") else "ok"
                print(f"{n:>4} {args.node} score={shown(stored.get('anomaly_score'))} {flag}")
            if n < args.count:
                time.sleep(args.interval)


def _send(client: PhaemosClient, reading: dict[str, Any]) -> dict[str, Any]:
    """Post one reading. A 429 waits for the Retry-After the server named (at most a minute, three times):
    the device limit is 60 a minute, which an interval under a second would meet."""
    for attempt in range(MAX_429_WAITS + 1):
        try:
            return client.send_reading(reading)
        except ApiError as error:
            if (
                error.status != 429
                or attempt == MAX_429_WAITS
                or (error.retry_after or 10.0) > MAX_RETRY_AFTER
            ):
                raise
            wait = error.retry_after or DEFAULT_RETRY_AFTER
            print(f"warning: rate limited: waiting {wait:g} s", file=sys.stderr)
            time.sleep(wait)
    raise AssertionError("unreachable")


def shown(value: Any) -> str:
    """A server value made safe to print: repr escapes control and terminal escape characters. The
    length is cut so a long string cannot flood the screen."""
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


if __name__ == "__main__":
    main()
