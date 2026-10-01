# Edge

`phaemos-edge`, a small gateway that runs next to the machines (a Raspberry Pi or any Linux box) and makes sure no reading is lost when the network is not.

> [!NOTE]
> This folder is published to [phaemos/edge](https://github.com/phaemos/edge) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

## What it does

1. Reads readings as JSON lines on standard input, for example from a node's serial port.
2. Checks each line is a real reading (a JSON object with a `device_id`) and skips anything else.
3. Appends it to a spool file on disk and syncs it before doing anything else.
4. Forwards spooled readings to the API in order. On failure it keeps them and retries with backoff (1, 2, 4 seconds and so on, capped at one minute).

A crash, reboot or outage leaves the spool intact. Forwarding resumes where it stopped.

## Running it

```bash
cargo build --release
cat /dev/ttyUSB0 | ./target/release/phaemos-edge \
  --api-url https://api.phaemos.com \
  --api-key <device key> \
  --spool /var/lib/phaemos/spool.jsonl
```

The key can also come from `PHAEMOS_API_KEY`.

## Why Rust

The gateway runs unattended for months on small hardware. Rust gives a single 3 MB binary with no runtime, cross-compiles to ARM for a Raspberry Pi and rules out whole classes of crash. See ADR 020 in [docs/decisions.md](https://github.com/phaemos/phaemos/blob/main/docs/decisions.md).

## Development

```bash
cargo test
cargo clippy --all-targets -- -D warnings
```

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
