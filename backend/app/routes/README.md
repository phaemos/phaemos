# Route Handlers

One file per API domain. All routers are registered in main.py.

| File | Prefix | Description |
|---|---|---|
| auth.py | /api/v1/auth | Register, login, /me, /users (admin) |
| devices.py | /api/v1/devices | Device CRUD, API key management |
| telemetry.py | /api/v1/telemetry | Ingest, history, export CSV |
| alerts.py | /api/v1 | Alert history, resolve, alert rules CRUD |
| tickets.py | /api/v1/tickets | Maintenance ticket CRUD |
| audit.py | /api/v1 | GET /audit-logs (admin only) |
| firmware.py | /api/v1 | OTA firmware upload and download |
| ml.py | /api/v1/ml | Anomaly score endpoint, anomaly history |
| demo.py | /api/v1 | Demo mode start/stop with simulated data |
| ws.py | /ws | WebSocket real-time telemetry push |
