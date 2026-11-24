# Client

Tools for talking to a PHAEMOS server from outside the dashboard: a Python SDK with a telemetry simulator and `phaemosctl`, a Go command-line tool for operators and integrators.

> [!NOTE]
> This folder is published to [phaemos/client](https://github.com/phaemos/client) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

| Folder | Language | What it is |
|---|---|---|
| [`python/`](python/) | Python | `phaemos-client` SDK and `phaemos-sim`, a simulator for all four node types with injectable faults |
| [`go/`](go/) | Go | `phaemosctl`: devices, readings, alerts, maintenance windows, tickets, health and the anomaly model, plus the device commands `dev send` and `dev load` |

## Python SDK and simulator

```bash
cd python
pip install -e .
phaemos-sim --node esp32 --count 5 --dry-run
export PHAEMOS_DEVICE_KEY=<device key>
phaemos-sim --node esp32 --fault bearing --count 60 --interval 1 --url https://api.example.org
```

The simulator produces realistic readings for the ESP32, STM32, Arduino Nano and Pico 2W nodes. A fault (`bearing`, `overheat`, `leak` or `gas`) ramps from nothing to full severity over the run, which is how to watch the anomaly score climb and alerts fire without any hardware.

```python
from phaemos_client import PhaemosClient

with PhaemosClient("https://api.example.org", api_key="<device key>") as client:
    stored = client.send_reading({"device_id": "node-1", "temperature": 24.3})
    print(stored["anomaly_score"], stored["is_anomaly"])

with PhaemosClient("https://api.example.org", token="pht_...") as client:   # an API token, for reads
    print(client.health_summary())
```

The library has the same reads as `phaemosctl` (devices, alerts, tickets, windows, health, model, readings, export and tokens), a pager, one `ApiError` with `status`, `code` and `retry_after` and the same retry rules. It is a real package: `py.typed` is included and it builds as a wheel. See [`python/README.md`](python/README.md). It has two fixes from before: `create_device` now sends the field the API reads (`type`) and needs an admin token and `login` is gone because nothing used the token it returned. The simulator ends with one line and the same exit codes as `phaemosctl`, waits out a 429 and has `--version`.

### Keys and plain HTTP

Both clients check the server's certificate, never follow a redirect and never print the key. The key is not in a
help text or in the message for a mistyped option (the simulator names the unrecognised option and not its value).

- Give the device key in `PHAEMOS_DEVICE_KEY` (`PHAEMOS_API_KEY` is the old name and prints a notice). A key flag (`--key` and `--api-key` in the simulator) still works but a key on the command line shows in the
  process list.
- The API address must be `https://`. Plain `http://` is accepted for `localhost` and literal loopback addresses
  (`127.0.0.1`, `::1`) only. A name that merely ends in `.localhost` is not resolved here, so it counts as remote.
  Any other host needs `--allow-insecure-http` (`-allow-insecure-http` in `phaemosctl`). That is for bench
  testing only, because the key and the readings then cross the network unencrypted. The tools print a warning
  when you use it.
- Time-outs and size caps. The Go client times a request out after 10 seconds. The Python client allows 10 seconds
  per socket operation and 30 seconds in all for a reply (checked as each piece arrives, so it can overrun by one
  operation). Both read at most 1 MiB of a reply and stop there. Python reads the reply as a stream, so an endless
  body ends at the cap.
- Server text shown to you is cut and cleaned. `phaemosctl` cuts it at 200 characters and replaces anything that is
  not printable. The simulator prints server values with `repr`, so terminal escape codes appear as text.

### Replay protection

The server refuses a post whose `(boot, seq)` is not newer than the last it accepted for the key (409). A
machine that has sent the pair must always send it. The Python client (when it has a key), `phaemos-sim` and
`phaemosctl send` and `load` add `boot`, `seq` and `up` to every reading. A reading that already holds a `boot` or
`seq` is sent as it is.

- `boot` is kept in a file named `boot-<first 16 hex digits of a hash of the key>` in `$PHAEMOS_STATE_DIR`, else
  `$XDG_STATE_HOME/phaemos`, else `~/.local/state/phaemos`. The folder is mode 0700 and the file 0600. The key
  is not in the name. A folder others can write to is refused with a warning.
- Each run is one boot: `boot` becomes the larger of the stored value plus one and the Unix time in seconds
  (capped at 2147483647), so it still rises if the file was wiped. `seq` starts at 0 in each run. `up` is the
  seconds since the run started.
- Each run counts as a restart on the machine. Three runs in ten minutes raise a restart alert. Run one program
  at a time per key: two started in the same second can get the same boot.
- A 409 is shown as a plain message (a `ReplayRefused` error in Python, `ErrCounterRefused` in Go). If the state
  folder was wiped an admin can accept a new counter for the machine. A 200 with `"status": "duplicate"` means
  the post was delivered earlier (`is_duplicate` in Python, `IsDuplicate` in Go).
- `phaemosctl load` posts concurrently, so posts can arrive out of order and the server answers some with 409. Use
  `-concurrency 1` for a clean count.

## phaemosctl

`phaemosctl` is the tool for a person at a terminal or a script. It signs in with an API token (never a password) and reads devices, readings, alerts, tickets and health. With a token that may operate it resolves alerts and with one that may administer it starts maintenance windows and accepts a new counter for a device. The two device commands, `dev send` and `dev load`, use a device key and sit apart under `dev`.

### Installing

There is no published binary yet. We build it from this folder with Go 1.24 or later and only the standard library:

```bash
cd go
go build -ldflags "-X github.com/phaemos/client/go/internal/cli.Version=1.0.0" -o phaemosctl ./cmd/phaemosctl
sudo install phaemosctl /usr/local/bin/
phaemosctl completion bash > /etc/bash_completion.d/phaemosctl   # or zsh or fish, see below
phaemosctl --version
```

What exists today: the source, the tests (run by CI) and a build that needs only the Go toolchain. The Python client builds as a wheel (`pip wheel .` in `python/`) with `py.typed`. The edge gateway builds with `cargo build --release`.

What a release must publish and does not yet:

- `phaemosctl` and `phaemos-edge` built for Linux (amd64 and arm64), macOS (arm64 and amd64) and Windows (amd64), stamped with the release version (`-ldflags` above and the crate version), with a checksum file that is signed, attached to the tagged release by `.github/workflows/release.yml`. That workflow only checks the changelog heading today.
- `phaemos-client` on PyPI from a tagged release, built with trusted publishing so no token is kept in the repository.
- A tag on the read-only mirror in the form `go/v1.0.0` for the Go module, once it has a public package (see below), so that `go install` resolves a real version and not a pseudo-version.
- Crates are not published: `phaemos-edge` is a program and is shipped as a binary.

The prompt for a token that does not echo works on Linux and macOS (it uses `stty`). On Windows pass the token on standard input (`type token.txt | phaemosctl auth login`).

### Is the Go library importable?

Not yet and we say so on purpose. The typed models, the pager, the retry rules and the one error type live under `go/internal/api`, which Go forbids anyone else to import. Making them public is a promise about their shape and four things about the API are still moving: the token routes and their paths, the error `code`, the one paging contract and the batch ingest route. The mirror also receives commits without tags, so a version could not be pinned. When those have settled and the first tagged release exists, the move is small: rename `internal/api` to a public package (for example `go/phaemos`), keep the tests, tag the mirror `go/v0.1.0` and say in the package comment that v0 may still change. Until then the Python client is the supported library.

### Five-minute start

1. A signed-in person makes a token on the profile page of the dashboard. They choose a name, a scope and a life (1 to 365 days, 90 by default) and prove who they are with their password (and a code when two-step is on). The token starts with `pht_` and is shown once. This tool can never make a token, because the API only lets a signed-in session do that.
2. Point the tool at the server and sign in:

   ```bash
   phaemosctl config set url https://api.example.org
   phaemosctl auth login          # paste the token at the prompt, it is not shown
   phaemosctl auth status         # who you are, the scope, the expiry
   ```

3. Look around:

   ```bash
   phaemosctl health
   phaemosctl devices list
   phaemosctl alerts list --open
   phaemosctl readings tail press-01
   ```

Use the smallest scope that does the job. `read` is enough for every read. `alerts resolve` needs `operate`. `windows start`, `windows end` and `devices accept-counter` need `admin`. If something is wrong, `phaemosctl doctor` checks the profile end to end.

### Commands

Every command has `phaemosctl help <command>` and `phaemosctl <command> -h`, which print the same text with examples.

| Command | What it does |
|---|---|
| `status` | The server's status and who you are when a token is set |
| `doctor` | Check the profile end to end: address, TLS, clock against the server, token and scope, device key |
| `health` | The fleet summary: devices, link states, open alerts and tickets, health score |
| `devices list` | The devices you may read, with state, last seen, link state, open alerts, model and replay state (`machines` still works) |
| `devices show <device>` | One device in full, by id or name |
| `devices accept-counter <device>` | Accept a new counter for a device whose flash was wiped (admin scope, asks first) |
| `readings latest <device>` | The newest reading (or `--count` of them) |
| `readings tail <device>` | Follow new readings by polling until you press Ctrl+C |
| `readings export <device>` | Stream a CSV export to a file (`--from`, `--to`, `--out`, `--force`) |
| `alerts list` | Alerts, with `--open`, `--severity`, `--category` and `--device` |
| `alerts show <id>` | One alert in full |
| `alerts resolve <id>` | Resolve an alert after asking you to confirm (operate scope, `--yes` skips the question) |
| `windows list` | Maintenance windows |
| `windows start <device> --for 2h` | Silence a device's alerts for a while (admin scope, asks first) |
| `windows end <id>` | End a window now (admin scope) |
| `tickets list` | Tickets, with `--status`, `--priority`, `--alert` and `--machine` |
| `tickets show <id or number>` | One ticket, by id or number (`PHM-0012`) |
| `model status` | The anomaly model's state, schedule and last retrain |
| `tokens list` | Your API tokens, with scope, expiry and last use |
| `tokens revoke-current` | Revoke the token in use and forget it |
| `auth login`, `auth status`, `auth logout` | Store, check and remove a token |
| `config set`, `config show` | Change and show the settings |
| `dev send`, `dev load` | Post a reading or measure the ingest answer time, with a device key (`send` and `load` still work) |
| `version`, `--version` | The tool's version (add `--server` to ask the server) |
| `completion bash`, `zsh` or `fish` | A completion script |

There is no command to rotate a device's key, to make a token or to revoke another token. All three need a signed-in person's fresh proof (their password and code) and the API never gives that to a token. A person does them on the dashboard.

```bash
phaemosctl devices list --status offline
phaemosctl devices show press-01 --output json
phaemosctl readings latest press-01 --count 20 --fields temperature,vibration_x
phaemosctl readings export press-01 --from 7d --out press-01.csv
phaemosctl alerts list --open --severity critical
phaemosctl alerts resolve 0b6c1f0e-1111-4222-8333-444455556666 --yes
phaemosctl windows start press-01 --for 2h --label "bearing swap"
phaemosctl devices accept-counter press-01
phaemosctl tickets show PHM-0012
phaemosctl doctor
PHAEMOS_DEVICE_KEY=<device key> phaemosctl dev send --json '{"device_id":"d1","temperature":24.1}'
```

A device is named by its id or by its exact name (case does not matter). The API has no lookup by name, so the tool searches the list for it. Two devices with one name are refused with their ids.

### Configuration

Each setting is taken from a flag first, then the environment, then the config file, then a default.

| Setting | Flag | Environment | File |
|---|---|---|---|
| Profile | `--profile` | `PHAEMOS_PROFILE` | `profile = name` at the top |
| Address | `--url` | `PHAEMOS_URL` | `url` in the profile (default `http://localhost:8000`) |
| Token | none, never | `PHAEMOS_TOKEN` | `token` in the profile |
| Device key | `--key` (shows in the process list) | `PHAEMOS_DEVICE_KEY` (`PHAEMOS_API_KEY` is the old name and prints a notice) | none |
| Output | `--output` | none | none (default `table`) |

The file is `$PHAEMOS_CONFIG`, else `$XDG_CONFIG_HOME/phaemos/config`, else `~/.config/phaemos/config`. It is plain `key = value` lines under `[profile]` headings:

```text
profile = default

[default]
url = https://api.example.org
token = pht_...

[staging]
url = https://staging.example.org
```

The tool makes it with mode 0600 in a folder of mode 0700. It refuses to read a file that other users can read, a file that belongs to someone else and a link. It refuses to write into a folder that other users can write to. `config show` never prints a token: it shows the token's id, name, scope and expiry and where each setting came from. A token comes only from `auth login` (typed at a prompt that does not echo or piped on standard input) or from `PHAEMOS_TOKEN`. It is never a flag, because a flag shows in the process list and the shell history. It is never printed and never in an error: anything shaped like a token is blanked from everything the tool writes.

The API address must be `https://`. Plain `http://` is allowed for `localhost` and loopback addresses and needs `--allow-insecure-http` for any other host, because it would send the token across the network unencrypted.

### The address

`--url`, `PHAEMOS_URL` and the config file take the base address only, for example `https://api.example.org`. Trailing slashes are stripped before any request, because the server answers 404 for a path with a trailing slash and never redirects it. An address with a path (`https://api.example.org/api/v1/telemetry/`) is refused with a plain message, in `config set` too. The Python client and the simulator do the same. A 404 on a post (`dev send`, `dev load`, the simulator) is a wrong address: it is reported once and never retried. `dev load` stops at the first one. `phaemosctl doctor` warns about a stripped slash, fails on a path and says what to change when `/status` answers 404. It reads the server's version and clock from `/status` (`version` and `updated_at`) and falls back to the `Date` header.

### Output

- The default is a table. On a terminal it is aligned columns with colour (green, yellow and red for states). Off a terminal it is tab-separated rows with a header and no colour. `--no-color`, `NO_COLOR` and `TERM=dumb` switch colour off.
- `--output json` is the server's own JSON as one document on one line. `--output jsonl` is one JSON document per line for lists and for `readings tail`. `status` with a token is the one place the tool joins two answers: it prints `{"status": ..., "whoami": ...}`.
- Times in a table are local with the zone (`2026-11-22 12:59:55 BST`). In JSON they are the server's own UTC times.
- Only the result goes to standard output. Progress, warnings and errors go to standard error. `--quiet` drops warnings and progress. `--verbose` shows each request's method, path, status and time and never a header or a body.
- Lists page through everything up to `--limit` (default 1000, at most 100000) and say on standard error when there is more.

### Exit codes

A script can rely on these.

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | A general failure (also an answer nobody expected and a confirmation you declined) |
| 2 | A usage error: an unknown command or option, a missing argument, a refused prompt |
| 3 | Not signed in or the token was refused (unknown, expired or revoked) |
| 4 | Not allowed: the account's role or the token's scope does not permit it |
| 5 | Not found |
| 6 | A conflict (a name that matches two devices) or the server refused the request as invalid |
| 7 | Rate limited, after the retries |
| 8 | The server or the network failed (5xx, no reply, a time-out) |

An error is one line with the server's own message. With `--output json` it is one JSON object on standard error with a stable `code` (`general`, `usage`, `unauthenticated`, `forbidden`, `not_found`, `conflict`, `rate_limited`, `unavailable`), the `exit` code, the HTTP `status` when there was one and the `message`.

### Retries and time-outs

- A read (GET) is retried after a network failure and after 502, 503 and 504, up to four tries in all, waiting 0.5 s then 1 s then 2 s (never more than 8 s).
- A 429 waits for the `Retry-After` the server named (10 s when it named none), up to three times. A wait longer than 60 s is not waited out: the command ends with exit code 7. Any request may wait on a 429, because the limiter answers before anything is done.
- A write is never retried after a network failure or a 5xx, because the server may have done it. The one exception is `alerts resolve`, which is safe to repeat: resolving an alert that is already resolved leaves it resolved. `dev send` and `dev load` are never retried.
- A certificate failure is never retried.
- `--timeout` is the total time for the command: 60 s by default, 10 minutes for an export and none for `readings tail`. `--timeout 0` removes the limit.

### Following readings

`readings tail` polls every `--interval` (5 s by default and never under 1 s), shows each new reading once and oldest first and ends cleanly on Ctrl+C. A failed poll waits longer each time (up to 60 s) and ten failures in a row end the command with exit code 8. It polls and does not use the live socket, because an API token may not use the socket: the socket takes a signed-in session only. The readings route allows 600 reads a minute for each token, so the default interval uses a fiftieth of that.

### Scripting

A cron job that fails loudly when a machine is offline. The exit code of the pipeline is the exit code of the last command, so test the link state and let `set -e` do the rest:

```bash
#!/bin/sh
set -eu
export PHAEMOS_TOKEN="$(cat /etc/phaemos/token)"      # a read token, mode 0600
state="$(phaemosctl devices show press-01 --output json | jq -r .link_state)"
if [ "$state" != "online" ]; then
  echo "press-01 is $state" >&2
  exit 1
fi
```

A cron job gets its own mail when it exits non-zero, so a failure of the tool itself (exit 3 for a dead token, exit 8 for an unreachable server) is loud too. Do not hide it with `|| true`.

An export to a file, refusing to overwrite yesterday's:

```bash
phaemosctl readings export press-01 --from 24h --out "press-01-$(date +%F).csv"
```

Open critical alerts as a count:

```bash
phaemosctl alerts list --open --severity critical --output json | jq length
```

Rules for scripts:

- Give the token in `PHAEMOS_TOKEN` or a config file in a private folder. Make one token for each script, name it after the script and give it the `read` scope unless it must resolve alerts.
- The rate limit is counted for each token on each route and every token of one account shares 600 calls a minute. A 429 carries `Retry-After` and the tool honours it. More tokens do not add up to more calls.
- A token has a life (90 days by default). `auth status` warns when it has fewer than 14 days left and every command warns once on standard error when the stored token is that close. Make the next token before then.
- A password change, a change of two-step sign-in, "sign out other sessions" and an admin clearing the account's sessions or deactivating it each **revoke every token of that account**. After one of those, every script of that account gets exit code 3. The owner must make new tokens on the profile page and sign each script in again (`auth login` or a new `PHAEMOS_TOKEN`).

### What a token cannot do

A token can never do the following, whatever its scope. The API answers 403 with "A signed-in session is needed for this". The tool does not offer these commands.

- Make, list for others or revoke a token. Making one needs a fresh proof (password and code), so an operator makes tokens on the profile page.
- Anything that needs fresh proof: rotating a machine's key, inviting an admin, adding or changing a webhook, uploading firmware and the admin controls over users.
- Anything about the account itself: password, two-step, email, phone, sessions and provider links.
- The live socket.

A token with too low a scope for a command is refused with 403 and the tool says which scope the command needs and which the token has. The audit log, its export and the webhook list will need the `admin` scope and are not in the tool yet.

### What the API does not offer

The server now has the filters the tool first had to apply itself (`name` on devices, `severity` and `kind` on alerts, `device_id` and `ticket_number` on tickets), a route that reads one alert and keyset paging. What is still missing:

- There is no acknowledge step for alerts, only resolve, so there is no `alerts ack`.
- Readings send no total, on purpose, so a tool cannot show how many there are.
- `readings export` is one streamed request (the server reads and sends it in batches), so it needs no paging and the 31 day limit applies.

### Paging

Every list takes `limit` and `offset` and sends `X-Total-Count`. Readings send no total and, like alerts, send `X-Next-Before` on a full page. The pager reads that cursor and sends it back as `before` (keyset, which is read straight off an index however far back). It uses offset where the server sends no cursor. `readings tail` walks a burst of new readings the same way. If a route ignores paging the pager stops with an error and never loops.

### Idempotency and deprecations

`windows start` sends an `Idempotency-Key` (a random value made for each run), so a retry after a time-out cannot make two windows. With a key the create is safe to repeat, so the tool retries it. A 409 `idempotency_in_progress` ("the first request with this key is still being handled") and a 422 `idempotency_key_reused` are reported plainly with exit code 6. With `--verbose` the tool prints one line when an answer carries `Deprecation` or `Sunset` headers ("notice: POST /x is deprecated and will be removed after DATE: update phaemosctl"). Resolving an alert is a `POST`. The `PATCH` form still works on the server as a deprecated alias.

### Proved live and not

Against the running local server (version `unreleased`) with no sign-in: `status`, `doctor` (no token and a made-up token), the 401 error shape through the tool (`api_code` `token_invalid`, exit code 3) and the 404 error shape (`{"code": "not_found", "detail", "request_id"}`). Everything that needs a signed-in token (the reads, `alerts resolve`, `windows`, `tokens`, keyset paging and the filters) runs only against the fake server in the tests, apart from the reads checked by hand. The live server still answered a path with a trailing slash with a 307 redirect when this was run, where the reference says it answers 404: the tool strips trailing slashes either way.

## Testing

```bash
cd python && python3 -m pytest      # needs httpx and pytest: pip install -e '.[dev]'
cd go && gofmt -l . && go vet ./... && go test -count=1 ./...
```

The Python tests use `pytest` and do not run under `python3 -m unittest`. Neither suite needs the network. The Go tests hold golden files for each command's table and JSON in `go/internal/cli/testdata`. After a change to an output, run `go test ./internal/cli -update`, read the diff and commit it.

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
