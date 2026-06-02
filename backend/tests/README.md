# Tests

pytest test suite. Uses a real PostgreSQL test DB (not mocks).

| File | Coverage |
| --- | --- |
| conftest.py | Fixtures - test DB setup, admin user, auth headers, device |
| test_auth.py | Register, login, /me, JWT validation |
| test_telemetry.py | Ingest, history, latest, export, v2 sensor fields |
| test_alerts.py | List alerts, resolve, alert rules |
| test_ml.py | ML score endpoint, retrain admin guard, retrain cooldown |
| test_devices.py | list_devices role filter (admin/viewer/technician), auth guard, owner_id in response |

Run: `cd backend && pytest` (requires DB running via docker compose)
