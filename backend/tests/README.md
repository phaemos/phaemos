# Tests

pytest test suite. Uses a real PostgreSQL test DB (not mocks).

| File | Coverage |
| --- | --- |
| conftest.py | Fixtures - test DB setup, admin user, auth headers, device |
| test_auth.py | Register, login, /me, JWT validation |
| test_tokens.py | JWT create and verify, token format, expiry, tampered and unsigned tokens, invite tokens |
| test_telemetry.py | Ingest, history, latest, export, v2 sensor fields, bucketed history (means, maxima, flag OR, empty buckets, bounds and the bucket cap) |
| test_alerts.py | List alerts, resolve, alert rules |
| test_ml.py | ML score endpoint, retrain admin guard, retrain cooldown |
| test_anomaly_decision.py | The anomaly alert decision at every edge: exactly 80 per cent, the 12 reading minimum, the window length at fast and slow intervals, a gap resetting the window, critical and escalation, the hysteresis, resolving, the 15 minute re-arm delay. No database |
| test_training_data.py | Which readings may teach the model, run in SQL against the test database: maintenance and fault and open alert and link gap refusals with their counts and the split by time with no leak, the even sampling and the caps and agreement with the in-memory selection the evaluation uses |
| test_ml_model.py | The fast scorer against scikit-learn, `contamination="auto"`, the 0 to 1 mapping, the measured boundary, the budget and detection refusals and their messages, what a retrain carries over, the learning state, the cap on machine models, bundle size and scoring time, which model scores a reading, the model status in every state and the model file (atomic save, `.prev` fallback, picking up a newer file). Simulated machines, no database |
| test_ml_replay.py | The replay of the design: the same seeded healthy week through the old three-in-a-row rule and the new model and decision, false alerts per machine per week side by side, the labelled faults with their delays, a faithful copy of the old rule and that the replay gate changes no result |
| test_contact.py | Contact form: Turnstile verify URL, fail-closed outside development, 422 and 503 paths, visitor address, rate limit. The Cloudflare call is mocked, so no test reaches the network |
| test_email_service.py | The one email path: sender, recipients, Reply-To, escaping, unconfigured behaviour, Resend failure, invite route and alert email recipients. The Resend call is mocked |
| test_sms_service.py | Brevo request shape, E.164 and sender checks, the 160 character cap, number formatting and error logging. The HTTP call is mocked |
| test_alert_notifications.py | Repeat window, daily caps, failed sends freeing the window, background dispatch, the anomaly path and ingest surviving vendor failures |
| test_notify_service.py | Discord alert failures log the status or type and never the webhook URL |
| test_logging_config.py | INFO in development, WARNING elsewhere, uvicorn loggers untouched |
| test_phone_number.py | Profile phone number: empty or E.164, with the format in the error |
| test_access_control.py | Machine access rule across telemetry, the anomaly history, the live socket (refusal, expiry and re-checks), alerts, alert rules, tickets, maintenance windows, device owner and tag changes and the health totals: admin, owning technician, other technician, viewer and unowned machine, lists included |
| test_accounts_and_lists.py | Account deletion rules and proof, the complete export, the user list without phone numbers, webhook address safety, owner and ticket names, assignees, totals and paging, alert links and the provider list |
| test_sessions_and_proof.py | Server-side sessions (rotation, theft, logout from the cookie alone), proof of ownership for email, two-step and deletion, provider linking, paging caps, tickets that lost their machine, delete rules, export gaps and small fixes |
| test_account_security.py | Failing closed, the sign-in slowdown (the attack and then the real owner signing in), sign-in answers that give nothing away, NUL characters, invitations in a table, a key for each purpose and key rotation, admin control of accounts (every rule, the audit rows and the admin lock), fresh proof on the dangerous admin routes, encrypted two-step secrets and the small fixes |
| test_access_tokens.py | Access tokens: every route in one stated class (the printed table), a token refused on every session-only route and a read token on every write, the scope rules, the role read on every call, the same 401 and one hash for every bad token, limits per token with an account ceiling, making and revoking, the audit trail and the export |
| test_email_limits_and_account_linking.py | Email change limits and notices, wrong-proof status codes, clearing the lock count, the refresh grace and row lock, cookie lifetime, the phone proof, ending your own session, invitation checks, migration shape (skips without a full checkout), the image and compose files (skip without a full checkout) and linking a provider |
| test_sessions_and_email_change.py | Failure counting on every proof route, the email change aftermath, sessions routes and absolute lifetime, cookie paths, per-origin CORS, logging of database errors and start-up errors, one-time invitations and small fixes |
| test_hardening.py | Webhook delivery checks and pinning, heavy-read limits, the uvicorn log filter, IPv6 rate-limit keys and the uvicorn flags and Nginx limits for the live socket. The Dockerfile and Nginx checks need the whole repo, so they run from a full checkout (`python -m pytest backend/tests/test_hardening.py` from the repo root) and in CI and skip inside the backend-only test container |
| test_registration.py | Open and closed registration, OAuth with and without an existing account, invitations when closed and the create-admin logic |
| test_firmware.py | Device key checks on both firmware routes, rate limits and the stored latest-version details |
| test_sensor_map.py | Every telemetry field belongs to a sensor, no field belongs to two, the fault map is cleaned (unknown states, `ok`, key length, entry cap) |
| test_unmeasured_not_scored.py | A missing feature gives a null score and no flag, a present zero still scores, training leaves out and counts incomplete rows, the general model's columns, the node type and general fallback, three scored anomalous rows still open the alert and ticket and unscored or stale rows cannot |
| test_node_health.py | Health fields stored and validated, a current-style post unchanged, a faulted sensor's rule not firing and its value stored as null with the rejected value in `quality`, lost posts, the restart-loop alert, `link_state` and `health` on the device routes and the alert `category` filter |
| test_liveness.py | The sweep's three states and `status` consistency with an injected clock, the monitoring alert opening once and resolving itself with the outage length, the start-up grace, maintenance, the notification after commit, the Redis lock and its fallback, the scheduler job |
| test_notification_queue.py | Discord and webhook calls queued and not made in the request, the hourly window per device, metric and severity, failed sends freeing the window, anomaly alerts through Discord |
| test_ingest_batch.py | The batch route and `observed_at`, from the attacker's side first: per-item replay under one lock, the allowance, a backlog never judged as current, backdated readings that cannot dilute the anomaly window |
| test_api_contract.py | Filters, keyset walks, item reads, partial updates, idempotent creates, the signed json webhook with its retries, the aliases kept for one release and the headers on a hand-raised 429 |
| test_device_keys.py | Keys stored as a hash and never read back, lookup by id, the same answer and work for an unknown and a wrong key, the upgrade of keys held in clear, rotation limited to admins and owners |
| test_replay.py | Replay protection: newer, duplicate, older and missing pairs, the unprotected machine, the admin's accept-counter and the lock order |
| test_attacker_lies.py | A stolen key posting calm lies: fault claims with no alert behind them, the firmware's not-fitted list, impossible values, flapping, physical ranges and what training leaves out (with the real fault gating) |
| test_stuck_sensors.py | The stuck sensor check on its own and through a post |
| test_hardening_misc.py | Spreadsheet safe cells, a machine's share of the daily caps, the phone confirmation gate and the no-scored-reading alert skipping machines that are unscored by design |
| test_rule_alerts.py | Stateful rule alerts with an injected clock (hold, gaps, in-place updates, margin and clear hold, notifications and reminders, unavailable fields, edits, deletes, hand resolve, the API fields, the migration's collapse) and the anomaly decision through `evaluate_anomaly` with the decision stubbed |
| test_alert_delivery_and_locking.py | Failures after the commit, the notify pool (order, bound, drops, undo), the window and the daily cap under concurrency, deadlock retries and lock order, the model alert under the unique index, rule metrics, the anomaly-score rule, hand resolves, the hub's `diag`, `board_mismatch` and `not_fitted` and that every migration guard sends nothing on an up-to-date database |
| test_alerting_path.py | The session closed before notifications, no pool connection checked out while one is in flight, a model that cannot be loaded or used, the ingest limit, bounded tracking, the open-alert unique index and the device lock, the migration's duplicate handling, clipping and the water input |
| test_fault_alerts.py | One stateful alert per device and sensor (opens after a minute, updates, resolves, flapping, not fitted, maintenance, email window), the no-scored-reading alert, the rules that cannot be evaluated and the admin-only `not_fitted` field, with injected clocks |
| test_satellite_fields.py | The Nano and Black Pill columns, their ranges, faults on the satellites and their links, the `links` object, the bucketed reads and the export |
| test_cooldown_breaker.py | After one failed Redis call the windows use process memory and Redis is skipped for a while |
| test_deploy_script.py | `deploy.sh` migrates an existing database before the new code starts and keeps its safety checks |
| test_read_limits.py | Paging bounds on the device and telemetry lists, only an admin or a technician owning a machine and the heavy-read slots held by an export for the whole stream and by a bucketed read |
| test_shaft_angle.py | The bucketed shaft angle stays below 360 and is null when the angles do not agree |
| test_retention.py | Closed tickets, resolved alerts and audit entries deleted past their periods with an injected clock, open tickets and unresolved alerts kept, the ticket and alert key respected, periods as settings, each result audited |
| test_health_access.py | The machine access rule on `link_state`, `health`, the summary's `link_states` and the monitoring alerts: admin, viewer, owning technician, other technician, unowned machine and an unknown role |
| test_devices.py | list_devices role filter (admin/viewer/technician), auth guard, owner_id in response |

Run: `make test` from the repository root. It creates a `phaemos_test` database next to the development one. To run `pytest` directly, point `DATABASE_URL` at a database whose name ends in `_test`: the suite drops its tables at the end and refuses any other name.
