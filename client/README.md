# Client

Tools for talking to a PHAEMOS server from outside the dashboard: a Python SDK with a telemetry simulator and `phaemosctl`, a Go command-line tool for operations and load testing.

> [!NOTE]
> This folder is published to [phaemos/client](https://github.com/phaemos/client) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

| Folder | Language | What it is |
|---|---|---|
| [`python/`](python/) | Python | `phaemos-client` SDK and `phaemos-sim`, a simulator for all four node types with injectable faults |
| [`go/`](go/) | Go | `phaemosctl`: server status, sending readings and load-testing the ingest endpoint |

## Python SDK and simulator

```bash
cd python
pip install -e .
phaemos-sim --node esp32 --count 5 --dry-run
phaemos-sim --node esp32 --fault bearing --count 60 --interval 1 --api-key <device key>
```

The simulator produces realistic readings for the ESP32, STM32, Arduino Nano and Pico 2W nodes. A fault (`bearing`, `overheat`, `leak` or `gas`) ramps from nothing to full severity over the run, which is how to watch the anomaly score climb and alerts fire without any hardware.

```python
from phaemos_client import PhaemosClient

with PhaemosClient("http://localhost:8000", api_key="<device key>") as client:
    stored = client.send_reading({"device_id": "node-1", "temperature": 24.3})
    print(stored["anomaly_score"], stored["is_anomaly"])
```

## phaemosctl

```bash
cd go
go build -o phaemosctl ./cmd/phaemosctl
./phaemosctl status -url http://localhost:8000
./phaemosctl send -key <device key> -json '{"device_id":"node-1","temperature":24.1}'
./phaemosctl load -key <device key> -requests 1000 -concurrency 50
```

`load` reports throughput and p50, p95 and p99 latency, the numbers behind the ingest latency budget.

> [!WARNING]
> Load testing writes real rows. Point it at a development server, never at production.

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
