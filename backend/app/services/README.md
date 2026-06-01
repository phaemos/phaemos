# Services

Business logic shared across route handlers.

| File | Purpose |
|---|---|
| alert_service.py | Evaluates alert rules on every telemetry ingest |
| audit_service.py | Writes audit log entries (raw SQL, independent of ORM) |
| ml_service.py | Loads IsolationForest model, scores each reading |
| notify_service.py | Discord and SMTP notification dispatch |
| ws_manager.py | WebSocket connection registry and broadcast |
