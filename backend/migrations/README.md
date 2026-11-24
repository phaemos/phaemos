# SQL Migrations

Plain SQL migrations. Apply in order when upgrading an existing database.
The API creates any missing table from the ORM models on start. That does not alter an existing table and does not create everything: the audit log table and some indexes come only from these files. `make migrate` and `infra/scripts/deploy.sh` apply all of them on every run.

| File | Description |
| --- | --- |
| 001_initial_schema.sql | Full initial schema: all tables (including the audit log), indexes and the v2 telemetry columns |
| 002_security_hardening.sql | Adds `failed_login_attempts` and `locked_until` to users |
| 003_multi_tenant.sql | Adds nullable `owner_id` FK on devices referencing users |
| 004_ticket_numbers.sql | Adds a human-readable ticket number with a unique index |
| 005_oauth_and_profile.sql | OAuth sign-in and profile columns on users |
| 006_webhooks.sql | Webhook integrations table |
| 007_maintenance_windows.sql | Maintenance windows table |
| 008_device_tags.sql | Device tags as a PostgreSQL array with a GIN index |
| 009_rbac_permissions.sql | Per-user permissions column. Retired: nothing reads or sets it. The column stays |
| 010_session_security.sql | Session version and one-time code columns for sign-in |
| 011_telemetry_device_time_index.sql | Index on telemetry by device and time (newest first), built with `CONCURRENTLY` so ingest is not blocked. It first drops a leftover invalid copy from an interrupted build |
| 012_health.sql | Node health (sets a three second lock timeout and alters the readings table in one statement): `seq`, `device_ts` and `quality` on telemetry, the `device_health` table (latest vitals and faults per device), `expected_interval_s` and `link_state` on devices, `category` and `sensor_key` on alerts |
| 013_ticket_delete_rules.sql | Gives the four ticket foreign keys `ON DELETE SET NULL` where a database built by `create_all` left them without a rule. It changes a key only when its rule is wrong, finds a key by its column whatever it is called and gives up after a 5 second lock wait |
| 014_alerts_category_index.sql | Index on alert category and resolved state, built with `CONCURRENTLY` so a live alerts table keeps taking writes. It first drops a leftover invalid copy |
| 020_open_alert_unique.sql | `kind` on alerts, the kind of existing monitoring alerts worked out from their text, older duplicate open alerts resolved (the newest is kept) and a unique index on open alerts by device, kind and sensor key, built `CONCURRENTLY`. If a new duplicate appears while it builds the index build fails: run the file again |
| 029_stateful_rule_alerts.sql | Stateful rule alerts: the columns an alert keeps (`occurrences`, `last_value`, `peak_value`, `last_seen_at`, `notified_at`), `for_seconds` and `clear_margin` on a rule, the `rule_states` table, the system-alert index moved to one that leaves rule alerts out, the collapse of open duplicate rule alerts into one per machine and rule (the oldest row is kept as the alert, the others are resolved and say why, nothing is deleted) and the unique index for rule alerts. Indexes are built `CONCURRENTLY` and every step is conditional |
| 039_detector_state.sql | `devices.detector_state` JSONB: the anomaly change detector's state per machine (about 1 kB), read and written under the device lock at ingest |
| 040_alert_fault_confirmed.sql | `alerts.fault_confirmed`: a person's verdict on a machine alert (true a real fault, false not one, null not yet said). Only a confirmed model alert keeps its readings out of the anomaly model's training. Conditional, with a three second lock timeout |
| 041_device_ambient_source.sql | `devices.ambient_source_id`: another node in the same place whose air temperature is this machine's ambient reference for the anomaly model. Conditional, with a three second lock timeout |
| 036_webhook_delivery.sql | Webhooks: `format` (`chat` or `json`), the encrypted signing `secret`, `last_delivery_at`, `last_status`, `last_error` and `consecutive_failures`. Conditional, so a second run takes no lock |
| 037_keyset_indexes.sql | Indexes for keyset paging, built `CONCURRENTLY`: alerts `(device_id, triggered_at DESC, id DESC)` and `(triggered_at DESC, id DESC)` and telemetry `(device_id, recorded_at DESC, id DESC)`. Pipe the file to psql without `--single-transaction` |
| 031_device_keys_replay_hold.sql | Device keys by id and hash (`key_id`, `key_hash`, the old `api_key` column made nullable and its ids filled in), replay protection counters on `devices`, the stuck sensor state, `hold_count` and `hold_peak` on `rule_states` and `first_seen_at` on `alerts`. The hashes need the server's secret key, so the application hashes each old key when it starts or when that machine next posts. Every step is conditional and the unique index is built `CONCURRENTLY` |
| 028_alert_state.sql | The model's alerts get a kind (older duplicate open model alerts are resolved, the newest is kept), `alerts.resolved` becomes NOT NULL with a default of false in steps that hold no long lock and `device_health` gets the hub's `diag`, `board_mismatch` and `not_fitted_by_firmware`. A NULL written during the change makes the validation fail: run the file again |
| 021_vibration_clipping.sql | `vib_clipping` on telemetry and the clipping state on devices |
| 015_fault_alerts_and_links.sql | The Nano and Black Pill value columns on telemetry, `links` and `sensor_track` on device_health and `not_fitted` and the no-scored-reading state on devices. Sets a three second lock timeout |
| 016_user_sessions.sql | Server-side sign-in sessions (`user_sessions`). The clean-up job should run `DELETE FROM user_sessions WHERE expires_at < now() - interval '1 day'` |
| 017_alert_rule_delete_rule.sql | `alerts.rule_id` keeps the alert when its rule is deleted. Same method as 013 |
| 018_provider_signin.sql | Retired and now a no-op. It added `users.provider_signin_at`, which moved onto the session in 022 |
| 019_webhook_disabled_reason.sql | `webhooks.disabled_reason`, why delivery switched a webhook off |
| 022_session_details.sql | `user_sessions.label` and `user_sessions.provider_signin_at` and drops `users.provider_signin_at` where 018 added it |
| 023_used_invites.sql | `used_invites`, so an invitation works once. The clean-up job can run `DELETE FROM used_invites WHERE used_at < now() - interval '3 days'` |
| 024_email_changes.sql | `users.email_since` and the `email_changes` table, for email change limits and for who is mailed a notice |
| 025_session_rotation.sql | `user_sessions.previous_jti` and `rotated_at`, for the 10 second refresh grace |
| 032_accounts_hardening.sql | `users.is_active` and `deactivated_at`, `totp_secret` as TEXT for encrypted secrets and the `invitations` table. The API encrypts existing two-step secrets at start. Needs the table owner and no superuser right |
| 033_email_lower_case.sql | Lowers every address that cannot clash, reports a clash as a notice and adds a unique index on `lower(email)`. Needs the table owner and no superuser right |
| 034_phone_confirmation.sql | `users.phone_confirmed_at` and the pending code columns. Existing numbers start unconfirmed, so alert texts stop until each person confirms theirs. Needs the table owner and no superuser right |
| 035_api_tokens.sql | The `api_tokens` table for access tokens (id, account, name, scope, keyed hash of the secret, dates). Safe to run twice. Needs the table owner and no superuser right |
| 038_service_accounts.sql | `users.is_service` and `api_tokens.created_by`, for service accounts that cannot sign in and own API tokens. Safe to run twice. Needs the table owner and no superuser right |

All scripts use `IF NOT EXISTS` / `IF EXISTS` guards and are safe to re-run. Migrations 013, 016, 017, 019, 022, 023, 024 and 025 are conditional and set `lock_timeout` to 5 seconds. Before this round 016, 019 and 022 ran `CREATE INDEX IF NOT EXISTS` or `ALTER TABLE ... IF NOT EXISTS` unconditionally, which takes a lock even when nothing changes and 022 had no timeout, so it waited behind a reader of `users` and a sign-in query queued behind it timed out. 023 gained the timeout only. 018 is a no-op. Migrations 013 and 017 read the catalogue and change a foreign key only when its delete rule is not SET NULL, so a deploy that runs them again takes no lock. They set `lock_timeout` to 5 seconds, so a change that has to wait for a busy table fails the deploy with a clear error instead of queueing every other statement behind it. If that happens, run the file again when the table is quiet. They use a temporary function and no psql meta commands.

Run manually on the live DB container:

```bash
docker exec phaemos-db-1 psql -U postgres -d phaemos -f /path/to/migration.sql
```

Or use `make migrate`, which applies every file in order.

Migration 011 uses `CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction block. `make migrate` and `deploy.sh` pipe each file to psql without `--single-transaction`, so it works there. Do not wrap the file in `BEGIN` and `COMMIT` or run it with `psql -1`. The file also uses psql's `\gexec`, so it must go through `psql` and not another client.

Migration 012 has no `CONCURRENTLY` and no psql meta commands, so it runs through `psql` on stdin and inside a single transaction alike. Existing devices start with `link_state` set to `offline`. The liveness sweep corrects each one within about 15 seconds of the API starting and a device's next post sets it to `online` at once. Existing alerts become `machine` alerts. The ORM models describe the same columns, so a fresh test database made by `create_all` matches a migrated one.

The new index starts with `device_id`, so the single-column `idx_telemetry_device_id` from 001 is now a redundant prefix of it. It is kept for now because dropping it is a separate decision that needs a look at the query plans first.

## A migration that has been applied is never edited

`infra/scripts/migrate.sh` (the Makefile's `migrate` target and the deploy script both use it) applies each file once and records it in `public.schema_migrations` with a hash of the file. A file that was applied and then edited is refused. So a migration that has been applied anywhere is never changed: a fix goes in a new numbered file. The one exception is `020_open_alert_unique.sql`, edited because nothing was deployed: its collapse and its index now leave rule alerts alone (`kind <> 'rule'`), which 029 gives their own per-rule uniqueness. It closed a real rule alert on old data before. A developer database that already ran the old 020 runs `bash infra/scripts/migrate.sh --rehash 020_open_alert_unique.sql`. Migrations 028, 029, 031, 036 and 037 apply cleanly after the new 020 on a database that has run the old one and on a second pass. The open-alert indexes it leaves match the model's (`uq_alerts_open_system` and `uq_alerts_open_rule`).
