# Services

Business logic shared across route handlers.

| File | Purpose |
|---|---|
| access.py | Who may read and who may change a machine, shared by every route that touches machine data |
| alert_service.py | Evaluates alert rules on every telemetry ingest and queues email, SMS, Discord and webhooks with an hourly window each. Holds the helper that sends a monitoring alert as an email warning |
| audit_service.py | Writes audit log entries (raw SQL, independent of ORM) |
| ml_service.py | Trains and serves the anomaly models: an Isolation Forest and a per-sensor baseline and a sequential change detector per machine (24 machines at most) and per node type and one general model, each with a boundary measured on held-out healthy readings and an alert-rate and fault-detection check before use. Scores a reading only when every feature its model needs is present, signs the model file with an HMAC and refuses one that is unsigned or outside the model folder, keeps a `.prev` fallback and reports each machine's model state |
| sensor_map.py | Which telemetry fields each sensor and serial link produces, the fault states a node may report, their plain words and the cleaning of a `faults` object |
| keyset.py | Keyset paging: the `before=<time>,<id>` cursor, reading it and the `X-Next-Before` header |
| idempotency.py | `Idempotency-Key` for the creates that would double on a retry: kept 24 hours per account and route, the stored answer encrypted, the same key with another body refused |
| deprecation.py | The `Deprecation`, `Sunset` and `Link` headers of a route kept as an alias for one release |
| maintenance_service.py | Whether a machine is inside a maintenance window (moved out of the route file so services do not import routes) |
| webhook_secrets.py | A webhook's signing secret, encrypted at rest under its own derived key |
| ingest_limit.py | The per-device allowances: 60 single posts a minute, 1,200 batched readings a minute (6,000 for the site) and the firmware routes per device |
| device_keys.py | How device keys are made, stored and checked: a keyed hash (HMAC-SHA256 under a sub-key of `SECRET_KEY`), lookup by the first 8 characters, a constant-time compare with the same cost for an unknown key and the start-up upgrade of keys still held in clear |
| replay.py | The replay judgement for a post: accept, duplicate (the exact last pair), old or missing pair and the counters it keeps on the device |
| stuck_sensors.py | The stuck sensor check: a table of columns with the period and resolution each needs and the reason, the rules that keep it from nagging and the state it keeps per column |
| csv_safe.py | Makes a text cell safe to open in a spreadsheet (a leading = + - @ tab or carriage return gets a quote) |
| health_service.py | Ingest side of node health: stops the sensors a node claims are faulted only while an alert backs the claim, finds the faults the server sees for itself (an impossible value, a stuck value), stores the latest vitals and links, counts lost posts and restarts, runs the sensor fault alerts and the no-scored-reading alert, raises the restart-loop alert and lists the rules that cannot be evaluated |
| liveness_service.py | The sweep that sets each device's link state, opens and resolves the silent-node alert, with a Redis lock and a start-up grace |
| cooldown.py | Repeat windows and daily caps for notifications (Redis, with a process-memory fallback that also takes over for 30 seconds after one failed Redis call) |
| email_service.py | The one email path: every message goes through Resend |
| notify_service.py | Discord and alert email dispatch. Discord returns whether it was accepted, so a failed send frees its window |
| telemetry_buckets.py | SQL time-bucketing for long telemetry ranges: aggregate per column, bounds and bucket cap |
| sms_service.py | Critical alert texts through Brevo |
| notify_pool.py | The small pool of threads that make vendor calls, with a bounded queue, critical jobs first and never dropped |
| alert_state.py | The per-device lock and the guarded insert every system alert uses, refusing only a second open alert |
| rule_metrics.py | The readings an alert rule may watch, the conditions and the severities, in one place |
| webhook_service.py | Delivers alerts to the configured webhooks (Slack, Discord, Teams) from plain copies of the rows, so it can run after the request |
| ws_manager.py | WebSocket connection registry and broadcast |
