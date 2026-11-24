# phaemos-client

A Python client for the PHAEMOS API and `phaemos-sim`, a simulator for the four sensor nodes.

> [!NOTE]
> This folder is published to [phaemos/client](https://github.com/phaemos/client) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

```bash
pip install -e .          # from this folder: nothing is published to a package index yet
phaemos-sim --node esp32 --count 5 --dry-run
PHAEMOS_DEVICE_KEY=<device key> phaemos-sim --node esp32 --fault bearing --url https://api.example.org
```

```python
from phaemos_client import ApiError, PhaemosClient

with PhaemosClient("https://api.example.org", token="pht_...") as client:  # an API token, for reads
    print(client.health_summary())
    for device in client.list_devices(status="offline").items:
        print(device["name"], device["link_state"])
    try:
        client.resolve_alert("0b6c1f0e-1111-4222-8333-444455556666")  # needs the operate scope
    except ApiError as error:
        print(error.status, error.code, error.retry_after)
```

A device posts with its device key: `PhaemosClient(url, api_key=...)` and `send_reading`. An API token is for people and scripts and is sent only as `Authorization: Bearer`. The device key is sent only to the ingest route. Never both on one request.

Reads: `whoami`, `health_summary`, `ml_status`, `list_devices`, `get_device`, `list_alerts`, `get_alert`, `list_tickets`, `get_ticket`, `list_windows`, `list_tokens`, `latest_reading`, `readings` and `export_csv`. Lists return a `Page` with `items`, the server's `total` and `more`. `resolve_alert` needs a token of the `operate` scope and `create_device` the `admin` scope. A token can never make or revoke tokens, rotate a device key or do anything else that needs a person's fresh proof.

Every failure with a status is an `ApiError` (a subclass of `httpx.HTTPStatusError`) with `status`, `code` (the API's stable code when it sends one), `message` and `retry_after`. Read `code` when there is one and `status` when there is not, never the message. A read is retried after a network failure and after 502, 503 and 504 (four tries, waiting 0.5 s then 1 s then 2 s). A 429 waits for `Retry-After` (at most a minute, three times) for any call. A write is never retried unless it is safe to repeat (`resolve_alert` is). The simulator ends with one line and the same exit codes as `phaemosctl`.

Tests: `pip install -e '.[dev]' && python -m pytest`. Nothing here has run against a real server: the tests use a fake that follows `docs/api-reference.md`.

Licence: GNU Affero General Public License v3.0.
