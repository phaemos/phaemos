# Changelog

All notable changes to PHAEMOS are recorded in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed

- Routine tidy-up: the parts inventory is one list, `hardware/inventory/README.md`, with the parts in stock and the parts still to source grouped by type. It replaces `owned.md` and `needed.md`. The wiring guide and the Discord bot's hardware cards link to it.

## [2.6.0] - 2026-11-25

Adds production deployment files plus email and text alerts through Resend and Brevo, with limits on how often an alert repeats.

### Added

- The PHAEMOS wordmark as vector lettering redrawn from the brand artwork (`assets/brand/phaemos-wordmark-light.svg` and `-dark.svg`, `components/ui/Wordmark.tsx`), in the site header and footer, the dashboard, the sign-in pages, the 404 page, the documentation header and the share images.
- A share image for every public page with its own title, drawn at build time (`lib/ogImage.tsx`), plus `llms.txt`, Twitter card fields, structured data for what the pages show (organisation, source code, FAQ, breadcrumbs) and breadcrumbs on blog posts and release notes.
- The home page says who PHAEMOS is for, the problem and what it does, with a drawing of how a score becomes an alert and five answers from the FAQ.
- Cookie choices: Accept all, Reject non-essential and Customise, the same size and weight. A thank-you page after a contact message the API accepted. Google Analytics events with fixed words only.
- A first-run guide on the overview for a fleet with no machines.
- The production build check refuses a placeholder anywhere in the site's source, not only the legal pages.
- CI and release automation. `ci.yml` has jobs for the firmware (`make firmware-check` and the MicroPython node's tests), the infra scripts (shellcheck and the deploy guard tests), the backend extras (the lock file, a first-install migration run twice, the OpenAPI document and the route class table) and one final job, `CI passed`, that the repository can require. None of it has run on GitHub yet: it needs the repository settings first. `audit.yml` audits the Python, Node, Rust and Go dependencies on every change and weekly. `release.yml` builds `phaemosctl` for Linux, macOS and Windows, the edge gateway for Linux and the Python client from a signed `vX.Y.Z` tag, writes `SHA256SUMS`, attaches build provenance and creates a draft release. Every action is pinned to a full commit (`infra/scripts/check-action-pins.sh`). See `.github/workflows/README.md` and `docs/releases.md`.
- `POST /telemetry/batch`: up to 100 readings in one request with a result for each in order (`status` as a single post would answer, `outcome`, `id`, `code`, `detail`). The replay rule, the physical ranges, the fault-claim rule and the hashed key apply to every item under one lock. It has its own allowance in readings (1,200 a minute for a device, 6,000 for the site) and takes bodies up to 600,000 bytes.
- `observed_at` on a reading, for a gateway that spools: honoured up to 7 days in the past and never in the future, it sets `recorded_at` and so the ordering. A reading older than a live one is a backlog reading: stored and charted at its own time, never scored, never judged by the rules, the anomaly window, the liveness sweep or the notifications. This fixes a drained backlog being stamped with the moment it arrived and judged as live. `device_id` in the body is optional and ignored.
- Webhooks: a `json` format with a versioned event body (`alert.raised`, `alert.resolved`, `webhook.test`), a per-webhook secret shown once and stored encrypted, `X-Phaemos-Signature` with a time and a five minute tolerance, three tries with back-off, `last_delivery_at`, `last_status`, `last_error` and `consecutive_failures`, the chat template checked when it is saved and `POST /webhooks/{id}/test` reporting the status and the time taken (a failure answers 502). Migration 036.
- `GET /alerts/{alert_id}`, `GET /alert-rules/{id}`, `GET /webhooks/{id}` and `GET /maintenance-windows/{id}`. Filters as query parameters: `GET /alerts?device_id=&severity=&kind=&from=&to=`, `GET /tickets?device_id=&ticket_number=`, `GET /devices?name=`, rules and windows by machine and time.
- Keyset paging with `before` and `X-Next-Before` on `GET /alerts` and `GET /telemetry/{device_id}`, with indexes (migration 037). On 2 million readings a page 90,000 rows deep read in 465 ms by offset and in 0.5 ms by keyset.
- `Idempotency-Key` on the creates of machines, tickets, alert rules, webhooks and maintenance windows, kept 24 hours per account and route.
- `GET /alert-metrics` carries `daily_limits` for every signed-in role: for email and text the limit, today's count, whether it is reached and when it resets.
- One error shape for every answer: `{"code", "detail", "request_id"}`, with `errors` for validation. See `docs/api-conventions.md`. Every answer carries `X-Request-ID`, a 429 always has `Retry-After` and every route has a default limit.
- Service accounts (migration 038), `DELETE /tokens/current`, `/livez`, `/readyz`, `/fleet/summary`, `make openapi` and `docs/api-conventions.md` with `docs/api-stability.md`.
- Account administration moved out of `/auth` to `/users`, `/invitations` and `/tokens`. The old paths are deprecated aliases until 20 February 2027.
- API tokens for scripts and the command line tool (migration 035). `POST /auth/tokens` (session and fresh proof), `GET /auth/tokens`, `DELETE /auth/tokens/{id}` and `GET /auth/whoami`. A token is `pht_<id>_<secret>`, shown once and kept as a keyed hash, with a scope of `read`, `operate` or `admin`, an expiry and a last-used time. It works on every route a session does except the account's own security, token management, every route that asks for a fresh proof and the live socket, which are refused by construction. The role is read on every call. A bad token costs one hash and answers one 401. Limits count per token with a ceiling for the whole account, audit rows name the token and a test fails for any route that is not in one stated class.
- Alert texts go only to a phone number confirmed by a six digit code sent to that number (migration 034). `POST /auth/me/phone/send-code` and `POST /auth/me/phone/confirm` do it, with limits for each account and each number, a 10 minute expiry, five wrong tries and the code stored as a keyed hash. A changed number starts unconfirmed. `GET /auth/me` returns `phone_confirmed`. Existing numbers need confirming once.
- Device keys are stored as a keyed hash (derived through `services/keys.py`, so `SECRET_KEY_PREVIOUS` works and a machine is re-hashed under the new key on its next post after a rotation) and can never be read back (migration 031). A machine is found by the first 8 characters of its key and the hash is compared in constant time, with the same cost and answer for an unknown and a wrong key. Existing keys are hashed by the application when it starts or when that machine next posts, so nothing is re-issued. A key is returned only by `POST /devices` and `POST /devices/{id}/rotate-key`. `POST /demo/start` returns one only when it makes the demo machine.
- Replay protection. A node that sends `boot` and `seq` is refused (`409`) when its pair is not newer than the last accepted, the exact last pair is answered `200` with `{"status": "duplicate"}` and stored once and a machine that has sent the pair must always send it. The device read carries `replay_protected`, `last_boot`, `last_seq`, `replay_refused` and `replay_status`. `POST /devices/{id}/accept-counter` (admin, audited) takes a new counter for a hub whose flash was wiped.
- A fault claim from a node stops its sensor only while an open sensor fault alert backs it (or an admin marked the sensor as not fitted). The firmware's own `not_fitted` list and a `warming_up` claim are display only. `quality.not_applied` names the claims that stopped nothing.
- Every sensor field has a physical range. A value outside it is dropped, noted in `quality.dropped_values` and the sensor is treated as `out_of_range` by the sensor fault alerts. `node_type` is lower-cased and limited to `a-z 0-9 _ -` (20 at most).
- A stuck sensor is noticed on the server. A continuous value that has not moved for longer than its table period (`services/stuck_sensors.py`, with the reason for each) raises the sensor fault alert as `stuck` and clears when it moves. A column that has always been flat, a zero where zero is rest and a silent stretch never count. A stuck value is flagged, not hidden: the rules and the model still see it and the row is left out of training. `health.server_faults` shows what the server found.
- A rule alert's count, peak and first time cover the qualifying period. `rule_states` carries `hold_count` and `hold_peak` and the alert has `first_seen_at` (when the condition first held), so a reading that reached 39.1 before the raise shows as the peak.
- A pair at or past the ceiling (`boot` over 2,100,000,000 or `seq` over 4,000,000,000) is refused with `422`, so one post with the largest values can no longer lock a machine out. A big jump in `boot` (over 1,000) or in `seq` within a boot (over a million) is accepted and shown as `replay_warning`, which says to rotate the key. `replay_recovery` is the text for the accept-counter action.
- A model alert carries `evidence` (the counts and median of its window and, when one sensor carried the score, the sensor, its value and its usual range) and its message names that sensor. The nightly model retrain is registered on the retention scheduler. The daily retention job also deletes invitations expired for over 30 days.
- A machine's share of the daily alert caps. One machine can use a quarter of each cap (never under 10 messages) and a fifth is kept for critical alerts, so one noisy or hostile machine cannot spend the whole allowance. `ALERT_MACHINE_SHARE` and `ALERT_CRITICAL_RESERVE` set them.

- Rule alerts are stateful. A threshold rule keeps one alert for as long as its condition lasts, with `occurrences`, `last_value`, `peak_value`, `last_seen_at` and `still_occurring` and no longer writes a row for every breaching reading. A rule has `for_seconds` (how long the condition must hold before it is raised, 30 for a number and 0 for an on-or-off reading) and `clear_margin` (how far back inside the limit before it can resolve) and the alert resolves by itself after the margin and a hold of at least 60 seconds. People are told on the raise, on a rise to critical and as an hourly reminder. Migration 029 collapses existing duplicate open rule alerts into one per machine and rule (the oldest is kept with the count, the newest value and the peak) and adds the index that allows one open alert per machine and rule.
- The device read carries the anomaly model's state (`model`). The model's alert is decided by the shared decision module and keeps its ticket, lock and index.

- `provider_signin_recent` and `has_password` on `GET /auth/me`, `disabled_reason` on webhooks and migrations 016 to 019. `docs/api-reference.md` lists the exact bodies and messages for sign-out, refresh, deletion, email change and two-step.
- Machine replies carry `owner_name` and ticket replies carry `assigned_to_name` and `created_by_name`, so any role can see who without listing users. `GET /tickets/assignees` lists the admins and technicians a ticket can go to, with id and name only.
- `GET /devices`, `GET /alerts` and `GET /tickets` send an `X-Total-Count` header, counted with the same access filter and exposed through CORS. `GET /alerts` takes `limit` (default 100, at most 500) and `offset`. `GET /tickets` takes `priority` and `alert_id` filters.
- `PATCH /tickets/{id}` clears the assignee on an explicit null and checks a new assignee exists. `POST /devices` checks the owner exists.
- `GET /auth/providers` says which of Google, GitHub and Microsoft are configured, by name only, so the sign-in page shows only the buttons that work. `GET /auth/me` adds `has_password`.
- Retention for more than readings. The daily job also deletes closed tickets older than 24 months, resolved alerts older than 12 months and audit log entries older than 12 months, set by `RETENTION_CLOSED_TICKETS_DAYS`, `RETENTION_RESOLVED_ALERTS_DAYS` and `RETENTION_AUDIT_DAYS` (0 keeps that data for ever). Open tickets and unresolved alerts are never deleted and a resolved alert that a remaining ticket points at is kept. Each rule writes its result to the audit log.
- Node health on the telemetry post. A node may add `seq`, `boot`, `up`, `ts`, `faults`, `reset_reason`, `rssi`, `heap_free` and `fw` to the same JSON body. All are optional and bounded and a node that sends none works as before. The reading stores `seq`, `device_ts` and a `quality` record. The latest vitals live in a new `device_health` row per device, with the lost-post count that gaps in `seq` add up to. Migration `012_health.sql` adds them.
- A fault stops its sensor. A sensor named in `faults` has every field it produces stored as null. No alert rule fires on those fields and the model does not score the row. The value the node sent is kept in `quality.rejected`. `app/services/sensor_map.py` holds the map from sensor key to fields.
- Silent nodes are noticed. A sweep every 15 seconds sets each device's `link_state` to `online`, `late` (older than 4 expected intervals) or `offline` (older than 12). After 2 minutes offline one monitoring alert opens and resolves itself when the node posts again, with the outage length in its message. A restart loop (three boots in ten minutes) opens one too. A Redis lock keeps two workers from both sweeping and each API start gives every device a full interval of grace. Monitoring alerts email as a warning and never send the critical text message.
- `GET /devices` and `GET /devices/{id}` return `link_state`, `expected_interval_s`, `seconds_since_last_post` and the latest `health`. `GET /health/summary` adds `link_states`. `GET /alerts` takes a `category` filter and every alert carries `category` and `sensor_key`.
- `python -m app.scripts.create_admin` creates the first admin from a terminal, asking for an email and a password without echoing it. `REGISTRATION_OPEN` controls whether anyone may register.
- Summarised telemetry history. `GET /api/v1/telemetry/{device_id}` takes an optional `bucket` in seconds (10 to 86400) and returns one row per time bucket, worked out in SQL. Most readings are averaged. The shaft angle uses a circular mean, each signed axis adds a `_peak` field, the anomaly score and vibration magnitude keep their maximum, the vibration frequency comes from the strongest reading and alarm flags are ORed. Each row adds `reading_count`, the rows in the bucket. A window may span at most 31 days and at most 999 bucket widths. A query over 5 seconds answers 503.
- The live readings chart now shows the whole of its 6h, 24h and 7d ranges as summaries (one minute, five minute and 30 minute) and says in its caption what is drawn. Hovering a point says whether it is an average or a peak and how many readings it comes from.
- Production deployment files (roadmap issue 261). `infra/docker-compose.prod.yml` runs the database, Redis and API only, with `backend/.env` as the single source of settings, health checks, memory limits that fit a 1 GB droplet, log rotation and volumes for the database, the Redis repeat windows and the firmware file. A missing `POSTGRES_*` or `ENVIRONMENT` value stops the start. `infra/nginx/api.phaemos.com.conf` proxies the API with WebSocket upgrade on `/ws/`, a 3 MB body limit and `X-Real-IP`. The `infra/scripts/` folder holds `harden.sh`, `install.sh`, `deploy.sh` and `backup.sh`.
- The API refuses to start with an empty `SECRET_KEY`. Outside development it also refuses one shorter than 32 characters or containing `change`, `placeholder`, `example`, `secret` or `test`, which covers the public example and test keys.
- `restore.sh` loads a backup after a typed confirmation, in one transaction, on the live droplet or a new one. `backup.sh` writes its own log, keeps its files private and cleans up a partial dump.
- `MODEL_PATH` sets where the trained anomaly model is stored. Production keeps it on a Docker volume so a rebuild no longer resets anomaly scoring to zero.
- Outside development the interactive API docs (`/docs`, `/redoc` and `/openapi.json`) are switched off.
- The deployment guide has a section for creating the first admin and registering a machine through the API.
- `backend/.env.example` now lists every setting the API reads, including the Google, GitHub and Microsoft sign-in values and the `POSTGRES_*` values for the production database.
- Email through Resend (roadmap issue 267). Contact messages, invitations and alert emails all send from `FROM_EMAIL` through one function in `email_service.py`. The contact message sets Reply-To to the visitor.
- Critical alert texts go through Brevo's transactional SMS endpoint with a plain HTTP call (roadmap issue 268). The number must be in E.164 form and `BREVO_SMS_SENDER` must be 11 letters or digits at most. A numeric one may have up to 15 digits. A text is capped at 160 plain characters so one alert is one message part. What a part costs depends on the destination country.
- A critical anomaly alert now texts the device owner, as a critical rule does. Anomaly alerts also follow the same repeat window and daily caps.
- `DASHBOARD_URL` sets where invitation links point. `ALERT_EMAIL_DAILY_CAP` (default 50) and `ALERT_SMS_DAILY_CAP` (default 20) limit alert emails and texts across all devices in a UTC day.
- The profile refuses a phone number that is not empty or in E.164 form and shows the format in the error.
- The anomaly model measures itself before it is used. After fitting it replays readings it did not train on through the real alert decision and records the false anomaly alerts per machine per week. It also injects labelled faults (overheat and bearing shapes from the simulator and a stuck value and a current spike) and records which it caught and how soon. A model over one false alert per machine per week or finding fewer than 60 per cent of the faults is refused and the model in service is left untouched, with the reason in words. `GET /ml/status` returns what is in service and the outcome of the latest retrain.
- A per-sensor baseline beside the anomaly forest, per operating state, so a single sensor far outside its machine's usual range raises an alert the forest alone could not. The alert's reason names the sensor ("current is well above this machine's usual range") and its evidence holds the sensor and the value and the range. A clear excursion raises on a shorter window (one minute at the critical score). A stuck value is left to the sensor health check.
- A sequential change detector for a machine's own model: an expected value for each sensor from the machine's other sensors and a daily profile. A two-sided CUSUM runs on what is left. It catches a step or a slow drift in one sensor that a range cannot. The alert's reason says what moved ("temperature is about 4 above what this machine normally shows for this load, over the last 20 minutes") with the expected and observed values and the time. Per-machine detector state lives behind a small store the server can back with the database.
- Model routes. `POST /ml/alerts/{alert_id}/verdict` records whether a model alert was a real fault and only a confirmed fault keeps its readings out of training (`alerts.fault_confirmed`, migration 040). `POST /ml/machines/{device_id}/accept-move` (admin with fresh proof) accepts a larger move of a machine's normal that a retrain refused. `PUT /ml/machines/{device_id}/ambient-source` (admin) lets a machine with no air temperature use another node as its site reference (`devices.ambient_source_id`, migration 041). A retrain raises a monitoring alert for each machine it leaves unmonitored and each move that needs a person. Apply migrations 040 and 041 before a deploy. Simulated data only: 0.67 false alerts per machine-week on a healthy week and a 2 degree step caught within 30 minutes 58 per cent of the time.
- A nightly retrain at 03:30 UTC with the same guard as the manual one, one retrain at a time across workers. `GET /ml/status` shows the schedule.
- The model file is one signed envelope (an HMAC keyed through `services/keys.py` inside the file) and a file that does not verify or lies outside the model folder is refused without ever being unpickled. A file signed under the previous secret key verifies and is signed again at the next save. A file from before signing is refused with a message that says to retrain. Before this change the earlier file was loaded before it was refused. The second independent pass tried eight hostile files and the payload never ran.
- `POST /ml/score` is admin only as the API reference says and applies the machine access rule when `device_id` names a machine.
- A machine with five days of clean readings at a 5 s interval (its test part must hold a day) gets an anomaly model of its own: a full one for the first 24 machines and a light one (baseline and change detector) for every machine after them. A machine with no model of its own uses its node type's model and then the general one. A machine no model scores is shown as not monitored and gets a monitoring alert.
- `make ml-eval` prints the false alerts per machine per week and the injected faults caught for the old rule and the new model side by side on seeded simulated machines (roadmap issue 275). It says plainly that no real machine data has been used.
- Hub firmware (`firmware/esp32/`). The code is split into comms, outputs and sensors modules whose logic builds and is tested on a desktop (`make firmware-check`). PlatformIO builds the hub for both carrier boards with `HAS_` switches for a hub without a sensor. The Wi-Fi name, password, API address, device id and key are no longer in `config.h`. They are typed over the serial console (`firmware/esp32/tools/provision.py`) and kept in flash, so one image fits every hub. The hub posts over TLS and checks the server certificate against pinned roots. Plain HTTP needs the bench flag `ALLOW_PLAIN_HTTP`. **Operator action:** the two root certificates in `firmware/esp32/comms/trust_roots.h` are placeholders and must be pasted in before a release image is built. Nothing has run on a real board yet.
- Hub safety behaviour. The cooling decision is kept across a reset during an over-temperature, reset loops are counted, a board check refuses an image for the wrong carrier board and an unplugged sensor shows a fault and not a normal reading. The panel says why in words. Tested on a desktop only.
- Hub port expander driver. The revised hub image reads seven rail inputs and the push button through an MCP23017 (`HAS_EXPANDER`, built with `pio run -e esp32dev_revb`). A rail reads present only from a fresh reading, silence reads `stale` and a chip that stops answering is retried with a back-off. A 5 second press in the first 30 seconds after power-up clears the stored credentials. 614 host checks pass on a desktop. It is fit for a bench bring-up only. The revised board does not exist yet and the driver has not run on one.
- Satellite firmware (`firmware/arduino_nano/` and `firmware/stm32_blackpill/`). Every line sent to the hub carries a checksum (crc16) and a status code, so a corrupt line is refused and a dead cable is named. The Nano reports a stuck, reset or out-of-range air sensor. The Black Pill keeps window statistics for vibration. Both run in an emulator (`make sim-nano` and `make sim-blackpill`) and the Black Pill also has host tests. These are emulated results and nothing has run on a real board.
- Pico W node (`firmware/pico_w/`). Its settings live in `secrets.py` and not in the source. It posts over HTTPS and checks the certificate against `root_ca.pem` (a placeholder to replace). It has a watchdog, a back-off and a boot counter. It has desktop tests and has not run on a Pico.
- Edge gateway (`edge/`). The gateway reads lines with a size cap, forwards without ever waiting on the network and spools readings to disk with caps (`--spool-max-mb` and `--spool-max-age-hours`). It takes its key from the environment or a mode 600 file and keeps its own `boot` and `seq`. It has not run against a real API. It posts spooled readings in batches of up to 100 through `POST /telemetry/batch`. Its two certificate crates (`rustls-webpki` 0.103.17 and `webpki-roots` 1.0.12) were updated after the dependency audit failed on the old ones.
- The Go and Python clients send `boot`, `seq` and `up` with every reading so they work against a server with replay protection. The API address must be `https://` (plain `http://` only for localhost). The key is kept out of help text and error messages and a reply is capped at 1 MiB. `phaemosctl` has a command layer (`client/go/internal/cli`) with `auth login`, `devices`, `readings`, `alerts`, `tickets`, `windows`, `tokens`, `model status`, `config` and `completion`. It has profiles, `--output table`, `json` or `jsonl` and exit codes 0 to 8. 65 tests and 34 golden outputs pass against simulated servers. It has not been used against a real server and no binary is published yet.
- A sensor fault alert is one monitoring alert for each machine and sensor, with a 60 second debounce. It is marked intermittent after 5 changes in an hour.
- Dashboard and website (`frontend/`). The pages are split into public and signed-in route groups and one deployment can answer on two addresses when `NEXT_PUBLIC_SITE_URL` and `NEXT_PUBLIC_APP_URL` differ. After sign-in a person returns to the page they asked for. The dashboard has a content security policy with a nonce. Terms, privacy, cookies and accessibility pages are written as drafts and a build check (`node scripts/check-legal.mjs`) stops a build with a placeholder left in them. A changelog timeline, a status page and `security.txt` were added. The frontend has 57 test files and the last run on 22 November passed 426 of 426 tests. Sign-in across two real addresses has not been tried on a deployed server.
- Server set-up. The API connects to the database as a limited role (`infra/sql/roles/`, checked with `db-role.sh --check`). `check-nginx.sh` checks the Nginx site and `deploy.sh` deploys a signed release tag. These were rehearsed on a throwaway stack and not on a real server.
- The documentation site takes the dashboard's look (`mkdocs.yml` and `docs/`): the same palette and the Exo 2, Manrope and IBM Plex Mono typefaces bundled with the site. Nothing is loaded from another site. `make docs-check` builds it strictly and runs a browser check. The check ran in Chromium only.
- Community server script (`discord/`). `python3 -m serverkit check`, `plan` and `apply` build the Discord server from one layout file and keep the bot to 17 permissions. The two staff roles are never created or changed by the script. A relay posts releases and announcements and holds a stranger's issue text until a maintainer acts, with at most 10 posts an hour. A Cloudflare Worker answers 14 slash commands without a bot token. `setup_discord.py` is replaced. It is tested against a fake Discord API (732 Python tests and 101 worker tests) and has not met the real Discord.

### Fixed

- The NUL check no longer refuses a reading sent to `POST /api/v1/telemetry`, which cleans a bad string itself and keeps the reading. Every other route keeps the check.
- Development logs hold no full email address. They hold no message body or link unless `LOG_EMAIL_BODIES` is on.
- A failed notification for a rule alert is retried after a minute and not after the next hourly reminder. The alert was marked as told whenever the readings reached it, even when every channel was held by its retry window.
- A failure after a reading is stored (an alert rule that raises) no longer answers 500 or drops the notifications already queued. It is logged once for its kind. The repeat window is a minute when a send is queued and an hour only once the vendor accepted it, so a failed send, including one while the store cannot be reached, is not held for the hour.
- Notifications run on their own pool of 8 threads with a queue of 200, so forty machines alerting at once against a hung endpoint no longer stall ingest or the status check. A full queue drops the oldest non-critical job and counts it. A critical job is never dropped and goes first.
- A post and the liveness sweep take the device row first, so they cannot deadlock. A post is retried once after a deadlock or a lock timeout and its advisory lock has a timeout.
- The model's alert has a kind and is under the unique index, so two posts at once raise one alert and one ticket.
- The daily email and text limits are reserved before a send and given back when it fails, so sends in flight cannot pass them.
- A rule on `anomaly_score` now fires. An alert rule must name a reading a post can carry (`GET /alert-metrics` lists them), a known condition and a known severity.
- The health summary counts link states with the same rule as a machine's own read. A broken model file deleted by hand stops being reported. `add_alert` absorbs only the open-alert refusal, `alerts.resolved` can no longer be NULL and migrations 012, 015, 020 and 021 send nothing and take no lock when the database is up to date.
- A system alert resolved by hand is recorded and not raised again for an hour (and then only if its cause is still there).
- New hub fields: `diag`, `board_mismatch` (with its own monitoring alert) and `not_fitted`, which is kept apart from the admin's list and returned as `not_fitted_by_firmware`. The cap on fault entries follows the sensor key list.

- A slow notification endpoint no longer holds a database connection for every post. The post's session is closed before the response and the notifications and a failed send keeps its window for 60 seconds instead of being retried on every reading.
- Failed sends no longer use up the daily email and text limits. They are charged when the vendor accepts a message and reaching a limit is logged and written to the audit log once a day.
- A model file that cannot be loaded or used no longer turns every post into an error: the reading is stored unscored with the reason, logged once and the no-scored-reading alert says so. The model file is written atomically with the previous one kept, `/status` reports `model` and `deploy.sh` fails on `error`.
- Two posts from one node at once can no longer open the same alert twice or lose a reading: changes are serialised per device and the database refuses a second open alert of a kind (migration 020).
- A device is limited to 60 posts a minute (429 with Retry-After) and the tracked sensor keys per device are bounded.
- `fc28: unplugged` stops only `moisture_level`, so a leak alarm still fires. New `vib_clipping` reading with its own warning (migration 021).
- A fault no longer raises a second alert through the no-scored-reading path, a recovered intermittent sensor no longer says it is not answering, `node_type` over 20 characters no longer answers 500 and a numeric string gets the same range check. An admin can set `expected_interval_s` and the anomaly run window scales with it.
- An alert rule for an unknown machine answers 404. A machine owner is checked with a row lock. Used invitation records older than 3 days are deleted by the retention job.

- The start-up grace no longer brings dead machines back to life. It only holds back bad news while the API is young and never closes an alert or restarts the 24 hour limit.
- The liveness sweep takes a `FOR NO KEY UPDATE` lock on only the devices that can need a change, so posts are never blocked and runs a fixed number of queries.
- A boot counter that jumped while the node was away is one restart dated by the uptime and not three restarts in ten minutes.
- A node type whose own model lacks a column for a reading is scored by the general model instead of going unscored. A model file from before the change still scores what it can. The general model needs at least 50 complete readings and a retrain that has too few refuses clearly and keeps the old model. Retrain once after upgrading.
- A health string or fault key with a NUL or a lone surrogate is dropped and the reading kept, where it used to fail the commit.
- Redis that is slow but not down no longer holds the telemetry request on every window check.
- `deploy.sh` applies the migrations before the new code starts on an existing database. Migration 012 sets a lock timeout and alters the readings table once and the alerts index moved to migration 014 and is built concurrently.
- Retention deletes in batches of 10,000 with a commit per batch and also deletes sign-in sessions a day after they expire.
- The bucketed shaft angle is always below 360 and is null for a bucket whose angles do not agree, which is what a turning shaft gives.
- A machine's owner must be an admin or a technician and the device and telemetry lists refuse out-of-range paging.
- A sensor that drops out no longer raises a machine alarm. The model used to fill a missing feature with 0.0, so a node that lost a sensor produced rows that looked anomalous and three of them opened an "Inspect" ticket. A reading is now scored only when it has every feature its model needs. Otherwise the score is null and the reading counts as neither normal nor anomalous. The three-in-a-row rule uses the last three scored readings from the last minute and training leaves out readings with a missing feature. The general model uses the columns that at least 90 per cent of readings carry, so a mixed fleet still gets one.
- A node that stopped posting stayed `online` for ever. Its `status` now becomes `offline` when the sweep finds it offline and returns to `online` with its next post.
- Discord and webhook calls no longer run inside the telemetry request, where a slow endpoint could hold a node's post past the time it waits for a reply. They are queued like email and SMS and repeat at most once an hour per device, metric and severity.
- `GET /telemetry/{device_id}` now refuses a `limit` over 5000. The CSV export streams in batches, needs `from_ts` and covers at most 31 days. Both telemetry reads and the export are rate limited to 600 requests a minute per address.
- The API refuses a reading that holds NaN or infinity, which would have blanked a whole bucket.
- The live readings chart no longer shows only the latest two hours on its 24h and 7d ranges.
- `useTelemetry` can take a `windowMs` and then works out the start of the window at each request, so the window moves with the clock instead of staying where it was when the page loaded. It also takes a `bucket`.
- The deployment guide no longer tells the owner to run the development stack in production, where it overrode `ENVIRONMENT`, the secret key and the database password. It also ran the migrations with `psql` inside the API container, which does not have it.
- The post-launch checklist is now one ordered list with the exact action and expected result for each line (roadmap issue 272).
- `backend/.env.example` no longer lists two anomaly threshold values that the API never read.
- The refresh cookie check now agrees with the rest of the API about what development is: the exact name, ignoring case and spaces. `backend/.env.example` no longer sets a one day access token lifetime that contradicted the 15 minute default.
- The contact form no longer says "Message sent" when nothing was delivered. A Resend failure answers 503. So does a missing Resend key outside development. Both ask the visitor to email us directly. In development with no key the message is logged.
- An invitation that could not be emailed no longer says it was sent. The response has `email_sent` and still returns the link for the admin.
- Invitation links are built from `DASHBOARD_URL` and not from the API's own address, which was wrong behind a proxy. The dashboard page that opens the link is still to come.
- Invitation emails escape the role and the link.
- Contact names, subjects and messages must not be empty and are capped at 100, 200 and 5000 characters. They lose control characters before sending. The `[Contact]` prefix now counts towards the 200 character subject cap.
- A slow or failing Resend or Brevo call can no longer hold up a device's telemetry. Alert emails and texts go out after the response, with a 5 second timeout on each call. The live dashboard update is queued first.
- Alert emails and texts no longer repeat on every reading while a rule stays breached. The first goes at once and a repeat goes at most once an hour per device, metric and severity. A send that fails frees its window.
- Info alerts no longer send email. Only warning and critical alerts do.
- The API's own INFO log lines now appear in development, so the logged invite link and contact message can be seen. Other environments log warnings only.
- A failed webhook delivery logs only the webhook's name and the status or error type, no longer its address. A failed Discord alert logs the status or the error type and no longer the exception text, which could include the webhook URL.
- Vendor failures log the Resend error code and type. They log the Brevo error code too. They never log the message text. They never log an address or a number either.
- `make test` no longer drops the tables of the development database. It runs against a separate `phaemos_test` database that the target creates on first use. `conftest.py` refuses to run unless the database name ends in `_test`.
- The dashboard maintenance banner no longer says maintenance is in progress for a window that has not started yet.
- The dashboard content security policy now allows the `ws:` or `wss:` origin of the API next to its `http:` or `https:` origin, so the live telemetry socket connects.
- The dashboard content security policy now allows Cloudflare Turnstile and Google Analytics when their `NEXT_PUBLIC_` values are set. Before, the browser blocked both.
- `make dev` installs the dashboard dependencies on a fresh clone instead of failing at `npm run dev`.

### Removed

- The SMTP settings (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` and `SMTP_PASSWORD`) and the code that used them. Email sends through Resend only. The unused `sib-api-v3-sdk` requirement is gone as well.

### Changed

- Typefaces: Exo 2 for the name and page headings, Manrope for reading and the interface and IBM Plex Mono for code and data, on the site, the dashboard and the documentation (self-hosted). They replace Geist and Geist Mono.
- A visitor who has not picked a theme gets the one their system asks for. The site was dark unless the light theme was chosen.
- Vercel Web Analytics loads only with `NEXT_PUBLIC_VERCEL_ANALYTICS=1`. With it and `NEXT_PUBLIC_GA_ID` both unset the site loads no analytics and the privacy and cookie pages say so.
- The privacy notice names Google Workspace as the mailbox host, describes the API log as size-capped with no fixed period and asks for the transfer safeguard to be confirmed. The accessibility and security pages no longer promise reply times beyond the 72 hours for a security report.
- **Removed:** `GET /alerts/{device_id}`. Use `GET /alerts?device_id=`. The old path answers `410 endpoint_removed`.
- `PATCH /alert-rules/{id}` replaces `PUT` (kept as an alias with `Deprecation` and `Sunset` headers). `POST /alerts/{id}/resolve` replaces `PATCH` (kept as an alias). A `null` in a PATCH clears only the fields that may be cleared and is a `422` elsewhere, for devices, tickets, rules, webhooks and maintenance windows. `status` can no longer be written on a device.
- Lists take `limit` and `offset` (`skip` still works), end every order in id and send `X-Total-Count`. Rules, windows and webhooks are paged (50 by default).
- `from` and `to` name the time filters of readings (`from_ts` and `to_ts` still work). Webhook test answers `{ok, status, elapsed_ms}`. Adding a tag answers 201. Firmware routes are limited per device and not per address. A firmware `version` must be dotted numbers. Several 400s became 422 (maintenance windows, ticket assignee, firmware file) and an unknown machine on a new window is a 404.
- Key rotation is for an admin or the machine's owner. A technician who only shares an unowned machine gets `403`.
- CSV exports (`/telemetry/export` and the audit export) put a quote in front of any text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return.
- The no-scored-reading alert skips a machine whose model state is `learning` or `none`, which are unscored by design. `missing_features` is asked for the machine.
- The anomaly model raises far fewer false alerts on simulated healthy machines. A second independent pass said yes as a pilot with a person reading every alert. The latest round (carried state and a site reference) has had no independent pass. Its boundary is measured on healthy validation readings (1 reading in 1,000) and not set by a 5 per cent contamination, so it stops marking 5 per cent of its own training readings as anomalous. An anomaly alert now needs a sustained spell (at least 80 per cent of the scored readings in the last two minutes or 24 intervals at or over the boundary, at least 12 of them) and not three in a row. It resolves only after a calm of 30 minutes and a machine that has just resolved waits 15 minutes before a warning can raise again and 5 before a critical one can. The decision is a pure function in `services/anomaly_decision.py`.
- Retraining reads the last 14 days of each machine, sampled evenly in time in SQL and one machine at a time. It leaves out readings taken in a maintenance window or with a sensor fault or a rejected or dropped value or while a machine alert was open or beside a gap in the posts. It used to take the newest 10,000 rows of the whole table. Columns are scaled by their median and inter-quartile range.
- Scoring one reading took about half a millisecond with the change detector on a loaded developer machine, down from about 15 ms. A worker picks up a model file another worker wrote within 30 seconds.
- The contact form checks with Cloudflare Turnstile whenever a secret is set. With no secret it answers 503 unless `ENVIRONMENT` is exactly `development`, where the check is skipped so the form can be tried locally. A timeout or network error calling Cloudflare gives a 503 instead of a 500. The verify call uses the documented v0 URL and sends the visitor's address.
- The dashboard asks for analytics consent only when `NEXT_PUBLIC_GA_ID` is set. Accepting starts Google Analytics straight away. Cookie settings lets a visitor change their choice. Declining removes its cookies and reloads the page so the tag is gone.
- The cookie banner is readable in light and dark themes and has visible focus and 44 pixel targets. It no longer covers the page. The privacy page now lists the real cookies and storage keys.
- `docs/development.md` explains how to register the first account, promote it to admin and register a device. It also corrects the warning about which `docker compose` command deletes the database volume.
- `docs/VERIFICATION.md` records what a full local walk of the stack proved.
- The backend suite has 1,539 test functions in 60 files. On the final code it passed 1,812 tests with 0 failed and lint clean at the version CI pins (a local run, not yet on GitHub). The generated API document is in the repository (`docs/openapi.json` with 99 paths and `docs/api-routes.md`).
- Migration 011 adds an index on telemetry by device and time (newest first) so history, export and bucketed reads of one machine stay quick as readings grow. It is built without blocking ingest and first removes a half-built copy left by an interrupted run.
- **Breaking changes and operator actions when upgrading from 2.5.0.** This sums up the lines above so none is missed. `ENVIRONMENT` now defaults to production and registration is closed unless `REGISTRATION_OPEN` is true. The API refuses to start with an empty or weak `SECRET_KEY` (under 32 characters outside development) and `TRUSTED_PROXIES` defaults to none. People signed in before the update sign in once more and invitations sent before it must be sent again. Existing phone numbers must be confirmed once or alert texts stop. The SMTP settings are gone because email sends through Resend only. An existing deployment needs one `chown` of the two volumes for the unprivileged API image and one manual retrain after the upgrade. Machines need no new key because existing keys are hashed in place. Run `deploy.sh`, which applies the new migrations before the new code starts. Hub firmware needs the two trust roots pasted in and a one-off provisioning over the serial console.

### Security

- The API fails closed. `ENVIRONMENT` now defaults to production and only the word `development` relaxes anything. The relaxations are one list in `app/config.py` and development only runs against a database on the same machine. `TRUSTED_PROXIES` now defaults to none, so a client can no longer choose its own rate limit identity and the start-up log says which mode is in force. The root no longer names the environment.
- Wrong passwords never lock an account for good. A stranger who knew an address could keep its owner out. Failures now delay the source they came from, then slow browsers that have not signed in to that account before while it is being guessed at from many places. A browser that signed in before and every admin account, is not slowed by strangers and the owner is emailed at most once a day. An unknown address is counted exactly like a known one.
- Sign-in answers and takes the same time for a known address, an unknown one, an account with no password and a deactivated one. A password with a NUL character and any NUL character in a request body or query string, is refused with 422 and no longer answers 500. Email addresses are compared in lower case.
- Invitations are rows in their own table holding only the hash of a random token, so an admin can list and cancel one. Every access token must name a live session outside development. Each kind of token has its own key derived from `SECRET_KEY` (`derive_key` in `app/services/keys.py`) and `SECRET_KEY_PREVIOUS` allows a rotation without signing everyone out. Invitations sent before this change must be sent again.
- Admins can deactivate and reactivate accounts, change roles, clear a lost two-step, email a one-time password reset link to the account's own address, list and cancel invitations and remove an account. Each needs the admin's fresh proof, is audited and cannot be used on yourself or to remove the last active admin.
- Inviting an admin, adding or changing a webhook, uploading firmware and rotating a machine's key now need the actor's fresh password (and a two-step code when on).
- Two-step secrets are encrypted at rest. The API encrypts any left in clear at start and `python -m app.scripts.encrypt_two_step_secrets` does it by hand.
- The cookie routes refuse a page on another origin. Replies carry `nosniff`, the account routes are not cached and uvicorn sends no `Server` header. The demo feed is not served outside development. An unsent email no longer logs its link unless `LOG_EMAIL_BODIES` is set. Ticket status and priority are fixed lists. Passwords on a list of common ones are refused.
- An account may change its email at most 3 times an hour and 5 times a day and the profile route is rate limited. The notice about an email change goes only to an address that was never unconfirmed (an invitation went to it or a provider verified it) or that has been the sign-in address for at least an hour, so the route can no longer be used to make the service mail a stranger.
- Changing the phone number, where critical alert texts go, needs the same proof as changing the email.
- A wrong proof answers 400 on every route that checks one. `/2fa/disable` answered 401, which the dashboard treated as an expired token and retried, counting one wrong code twice. A right proof, a sign-in or a lock that has run out now clears the wrong-guess count. An account with no password can no longer be locked through `/change-password`.
- A refresh token that was swapped less than 10 seconds ago is accepted again and gets the same new token back, so two tabs refreshing together do not end the session. The session row is locked while it is rotated. The refresh cookie lasts the lesser of 7 days and what its session has left. Ending your own session also clears your cookies.
- A provider can be linked to an account that has a password, from a signed-in session after the password (and a two-step code when on), when the provider's verified address equals the account's address.
- `POST /auth/invite/check` says whether an invitation is valid, expired or used without using it.
- The API image runs as an unprivileged user and the production image no longer carries the test and plotting packages (`requirements-dev.txt` holds them). An existing deployment needs one `chown` of the two volumes, in the deployment guide.
- Migrations 013 to 025 are conditional and give up after 5 seconds on a busy table, so a re-run on an up-to-date database takes no lock. Migration 022 had no lock timeout and a sign-in query queued behind it timed out.
- The provider sign-in that proves a provider-only account is its owner is now recorded on the session that made the return, so a stolen token from another session of the same account can no longer use the owner's sign-in to turn on two-step or delete the account.
- A wrong password or two-step code now counts towards the sign-in lock on `/change-password`, `/2fa/confirm` and `/2fa/disable` as it already did at sign-in. An account with two-step on needs its code as well as its password to delete the account or change the email. Two-step codes are no longer read from the query string.
- After an email change every other session of the account is ended and the old address is sent a plain notice. A sign-in session also ends 30 days after it began however often it is refreshed (`SESSION_MAX_DAYS`). `GET /auth/sessions`, `DELETE /auth/sessions/{id}` and `POST /auth/sessions/end-others` let a person see and end their own sessions. The list shows a coarse browser label and times and never an address.
- The refresh cookie is sent only to `/auth/refresh` and `/auth/logout`, as two copies with their own paths. An invitation works once, even after the account it made is deleted.
- A DNS failure at delivery no longer switches a webhook off. A webhook is switched off only for a positive finding on two checks a minute apart. Delivery tries every checked address, IPv4 first. A webhook address with a user name and password is refused.
- Cookies are sent with a request only from the dashboard origin (`CREDENTIALED_ORIGINS`). A failed database statement logs its kind and SQLSTATE only, the database engine hides statement parameters and a refused start-up names the setting and no part of its value.
- A live socket that cannot keep up is closed so it reconnects. Alert-rule, webhook and invitation fields that overflowed their columns are refused with 422. Two-step enrolment installs Pillow with the QR library.
- Signing out now ends the session on the server. Each sign-in is a session the server keeps, a refresh token works once and is swapped for a new one on every use and presenting an old one revokes the session. `POST /auth/logout` needs only the cookie and the access token from that session stops working at once. A password or two-step change still ends every session. The refresh cookie is now scoped to `/api/v1/auth` so sign-out receives it. People signed in before this update sign in once more.
- Deleting an account, changing the email and switching two-step on or off need proof of ownership: the password, a two-step code or for a provider-only account a sign-in through the provider within the last 5 minutes. A typed word no longer counts. A wrong password or code counts towards the sign-in lock. A provider account cannot change its email.
- A provider sign-in finds the account by the provider and its own identifier first and links by email only to an account with no password and no provider. A closed site no longer says whether an address has an account.
- The live readings socket is hardened. The server starts with a message size cap of 8192 bytes, compression off and a concurrency limit, Nginx limits connections per address and the API caps sockets per account (5) and per address (20). A client can no longer make the server read large frames. The `?token=` address form is allowed only in development unless `WS_TOKEN_IN_URL` is set. Query strings are filtered out of uvicorn's own log lines, which still printed the socket address.
- A ticket tied to no machine, such as one whose machine was deleted, is visible to admins, viewers, its creator and its assignee only. A ticket can be given only to an admin or technician who can open it.
- Webhook addresses are checked again before every delivery and delivery connects to the address that passed. A webhook that fails the check is switched off with the reason recorded. This covers addresses saved before the check existed. The image refuses to build on Python older than 3.12.4.
- Every list caps `limit` and rejects negative paging with 422. `GET /alerts/{device_id}` was paged with a total and is now removed (see Changed). Rate limits key an IPv6 client on its /64 and the public status route is limited.
- Every foreign key in the models now has a delete rule that matches the migrations. An alert rule that has fired can be deleted. Migration 013 changes a key only when its rule is wrong and gives up after a 5 second lock wait.
- The data export adds the provider identifier, the lock state and the maintenance windows the person created. It withholds the text of an assigned ticket on a machine the person may not read, names no other person's account id and fails loudly if the log cannot be read.
- Two-step codes can travel in the request body. The invitation read route that put the token in a path is removed. The demo no longer takes over a machine that has an owner. Name, location and label lengths match their columns.
- Deleting an account now asks for the current password. An account that signs in through a provider sends a fresh two-step code when two-step is on and otherwise types the word DELETE. It is refused with 409 while the person owns machines or when they are the last admin. It clears the person from the tickets assigned to them as well as the ones they raised.
- The ticket foreign keys now carry the same delete rules on a database built by the API as migration 001 gave them. Migration 013 fixes any database where they differ. Deleting a user who had a ticket assigned no longer fails.
- The data export is complete: it adds the last sign-in time, the sign-in provider, whether two-step is on, saved permissions, tickets assigned to the person with their descriptions and the person's own audit entries.
- The admin user list no longer returns phone numbers. The per-user permissions route is removed and no reply returns that field, which nothing ever read.
- Webhook addresses must be https (http only in development) and must resolve only to public addresses. Private, loopback, link-local and reserved ranges are refused when a webhook is created or changed and when it is tested.
- The invitation link now carries its token after a `#`, so it does not reach web server or hosting logs.
- Google sign-in no longer asks for offline access. A failed audit write logs only the kind of error.
- The live readings socket takes its token in a first message so it need not appear in a URL. The older query-string form still works and logs one warning per process.
- Telemetry history, the latest reading and the CSV export, the anomaly history and the live readings socket now follow the same machine rule as the machines routes: a technician reads only their own and unowned machines. Admins and viewers are unchanged.
- A machine a technician may not read now answers 404, exactly as a machine that does not exist does, on the machines, telemetry, alert, alert rule and ticket routes. This replaces the 403 that `GET /devices/{id}` gave before. A viewer who tries to change something still gets 403.
- Alert, alert rule, ticket and maintenance window lists, the single alert history, the single ticket read and the health summary totals follow the same rule, so a technician sees only the machines they may read.
- Resolving an alert, creating a ticket and updating a ticket now need an admin or a technician. A technician can change only items on their own or unowned machines. Viewers are read-only, so ticket creation by a viewer is no longer allowed.
- A ticket created with both a machine and an alert must use an alert that belongs to that machine. An unknown alert answers 404.
- In `PATCH /devices/{id}` the owner, tags and firmware version can be changed by admins only. The new owner must exist. An explicit null clears the owner.
- An empty or unknown role is refused everywhere the machine rule applies. Only admin, technician and viewer are recognised.
- Registration is closed outside development. `POST /auth/register` and a first sign-in with Google, GitHub or Microsoft for an address with no account answer 403 unless `REGISTRATION_OPEN` is true. Existing accounts still sign in and invitations still work.
- The live readings socket now closes a refused client with code 1008 after accepting it, so a browser can read the code. An open socket closes when its token expires and re-checks the session, the role and the machine rule every 60 seconds.
- The API container starts uvicorn with its access log off, because the socket URL carries the access token.
- Both firmware calls (`GET /firmware/latest` and `GET /firmware/download`) now need the key of a registered machine and are rate limited. The details of the latest firmware are kept beside the file so they survive a restart.
- The machine access rule moved from the devices routes into `app/services/access.py` so every route shares it.

---

## [2.5.0] - 2026-11-09

Moves the Discord setup script into its own discord folder and updates two lint dependencies past published security advisories.

### Added

- `discord/`, a component of its own for the community Discord server: the setup script, its requirements, a licence and a README on what the script builds, what it needs and the bot planned for it. It is published to [phaemos/discord](https://github.com/phaemos/discord) like the other components.
- Status badges for CI, the secret scan, the latest release and the licence at the top of the README.

### Changed

- `scripts/setup_discord.py` and its requirements moved to `discord/`. The `scripts/` folder is gone.
- The Discord invite is removed from the README and SUPPORT.md until the organisation runs a server of its own. Discussions is the chat route for now.
- `CONTRIBUTING.md` sends security disclosures to security@phaemos.com and has a Security section pointing at SECURITY.md.

### Security

- `minimatch` under the TypeScript lint tooling moved to 11.0.5 and `zod` under the React lint tooling moved to 4.6.7, past their published advisories. Neither ships to users.

## [2.4.1] - 2026-11-03

Adds a script that builds the PHAEMOS Discord server and updates the community files and the security reporting address.

### Changed

- Community files follow the [AI policy](https://github.com/phaemos/.github/blob/main/AI_POLICY.md): pull requests declare AI use and issue forms ask whether AI helped. Security reports go to security@phaemos.com.

### Added

- `scripts/setup_discord.py` builds the PHAEMOS Discord server from `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID`: the Admin, Maintainer, Contributor, Member and Bot roles, the PHAEMOS, Support, Hardware, Community and hidden Admin categories with their channels and a summary in #bot-logs with every id, the Ticket Tool and Carl-bot invite links and the steps left to do by hand. Running it again changes nothing.
- A link to the PHAEMOS Discord server in the README and SUPPORT.md.

## [2.4.0] - 2026-10-28

Redesigns the dashboard, adds Microsoft sign-in and scores each node type with its own anomaly model.

### Changed

- The Release workflow only checks that a version tag has a matching changelog heading, now in the `YYYY-MM-DD` date format the changelog uses. A maintainer creates the signed tag and the GitHub release with the changelog section as its notes, so every release is made by a person.

- A redesigned dashboard. Filters are single segmented controls instead of rows of pills. Status, severity and priority show as a dot and a word. Alerts form one list and tickets open from a button with the machine picked by name. Devices are a table and every page has the same header and card layout.
- Live readings are drawn as one small chart per sensor with its own scale, unit and latest value, so pressure near 1000 hPa no longer flattens a 23 degree temperature. The anomaly score comes first with the 0.7 alert threshold and a 10-reading average drawn on it.
- The dashboard opens on the machine with the newest active alert. A device page leads with its charts, then the latest readings and its details.
- The PHAEMOS emblem in the sidebar and on the sign-in page, the favicon, app icon and share image from `assets/brand`, plus a Microsoft button on the sign-in page. The sign-in page no longer shows the app navigation.
- The brand colour is the royal blue of the PHAEMOS emblem.

### Fixed

- The colour palette defines every shade the components use. Missing shades such as `surface-300`, `surface-500` and every `-400` rendered with no colour, so much of the text and many borders were invisible, above all in the light theme.
- Layout classes such as `items-center`, `justify-center` and `transition-colors` were spelt `items-centre`, `justify-centre` and `transition-colours`, which Tailwind ignores, so alignment and transitions were lost on 16 components.
- The fleet health card is readable in the light theme.
- Anomaly scores are calibrated against the trained model. The old fixed formula turned every normal reading into a score of 0.9 or more, so after training every reading counted as an anomaly. A typical healthy reading now scores near 0 and the model's own decision boundary sits at the 0.7 threshold, so about 5% of healthy readings are flagged as configured.
- Each node type is scored by its own model trained on the sensors it really has, plus a general model for readings without a node type. An STM32's eight vibration fields no longer sit beside an ESP32's 23 sensors as zeros. `backend/ml/train.py` and `evaluate.py` train and score through the same code as the API. `evaluate.py` also reports support correctly instead of failing.
- Tickets are numbered again. The backend creates its tables before the migrations run, so the `SERIAL` column from migration 004 was never added and every ticket number stayed empty.
- Readings are stamped as they arrive, so the latest few always sort in order.
- Static files (the icon, the share image, `robots.txt` and everything in `public/`) load for signed-out visitors and crawlers instead of redirecting to the sign-in page.
- The API smoke test registers its device with the `type` field the API expects.

- The dashboard's live telemetry WebSocket now connects to `/ws/telemetry/{device_id}`, the path the backend serves, instead of `/api/v1/ws/telemetry/{device_id}`, which never answered. The URL is built in `frontend/lib/wsUrl.ts` and covered by new frontend unit tests (`npm test`, run in CI on Node 24) and backend route tests.
- The deployment guide's Nginx config passes the WebSocket upgrade headers.
- The edge gateway passes the newer `assert_is_empty` clippy lint.

### Added

- The anomaly model raises its own alerts. Three anomalous readings in a row raise one alert (critical at a score of 0.85 or more) and open a maintenance ticket; three normal readings clear it. A fault that returns reuses the open ticket. Healthy readings are flagged about 5% of the time by design, so a chance run of three is about one in 8,000.
- Microsoft sign-in beside Google and GitHub, configured with `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_REDIRECT_URI` and `MICROSOFT_TENANT`. A Microsoft email never links to an existing account, since a work or school tenant can set an address it never verified.

- `assets/brand/linkedin/`: the logo, cover image and profile text for the [PHAEMOS LinkedIn page](https://www.linkedin.com/company/phaemos/), linked from the brand README.
- `ACCESSIBILITY.md`: what the dashboard, the nodes and the documentation do for accessibility, the known gaps and how to report a barrier.

### Security

- Edge gateway `rustls` raised from 0.23.45 to 0.23.46 in `edge/Cargo.lock`, closing GHSA-h2v8-394m-p7vv, GHSA-c8m5-c952-6cm4, GHSA-w44r-93j7-qv28 and GHSA-vp88-798v-h67f. Backend `authlib` stays pinned at 1.9.1, which already fixes the eight open `authlib` advisories, now with a note in `requirements.txt` that 1.9.1 is the minimum safe release.
- Backend JWT signing and verification moved from `python-jose` to `PyJWT` 2.15.1, since `python-jose` has no fixed release for GHSA-3qf3-8w2g-rqmx. Tokens keep the same HS256 format, claims and lifetimes, so existing sessions and invite links stay valid. New tests in `backend/tests/test_tokens.py` cover creating and verifying tokens, expiry and tampered or unsigned tokens.
- Frontend npm `overrides` raise `sharp` to 0.35.5, `source-map-js` to 1.2.2 and `postcss-selector-parser` to 7.1.6, closing GHSA-wq5f-xc86-pv6w, GHSA-68fv-2mgg-jv7q and GHSA-rj75-hqrm-r3gf.
- Sign-in is hardened across every method. Once enrolled, two-factor authentication is required at every sign-in, including Google and GitHub, through a short-lived challenge. Each code is accepted once. Tokens are only accepted for their own purpose. Changing the password or two-factor settings ends every other session. OAuth sign-in checks a state value, accepts only verified emails and keeps tokens out of URLs. Device changes follow each role's permissions. Rate limits trust proxy headers only from the proxy. The stack's ports listen on localhost only. Migration 010 adds the columns this relies on, so run `make migrate` on an existing database.
- Bumped backend `python-jose` to 3.4.0, `scikit-learn` to 1.5.0, `pytest` to 9.0.3 and `python-dotenv` to 1.2.2, closing 5 Dependabot alerts. Pinned a frontend `sharp` override to `^0.35.0` via npm `overrides`, closing 1 more. The remaining 21 open alerts (`authlib`, `python-multipart`) are already at their fixed versions in requirements.txt from earlier merged PRs, pending GitHub's next dependency graph rescan to auto-close
- Resolved CodeQL high-severity findings in backend: webhook URL platform detection now uses `urlparse` netloc comparison instead of substring matching to prevent bypass; phone number removed from SMS warning log to prevent PII exposure
- Pinned transitive `postcss` dependency to 8.5.10 via npm `overrides` to address GHSA-qx2v-qp2m-jg93 (XSS via unescaped `</style>` in CSS stringify output); the vulnerability was in the version of postcss bundled internally by next
- The OAuth login path's refresh cookie was hardcoded `secure=False` with a stale comment saying to gate it in production, unlike the password and TOTP verify paths which correctly gate on environment; now matches the same pattern

### Added

- A **Research** discussion form for papers, datasets and open questions that are not an issue yet
- A **Docs update** issue form and a **Q&A** discussion form
- `assets/brand/`: the PHAEMOS logo and emblem in light and dark versions with transparent backgrounds, the single-colour emblem, a 1280 by 640 social preview card and the full brand board, with the colours, type and usage rules
- New docs pages: `development.md` (running locally, the smoke test, the simulator and the test commands), `releases.md`, `tech-stack.md` and `repositories.md` (the monorepo layout and how publishing works), all in the docs site navigation
- `client/`: the `phaemos-client` Python SDK, the `phaemos-sim` simulator for all four node types with injectable faults and `phaemosctl`, a Go tool for status checks, sending readings and ingest load testing
- `edge/`: `phaemos-edge`, a Rust gateway that spools readings to disk and forwards them in order, so an outage loses nothing (ADR 020)
- `infra/` holds the Compose stack, the Prometheus and Grafana overlay and the SQL queries and seed data, published to its own repository. A root `docker-compose.yml` includes it, so every existing command still works from the root
- `backend`, `frontend`, `firmware` and `hardware` are published to their own read-only repositories on every merge to `main` (`split.yml`), each with its own licence and a note pointing back to the monorepo
- GitHub Sponsors added to `.github/FUNDING.yml` as first entry; order updated to github, buy_me_a_coffee, patreon
- `Repo maintenance` workflow (`update-pr-branches.yml`) to delete merged PR branches the merge could not clean up
- `.markdownlint.json` and a `markdownlint.yml` CI workflow, with a `.github/workflows/README.md` documenting every workflow in the repository
- YAML issue forms (`bug_report.yml`, `feature_request.yml`) replacing the old markdown issue templates
- `.github/ISSUE_TEMPLATE/config.yml` disabling the blank issue option, pointing to status page, Discussions, the security policy and the contact form instead

### Changed

- The frontend Docker image and the security audit job now use Node 24, matching CI. Node 20 has reached end of life.
- The published component repositories credit the project's automation account for each commit. Messages and dates are unchanged.
- Tidied code comments and the contributor guide.
- The README and `docs/architecture.md` are redrawn with Mermaid diagrams and checked against the code: versions, the ingest order, the role of Redis, notifications and the full API surface. The README now explains the name. The docs site renders Mermaid diagrams.
- The hardware docs describe Proteus for circuit simulation and KiCad for the schematics and PCB layouts. The Pico 2W's chip is named correctly as the RP2350.
- Hardware designs in `hardware/` are now licensed under the CERN Open Hardware Licence v2, Strongly Reciprocal (CERN-OHL-S-2.0), matching MELOPHOS. Everything else stays AGPL-3.0-or-later. `NOTICE.md` now explains which licence covers what and lists every dependency manifest. The README and docs licence sections say the same
- `CONTRIBUTING.md` rewritten: where to start, the branch, commit and style conventions, the email addresses and how to report a vulnerability, with callouts for the read-only component copies and security reports
- `hardware/README.md` rewritten with the correct firmware folders, the MPU6050 on the STM32 node, a warning about the Nano's 5 V logic and its own licence section
- Issue, discussion and pull request templates rebuilt: bug reports and questions ask for the component, both bug and feature forms ask to search first and the pull request template lists every component
- Callouts where a mistake costs something: private vulnerability reports in `SECURITY.md`, the Nano level shifter, the ESP32 LED strip power budget and `docker compose down` wiping the database
- README rewritten in full around the brand logo, which switches between its light and dark versions with the viewer's theme. It now covers what PHAEMOS does, a short architecture diagram, a table of every component folder and the repository it publishes to, a two-command quickstart and the simulator. The detail it used to carry moved into the docs: running without Docker, the smoke test and the test commands into `development.md`, the release flow into `releases.md`, the tech stack and boards into `tech-stack.md` and the folder tree into `repositories.md`. The docs home page lists every page and uses the current board names
- Auto-merge is now ecosystem-aware: patch and minor Dependabot bumps and major GitHub Actions bumps auto-merge once CI passes, but major `npm` and `pip` bumps are held for manual review since a breaking runtime change could pass lint and build yet still deploy; previously major bumps were skipped entirely
- README rewritten: dropped the leftover animated capsule-render footer banner, fixed a stale architecture line that implied ML anomaly scoring was not yet built (it has been live since Phase 2, only real hardware data is still pending), verified every doc link and image still resolves
- Backend `redis` bumped to 8.1.0, `pandas` to 3.0.5 and `bcrypt` to 5.0.0; frontend `tailwind-merge` bumped to 3.6.0, `react`/`react-dom` to 19 and `eslint`/`eslint-config-next` to 9/16, each held for manual review as a major bump and verified individually rather than merged blind
- Frontend migrated to Tailwind CSS v4: `@tailwindcss/postcss` replaces the old `tailwindcss` + `autoprefixer` PostCSS plugins, `globals.css` uses a single `@import "tailwindcss"` instead of the three `@tailwind` directives and the existing `tailwind.config.ts` stays in effect via `@config` rather than migrating its theme into CSS
- Frontend migrated to ESLint 9's flat config for `eslint-config-next` 16: `.eslintrc.cjs` replaced by `eslint.config.mjs` importing the package's native flat config export directly; `next lint` (deprecated, crashes on ESLint 9 with a circular-JSON error) replaced by calling the `eslint` CLI directly in the `lint` script
- Bumped backend `uvicorn` to 0.54.0. SQLAlchemy stays on 2.0.x and Dependabot now ignores 2.1 and later, since 2.1 switches a bare `postgresql://` URL to the `psycopg` driver while the backend uses `psycopg2-binary`.
- Tidied punctuation in the comments of `deploy.yml`, the monitoring compose file and the discussion templates.

### Removed

- Ignore rules for local working folders that no longer exist. The work they listed is tracked in the [roadmap issues](https://github.com/phaemos/phaemos/milestones)
- The Bugs discussion form, which had no matching discussion category. Q&A covers questions about unexpected behaviour
- `firmware/arduino/` and `firmware/stm32/`, the v1 sketches replaced by `arduino_nano/` and `stm32_blackpill/`. Nothing built or documented them and they gave the published firmware repository two STM32 folders. Git history keeps them

### Fixed

- The architecture, deployment and decision docs match the code. The schema has ten migrations (001 to 010). Decision 004 notes that the telemetry chart now uses a WebSocket with the 5-second poll as its fallback. The deployment docs state the current backend deploy (a disabled workflow holding an earlier Render hook) and the VPS planned for Launch.
- Each publish run checks out the latest `main`, so a push event that arrives late can no longer publish stale history to the component repositories.
- The pull request template's links, the conduct reporting route and two support answers now match the project. Older blog posts note where the hardware or the model has changed since they were written. The docs site builds with no warnings.
- `.github/CODEOWNERS` read `- @zaccesss` instead of `* @zaccesss`, so no pull request requested a review. It now carries the standard header and rule
- UK spelling and sentence joins in `docs/decisions.md`, `edge/README.md` and the audit log page range
- The STM32 driver READMEs called the MPU6050 driver an SPI driver. It talks to the sensor over I2C1, as the node README's wiring section shows
- Health check docs pointed at `/health`, which the API does not serve. Liveness is `GET /` and the public check is `GET /status`, which uptime monitors match on `operational`
- `SUPPORT.md`, `CONTRIBUTING.md` and the new issue page no longer link to phaemos.com, its status page or its docs site, none of which resolve before the Launch milestone. The new issue page links the roadmap board and `SUPPORT.md` instead
- `.github/dependabot.yml` had `open-pull-requests-limit: 0` on all three ecosystems, silently blocking every Dependabot PR since the pause was added; raised back to 5 on each ecosystem to match the limit already used in repo-ops and mirror-ops
- The `pydantic` bump to 2.13 split `email-validator` into an optional extra; schemas here use `EmailStr`, so bare `pydantic` no longer shipped it, added `pydantic[email]` to requirements.txt
- `prometheus-fastapi-instrumentator` 7.1.0 accessed a router attribute the newer `fastapi`/`starlette` no longer exposes; bumped to 8.1.0 alongside the `fastapi` bump it depends on rather than as a separate PR
- Tests asserting 403 for a missing Authorization header were updated to 401, matching newer `starlette`'s `HTTPBearer` behaviour; role-guard 403s for an authenticated but unauthorised user are unaffected
- `passlib` (unmaintained since around 2020) is incompatible with `bcrypt` 4.1+ in two ways: it reads a version attribute bcrypt 4.1+ removed and its own internal self-test hashes a deliberately 255-byte probe string that bcrypt 4.1+ now correctly rejects instead of silently truncating. Restored both the version attribute and the old truncate-rather-than-raise behaviour at the `bcrypt.hashpw`/`checkpw` boundary; real passwords are separately capped at 72 bytes in the password strength validator
- 18 existing call sites across several hooks and components were newly flagged by stricter `react-hooks` rules aimed at React Compiler compatibility, bundled with the `eslint-config-next` 16 upgrade. One (`app/faq/page.tsx`) was a genuine issue, a running counter mutated during render, replaced with a precomputed per-section offset. The other 17 are legitimate, documented patterns (syncing state from an external source on mount, an intentional ref read to batch WebSocket pushes between polls, a standard recursive-reconnect closure) that this new rule set is unable to distinguish from unsafe code; each is annotated with a scoped, justified `eslint-disable` rather than rewritten

## [2.3.0] - 2026-06-03

Adds Google and GitHub sign-in, two-factor authentication, webhooks, maintenance windows and the public pages under a new AGPL-3.0 licence.

### Added

- Multi-tenant device ownership: nullable `owner_id` FK on devices; technicians see only their own devices; admins see all (PR 86)
- Auth hardening: every non-public backend route now requires a valid JWT; admin-only routes require role=admin (PR 88)
- Refresh token flow: 15-minute access tokens + 7-day httpOnly refresh cookie; `POST /auth/refresh` and `POST /auth/logout` endpoints (PR 89)
- Human-readable ticket numbers in PHM-0001 format (SERIAL column, backend + frontend display) (PR 90)
- Google OAuth and GitHub OAuth sign-in (authlib, email-matched upsert, redirect with JWT) (PRs 91, 92)
- TOTP two-factor authentication: enable, confirm, verify, disable endpoints; `pyotp` + QR code via `qrcode` (PR 93)
- User profile management: `PATCH /auth/me`, `POST /auth/change-password`, `DELETE /auth/me` (GDPR erasure), `GET /auth/me/export` (GDPR portability) (PR 94)
- Webhooks backend: Slack, Discord and Teams integrations; auto-detect platform from URL; custom message template; test endpoint (PR 95)
- Fleet health summary: `GET /health/summary` returning online/offline counts and health score; public `GET /status` database and Redis health check (PR 96)
- Maintenance windows: create/update/delete windows; alert suppression during active windows; `POST /api/v1/maintenance-windows` admin endpoint (PR 97)
- Device tags: PostgreSQL ARRAY column; `POST /devices/{id}/tags`, `DELETE /devices/{id}/tags/{tag}`; tag filter on `GET /devices`; `POST /devices/batch/firmware-update` by tag (PR 98)
- RBAC permissions: JSONB `permissions` column on users; `PATCH /auth/users/{id}/permissions` admin endpoint (migration 009) (PR 101)
- SMS critical alerts via Brevo transactional SMS API; graceful no-op when key is not configured (PR 102)
- User invitation flow: `POST /auth/invite` sends signed JWT link via Resend; `GET/POST /auth/accept-invite` for onboarding (PR 104)
- Axios refresh token interceptor: silently retries 401 responses using the httpOnly refresh cookie (PR 99)
- Design system: Tailwind colour tokens (brand, surface, success, warning, critical); Sidebar nav replacing top nav; `SidebarNav` component (PR 100)
- Toast notification system: `ToastProvider` context + reducer; success/warning/error/info variants with 4s auto-dismiss (PR 105)
- Device owner picker (admin only) on device detail page (PR 106)
- Tab visibility pause: telemetry polling pauses when `document.hidden` is true (PR 107)
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`; `robots.txt`; `sitemap.ts` (PR 108)
- Rate limiting on all sensitive endpoints: login (5/min), register (10/hr), password change (5/hr), contact form (3/hr), ML retrain; proxy-aware key function reads `X-Real-IP` from Nginx (PR 109)
- Profile page: name/email/phone edit, password change, 2FA enrolment UI, GDPR export and account deletion (PR 110)
- Health summary widget on dashboard: four stat cards polling `GET /health/summary` every 30s (PR 111)
- Webhook admin UI: list, create, delete, enable/disable toggle, test button (PR 113)
- Privacy policy (`/privacy`), terms of service (`/terms`) and cookie consent banner with localStorage consent gate (PR 114)
- About page (`/about`), blog with three posts (`/blog`), rendered changelog (`/changelog`), docs hub (`/docs`) (PR 115)
- Status page (`/status`): polls `GET /status` every 30s, shows per-component health badges and public Instatus link (PR 116)
- Security (`/security`), FAQ (`/faq`), support (`/support`) public pages; all added to middleware `PUBLIC_PATHS` (PR 118)
- Contact form (`/contact`): Cloudflare Turnstile bot protection, SMTP send, 3/hr rate limit (PR 125)
- Vercel Analytics and Google Analytics 4 (consent-gated, loads only after cookie accept) (PR 120)
- Maintenance windows admin panel and dashboard amber pulsing banner (PR 121)
- Device tag chips on DeviceCard; inline tag add/remove on device detail; batch firmware update modal (PR 122)
- MkDocs Material documentation site (`docs.phaemos.com`); `mkdocs.yml`, `requirements-docs.txt`, `docs/index.md`; `make docs` and `make docs-build` targets (PR 128)
- Instatus external status page setup guide (`docs/instatus.md`); public status card on `/status` page linking to `status.phaemos.com` (PR 129)
- Scalability guide (`docs/scalability.md`): six-stage scaling path from single VPS to distributed (PR 130)
- GitHub Discussions: four category templates; README Community section and badge; support and FAQ pages updated (PR 132)
- CodeQL security scanning workflow (Python + JavaScript, push/PR/weekly schedule); stale issue workflow; `FUNDING.yml` (PR 127)
- GDPR cookie consent gate on GA4; `GoogleAnalytics.tsx` client component reads `cookie_consent` from localStorage (PR 120)
- `frontend/.env.example` documenting all `NEXT_PUBLIC_*` variables (PR 135)
- Input validation `max_length` on all string fields in device, ticket and webhook Pydantic schemas (PR 135)

### Changed

- Deployment platform: Render replaced by DigitalOcean VPS with Docker Compose + Nginx reverse proxy; `docs/deployment.md` fully rewritten (PR 129)
- Rate limiter key function updated to read `X-Real-IP` from Nginx instead of `request.client.host` so per-IP limits work correctly behind a reverse proxy (PR 135)
- `docs/week_by_week.md` rewritten from rigid 12-week table to phase-based structure separating done from pending work (PR 135)
- `docs/architecture.md` updated for v2 hardware, Next.js 15 and DigitalOcean deployment (PR 135)
- `docs/api-reference.md` expanded with all endpoints added since v2.2.0 (PR 135)
- Tidied punctuation in source comments (PR 135)

### Fixed

- STM32 FFT migrated from custom O(N^2) DFT to `arm_rfft_fast_f32` (CMSIS-DSP); 9x speedup on 96 MHz Cortex-M4F; N=128 power-of-two buffer (PR 131)
- CI postgres service container replaced with explicit pull-with-retry loop to survive transient Docker Hub timeouts (PR 134)
- Broken `uptime-kuma.md` link in `docs/index.md` replaced with `instatus.md` (PR 135)
- `NEXT_PUBLIC_GA_ID` added to `.env.example` (was referenced in code but undocumented) (PR 135)
- Legacy `RENDER_DEPLOY_HOOK_URL` removed from `.env.example` (PR 135)

### Security

- Licence changed from Apache 2.0 to AGPL-3.0; `LICENSE` and `NOTICE` files added; README badge updated (PR 123)
- Responsible disclosure policy updated to use GitHub Security Advisories as primary channel (PR 135)
- Input validation: `Field(max_length=...)` added to all unbounded string fields in device, ticket and webhook schemas - prevents storage exhaustion attacks (PR 135)

## [2.2.0] - 2026-06-02

Adds WebSocket reconnects, admin retraining of the anomaly model and pagination for tickets and devices.

### Added

- WebSocket reconnect with exponential backoff (1/2/4/8/16s, max 5 attempts). No retry on close code 1008 to prevent token-expiry loop (PR 77)
- `useWebSocketTelemetry` hook; `TelemetryChart` now merges live WS pushes with 5s polling and deduplicates by id (PR 77)
- `POST /api/v1/ml/retrain` - admin-only endpoint; fits IsolationForest on last 10,000 rows, dumps model.pkl and reloads in-memory model; 1-hour cooldown; logs outcome to audit log (PR 80)
- `FEATURE_COLS` constant and `reload_model()` in `ml_service.py` so scoring and retraining use the same feature vector (PR 80)
- SensorGrid on device detail page polls `GET /telemetry/{id}/latest` every 5s via `useTelemetry` - live sensor values without a page refresh (PR 81)
- AlertBanner now has a Create Ticket button that opens a modal with TicketForm prefilled from alert context (device_id, title, severity/timestamp in description) (PR 83)
- Pagination on `GET /tickets` and `GET /devices` - `skip`/`limit` query params (default 0/20) (PR 84)
- Prev/Next pagination controls on Tickets and Devices frontend pages (PR 84)
- `docs/security.md` - 18-measure security table (PR 85)
- `Makefile` - make dev, make test, make lint, make build, make migrate, make seed (PR 85)
- `SUPPORT.md` - self-help resources and common issues (PR 85)
- Three new ADRs in `docs/decisions.md`: WS JWT via query param (010), ML retrain as background task (011), skip/limit pagination (012) (PR 85)

### Fixed

- `alerts.resolved` ORM column changed from `Column(String)` to `Column(Boolean)`. `str(resolved)` cast removed from list-alerts filter - DB schema was already BOOLEAN so no migration required (PR 82)
- Alert rule evaluation now receives all v2 sensor fields. The ingest route previously built `reading` from 6 hardcoded fields; rules on `gas_level`, `shaft_rpm` etc. would never fire (PR 79)
- `/ml/score` endpoint fixed to use `payload.model_dump()` instead of same 6-field hardcoded dict (PR 80)

## [2.1.0] - 2026-06-01

Adds a login page with a session guard and a hardware inventory, with fixes to dashboard polling and the CSS build.

### Added

- Login page and session guard (backlog - next session)
- Hardware inventory tracking: hardware/inventory/owned.md and needed.md with full component list
- README added to every folder and subfolder across the entire repo
- Pico W schematic placeholder added to hardware/schematics/
- PostCSS config (postcss.config.js) - was missing, causing Tailwind CSS to not compile
- alerts.resolved String/Boolean type mismatch fix in routes/alerts.py
- Dashboard selected-device polling bug fix - user selection no longer resets every 5 seconds

### Changed

- TelemetryChart refactored: prop changed from readings[] to deviceId, now manages own data fetch
- Dashboard uses Promise.allSettled so a failing alerts query never blocks device cards
- layout.tsx: suppressHydrationWarning on html element, proper light/dark body classes

## [2.0.0] - 2026-05-30

Adds firmware for the four sensor nodes, an extended telemetry schema, device comparison, a demo mode and the repository's community and CI files.

### Added

- Extended telemetry schema with 18 new sensor columns (v2)
- ESP32 v2 structured firmware: 10 sensor modules, 4 output modules, 3 comms modules
- STM32 Black Pill firmware (FFT vibration analysis)
- Arduino Nano firmware (auxiliary sensor node)
- Raspberry Pi Pico 2W MicroPython firmware (ambient environment node)
- Backend additions: audit_service, Alembic migrations, ML evaluate skeleton
- Frontend additions: SensorGrid, TicketTable, polling hooks, UI components
- Hardware wiring guides for all 4 nodes
- Sensor reference documentation
- Deployment guide and checklist
- VERIFICATION.md tracker
- JWT auth: get_current_user dependency, /auth/me, /auth/users (admin)
- GET /audit-logs endpoint (admin, paginated)
- Audit service calls wired into all mutating routes
- Alert rules CRUD (GET/PUT/DELETE /alert-rules)
- AlertRulesPanel admin component
- TicketForm, UserTable, AuditLog wired to real endpoints
- Device detail page with SensorGrid, TelemetryChart and Export CSV
- TelemetryChart: 4 collapsible per-sensor groups, 1h/6h/24h/7d time range picker
- GET /telemetry/export CSV streaming endpoint
- Device comparison page /compare with up to 3 side-by-side columns
- Global nav bar
- node_type filter on GET /telemetry and dashboard picker buttons
- firmware_version column on Device model and DeviceCard display
- Demo mode: POST /demo/start with APScheduler sinusoidal data generation
- 90-day data retention task via APScheduler cron (02:00 UTC)
- Dark/light mode toggle with ThemeToggle and localStorage persistence
- ML evaluate.py fully implemented: load_model, evaluate_precision_recall, plot_anomaly_distribution, generate_report
- Uptime Kuma setup documentation
- Docs updated: api-reference, architecture, decisions, schema, VERIFICATION

### Added

- Repo health files: LICENSE, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT and SECURITY
- GitHub Actions CI pipeline for backend linting and frontend type-checking
- Gitleaks secret scanning workflow
- GitHub release workflow with changelog version validation on pushed tags
- Biweekly GitHub workflow that opens or updates a security issue when `npm audit --omit=dev` reports frontend production vulnerabilities
- Issue templates for bug reports and feature requests
- Pull request template
- Dependabot configuration for automated dependency updates
- CODEOWNERS file
- `.editorconfig` for consistent formatting across editors
- Deployment checklist for Render backend and Vercel frontend
- Docker build-context ignore files for backend and frontend images
- pytest test suite with PostgreSQL service container in CI and transaction-rollback test isolation
- WebSocket real-time telemetry push endpoint (`/ws/telemetry`)
- OTA firmware upload route and ESP32 OTA sketch
- Discord webhook and SMTP email notification service
- Grafana and Prometheus monitoring overlay (`monitoring/`)
- Auto-deploy workflow triggering Render on CI pass

**v2.0 hardware spec additions (30-05-2026)**

- Extended telemetry schema with 18 new sensor columns: node\_type, pressure (BME280), gyro\_x/y/z (MPU6050), bus\_voltage/current\_ma/power\_mw (INA219), ir\_temperature (MLX90614), distance\_mm (VL53L0X), gas\_level/gas\_alert (MQ-2), shaft\_angle/shaft\_rpm (AS5600), sound\_level (MAX4466), contact\_temp (DS18B20), moisture\_level/water\_detected (FC-28), fft\_peak\_hz/vib\_magnitude (STM32 FFT output)
- ESP32 v2 firmware structured subfolder layout: `firmware/esp32/sensors/` (10 sensor pairs), `firmware/esp32/outputs/` (OLED, buzzer, RGB LED, relay), `firmware/esp32/comms/` (WiFi manager, HTTP client, serial parser), new `esp32.ino` v2 main sketch
- STM32 Black Pill firmware (`firmware/stm32_blackpill/`): HAL I2C register-level MPU6050 driver, DFT FFT implementation, 100Hz TIM2 sampling, UART output
- Arduino Nano firmware (`firmware/arduino_nano/`): BME280 + LDR + FC-28, CSV serial output at 9600 baud for ESP32 to parse
- Raspberry Pi Pico 2W firmware (`firmware/pico_w/`): MicroPython BME280 driver with full datasheet compensation, SSD1306 OLED driver, Wi-Fi connect helper, urequests HTTP POST
- Backend package `__init__.py` stubs for models, routes, schemas, services directories
- `audit_service.py`: standalone `log_action()` using raw SQL so audit entries survive ORM changes
- `backend/migrations/001_initial_schema.sql`: complete CREATE TABLE schema for all 7 tables with indexes
- `backend/ml/evaluate.py`: skeleton with docstrings for `load_model`, `evaluate_precision_recall`, `plot_anomaly_distribution`, `generate_report`
- `backend/.env.example`: all 15 environment variables documented
- Frontend `useTelemetry` and `useAlerts` polling hooks with setInterval cleanup
- `lib/utils.ts`: formatDate, formatSensorValue, severityColor, clamp, nodeTypeLabel helpers
- `StatusBadge`, `LoadingSkeleton`, `ErrorToast` UI primitive components
- `SensorGrid` dashboard component showing all 11 v2 sensor categories
- `TicketTable` (sortable), `TicketForm` (stub), `UserTable` (stub), `AuditLog` (stub) components
- Device detail page stub at `app/devices/[id]/page.tsx`
- `hardware/` folder: Proteus schematic placeholders, wiring guides for all 4 nodes, PCB design guide
- `docs/sensor_reference.md`: full sensor tables with I2C addresses and library references
- `docs/deployment.md`: Render + Vercel + Docker self-hosted deployment guide
- `docs/week_by_week.md`: updated 12-week implementation plan
- `docs/VERIFICATION.md`: living checklist tracking verified vs pending features
- Repo settings: auto-merge enabled, auto-delete-branch-on-merge enabled
- Branch protection on main requiring all 4 CI checks to pass before merge

### Changed

- Frontend upgraded from `next@14.2.3` to `next@15.5.15`
- Frontend PostCSS pinned to `8.5.10` in direct dev dependencies
- Release changelog date heading format standardised to `DD-MM-YYYY`
- README architecture diagram updated to show all 4 nodes and full sensor list
- README hardware table updated to v2 hardware spec
- README project structure updated to include hardware/ folder
- README tech stack updated to Next.js 15 and full firmware language list
- `backend/requirements.txt` extended with `python-dotenv` and `pytest-asyncio`

### Fixed

- Next.js 15 async params type in `app/devices/[id]/page.tsx` (params is now `Promise<{ id: string }>`)

### Security

- Removed previously reported critical and high severity frontend advisories by moving off the vulnerable Next 14 line
- Remaining moderate transitive PostCSS advisory is currently upstream in Next.js and is tracked for future patch updates
- `.gitignore` extended to exclude Arduino build artefacts (`*.elf`, `*.bin`, `*.hex`, `*.map`) and Proteus files (`*.DBK`, `*.LKS`, `*.SDF`)

---

## [0.2.0] - 2025-05-06

Adds version and environment fields to the API's health response.

### Added

- `version` and `environment` fields in the root health endpoint response

---

## [0.1.0] - 2025-05-01

First version: a FastAPI backend, a Next.js dashboard and firmware for an ESP32, an Arduino Uno and an STM32 node.

### Added

- FastAPI backend with telemetry ingestion, device registry, alert rules and ticket system
- JWT authentication with role-based access control (admin, technician, viewer)
- PostgreSQL data models and SQLAlchemy ORM layer
- Isolation Forest ML anomaly scoring pipeline
- Next.js frontend with live dashboard, device list, alert feed and ticket management
- ESP32 firmware for DHT22 temperature/humidity and MPU6050 vibration readings
- Arduino Uno secondary firmware
- STM32 high-frequency vibration firmware
- Docker Compose local development stack
- Initial project documentation
