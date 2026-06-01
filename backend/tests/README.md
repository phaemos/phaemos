# Tests

pytest test suite. Uses a real PostgreSQL test DB (not mocks).

| File | Coverage |
|---|---|
| conftest.py | Fixtures - test DB setup, admin user, auth headers, device |
| test_auth.py | Register, login, /me, JWT validation |
| test_telemetry.py | Ingest, history, latest, export |
| test_alerts.py | List alerts, resolve, alert rules |
| test_ml.py | ML score endpoint |

Run: `cd backend && pytest` (requires DB running via docker compose)
