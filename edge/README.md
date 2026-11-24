# Edge

`phaemos-edge`, a small gateway that runs next to the machines (a Raspberry Pi or any Linux box) and keeps readings safe on disk while the network is down. The spool holds up to 8 MiB and drops a reading older than 7 days, so a very long outage can lose the oldest readings.

> [!NOTE]
> This folder is published to [phaemos/edge](https://github.com/phaemos/edge) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

## What it does

0. `phaemos-edge --help` and `phaemos-edge --version` work. An option may be written `--name value` or `--name=value`.
1. A reader thread takes readings as JSON lines on standard input, for example from a node's serial port. A line
   longer than 64 KiB is skipped without being held in memory (`--max-line-bytes` changes the cap). Reading never
   waits for the network, because a forwarding pass is cut short after about two seconds and the loop then comes
   back to the input queue. An unread pipe fills and a serial bridge behind it loses bytes, so this matters.
2. Checks each line is a real reading (a JSON object with a `device_id`) and skips anything else.
3. Stamps it with the gateway's own `boot` and `seq` and the time it was seen as `observed_at` (see below), appends it to a spool file on disk and syncs it
   before doing anything else.
4. Forwards spooled readings to the API in order, whenever a reading arrives or a second passes with readings
   waiting. When the server has a batch route (`POST /api/v1/telemetry/batch`, up to 100 readings) they go in batches and each reading is judged on its own result. When it answers 404 the gateway sends them one at a time for the rest of the run. A batch refused as a whole is retried one reading at a time, so a bad reading is found and set aside on its own. What happens next depends on the reply:

| Reply | What the gateway does |
|---|---|
| 2xx (a 200 `duplicate` too) | The reading is delivered and leaves the spool |
| 400, 413 or 422 | The API says the reading itself is bad. It moves to `<spool>.rejected` with the status and the time and forwarding carries on. After three in a row the pass stops, the gateway backs off and the rest is kept |
| 409 | The API already has this reading or something newer. The reading leaves the spool and is counted as stale, never as rejected data. More than 100 in a row (after a crash at most 50 can legitimately repeat) stop the pass and the rest is kept for a long wait: the gateway's counter is behind, so check the state folder was not wiped and the clock was not set back, then ask an admin to accept a new counter |
| 401 or 403 | The key was refused. Nothing is rejected, because every reading would be. The spool is kept and the gateway waits 5 minutes, doubling up to an hour |
| 429 | Waits for `Retry-After` (up to an hour, 60 seconds if it is missing) |
| Any other 4xx, 408, 5xx or no reply | Keeps the reading and retries with backoff (1, 2, 4 seconds and so on, capped at one minute). A `Retry-After` longer than that is obeyed. A 404 or 405 says something is wrong with the address or a proxy and nothing about the reading, so nothing is thrown away |
| 3xx | Kept and retried. Redirects are never followed, so a redirect (a 307 from `http://` to `https://` for example) blocks forwarding until the address is fixed. The log says so: check `--api-url` |

A crash, reboot or outage leaves the spool intact. Forwarding resumes where it stopped. The last few readings (at
most 50) can be sent twice after a crash and are never lost. They carry the same pair as before, so the API
answers them as duplicates or stale and does not refuse the post.

### The gateway's pair

The API judges each post against the last `(boot, seq)` it accepted for the key and answers 409 to one that is not
newer. The gateway is the one posting under its key, so the pair is the gateway's own. Readings from several
nodes share it. The nodes' counters would clash. Each reading gets the pair as it enters the spool, so a
resend after a crash is the same post. A reading that already carries `boot` or `seq` from its node keeps them
as `node_boot` and `node_seq` (the API ignores unknown fields) and the gateway's pair replaces them.

`observed_at` is the gateway's time (UTC, ISO 8601 with a Z) when it took the line in, so a reading that comes out of a backlog hours later is dated by when it was seen and not when it was sent. A time the node already put there is kept.

`boot` is kept in `<spool>.boot`. At each start it becomes the larger of the stored value plus one and the Unix
time in seconds (capped at 2147483647, the API's limit), so it still rises if the folder was wiped. The gateway
does not start if the counter cannot be stored. `seq` starts at 0 each boot and a used-up `seq` starts a new boot.
Run one gateway at a time per spool.

### Caps and files

The spool is capped. By default it keeps at most 8 MiB and nothing older than 7 days and drops the oldest
readings first. It prints how many it dropped. `--spool-max-mb` and `--spool-max-age-hours` change the caps.
The age cap trusts the wall clock only so far: a forward jump of more than an hour is ignored until it has held
for a minute on the monotonic clock, so a clock being set by the network does not drop the spool. A Raspberry Pi
with no real-time clock should have its clock set before the gateway starts (in a systemd unit, after
`time-sync.target`), because readings stamped before that carry a wrong time.

The rejected file rotates to `<spool>.rejected.old` at 4 MiB. The waiting readings are held in memory and the file
is not reread on every pass. A small `<spool>.cursor` file records how far forwarding has got.

Without `--spool` the files live in a private state folder: `STATE_DIRECTORY` (set by systemd), else
`$XDG_STATE_HOME/phaemos`, else `$HOME/.local/state/phaemos`. Never the working directory. The folder is created
with mode 0700 and the gateway refuses one that is a link, belongs to someone else or can be written by anyone
else. Files are created with mode 0600. Temporary files are created new, so a link planted at their name is
replaced and not followed. A spool or rejected file that is a link is refused.

## Running it

```bash
cargo build --release
export PHAEMOS_DEVICE_KEY=<device key>
cat /dev/ttyUSB0 | ./target/release/phaemos-edge --url https://api.phaemos.com
```

The key is never taken from the command line, because the process list shows it. `--api-key` is refused.
It comes from `PHAEMOS_DEVICE_KEY` or from a file named with `--key-file` (or `PHAEMOS_DEVICE_KEY_FILE`). The address is `--url` or `PHAEMOS_URL`, the same names `phaemosctl` uses. The old names (`--api-url`, `--api-key-file`, `PHAEMOS_API_KEY` and `PHAEMOS_API_KEY_FILE`) still work and an old variable prints a one-line notice. The
file must be readable by its owner only (`chmod 600`) and owned by the user running the gateway. The gateway
refuses to start otherwise. It opens the file once and checks the open file, so it cannot be swapped between the
check and the read. The key is never printed or written to a log. An environment variable can still be read by the
same user and by root, so on a shared machine prefer the file under a service account.

The API address must be `https://`. An `http://` address is refused unless `--allow-insecure-http` is passed,
which is for bench testing only and prints a warning.

The HTTP client is `ureq` 3 with its default features. It checks the server's certificate with rustls against the
Mozilla root list built into the binary. It does not use the operating system's trust store, so a private
certificate authority is not trusted. The list only changes when the gateway is rebuilt. Nothing in the code
turns certificate checking off. Redirects are not followed, so the key is not sent to another address. A
request gives up after 10 seconds.

No proxy is used. `ureq` reads `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` from the environment by default (a test
shows it). A gateway started under a service manager or a shell profile would then send the key and the
readings through a host nobody chose for it. The gateway turns that off. A site that needs a proxy should ask for
a flag.

## The address

`--url` (or `PHAEMOS_URL`) is the base address only, for example `https://api.example.org`. Trailing slashes are stripped, because the server answers 404 for a path with a trailing slash and never redirects it. A full ingest address such as `https://api.example.org/api/v1/telemetry/` is refused at start with a plain message. A 404 on a post is a wrong address: nothing is rejected, the readings stay in the spool, the fault is reported once and the gateway waits as it does for a refused key (5 minutes, doubling to an hour). It ends with exit code 6 if readings are left.

## Exit codes and the closing line

When input ends the gateway prints one line on standard error with the counts (forwarded, already known to the API, set aside as bad, dropped over a cap, left in the spool and how many of those forwarded went in as backlog). It never ends quietly with readings left behind. The exit codes use the same meanings as `phaemosctl` where they apply:

| Code | Meaning |
|---|---|
| 0 | Nothing is left in the spool |
| 1 | A failure: the spool or the counter could not be used |
| 2 | A usage error |
| 3 | The server refused the key and readings are left |
| 6 | The server refused the readings or the counter (409 or bad readings) and readings are left |
| 7 | The server rate limited the gateway and readings are left |
| 8 | The server or the network failed and readings are left |

## The batch route and backlog

`POST /api/v1/telemetry/batch` takes `{"readings": [...]}` (up to 100, oldest first) and answers `{"results": [{"index", "status", "outcome", "id", "code", "detail", "backlog"}], "stored", "duplicate", "refused"}`. Each `status` is what a single post of that reading would have answered and the gateway judges each reading on its own:

- 201 is stored. If `backlog` is true the reading was stored at its own time and never judged as live. The closing line counts these.
- 200 is a duplicate (the exact pair last accepted). It counts as delivered.
- 409 is stale (the API already has this reading or something newer). It leaves the spool and is counted apart, never as bad data.
- 422 is a bad reading. It moves to the rejected file with the API's `code` (for example `invalid_reading`) and the pass carries on.
- Anything else for one reading (a 5xx or an odd status) is not judged in the batch: that reading and the ones behind it stay queued and the next send of the front reading is a single post.

A batch refused as a whole as bad or stale is retried one reading at a time. A batch 429 (`device_rate_limited`) stores nothing, so the gateway waits the `Retry-After` and sends the same batch again. The allowance is 1,200 readings a minute for one device, so after each batch the gateway waits long enough that a drain stays inside it (one reading every 50 ms, at most 6 s after one batch). A server with no batch route answers 404 and the gateway then sends one at a time for the rest of the run.

The rejected file has a line for each reading: the time, the status, the API's code (`-` when it sent none), the time the reading was spooled and the reading itself, separated by tabs.

### observed_at and the seven day limit

The API honours `observed_at` up to seven days back and refuses an older one (`422 observed_at_too_old`, nothing stored). The gateway stamps `observed_at` when it takes a line in. A reading older than 6 days 23 hours is therefore dropped and counted ("dropped over a cap" in the closing line) even if `--spool-max-age-hours` is longer. We do not send it without `observed_at`, because a week-old reading stamped as arriving now would sit in the wrong place in the history and could be judged as live. A reading that slips past the line anyway is refused with its code and lands in the rejected file, so it is not lost silently.

## What has and has not been tested

`cargo build` and `cargo test` run clean (see the tests in each module). The HTTP client has tests against a local
listener on 127.0.0.1 in plain HTTP: the key header and body, the status and `Retry-After`, a 4xx as a reply, a
redirect not followed and no proxy used. A certificate cannot be trusted without a fixture, so certificate
checking itself is not covered by an automated test. It has been tried by hand against a wrong name, an expired
certificate, a certificate that is not yet valid and an untrusted issuer. Each was refused before any key was
sent. No gateway has run against a real API or on real hardware.

## Why Rust

The gateway runs unattended for months on small hardware. Rust gives a single 3 MB binary with no runtime, cross-compiles to ARM for a Raspberry Pi and rules out whole classes of crash. See ADR 020 in [docs/decisions.md](https://github.com/phaemos/phaemos/blob/main/docs/decisions.md).

## Development

```bash
cargo test
cargo clippy --all-targets -- -D warnings
```

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
