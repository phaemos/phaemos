# Development

How to run PHAEMOS locally, test it and work on each component. The quickstart in the main README covers
the shortest path; this page covers the rest.

## Prerequisites

- Docker and Docker Compose
- Node.js 18 or later
- Python 3.11 or later
- For the edge gateway: a Rust toolchain. For the CLI: Go.

## Run with Docker

```bash
cp .env.example .env
make dev
```

`make dev` starts PostgreSQL, Redis and the backend in Docker, then runs the dashboard with `npm run dev`.

| Service | Address |
| --- | --- |
| Dashboard | `http://localhost:3000` |
| API | `http://localhost:8000` |
| Interactive API docs | `http://localhost:8000/docs` |

> [!WARNING]
> `docker compose down -v` deletes the database volume along with the containers. Plain `docker compose down` and `docker compose stop` keep your data. After a wipe, `make migrate` and `make seed` rebuild it.

Without Make, `docker compose up --build` starts the whole stack. The root `docker-compose.yml` includes
`infra/docker-compose.yml`, so it works from the repository root.

The dashboard image is built from the repository root and the development compose file passes `LEGAL_PLACEHOLDERS=allow` to it, so a legal page that still holds a placeholder does not stop `docker compose up --build`. A production image is built without that value and stops while a placeholder is open: `docker build -f frontend/Dockerfile -t phaemos-frontend .`. Set `LEGAL_PLACEHOLDERS=fail` in your shell to make the compose build strict as well.

## Sign in for the first time

The dashboard has no sign-up page. In development registration is open, so register an account through the API.
Passwords need at least eight characters with an uppercase letter and a digit:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"name": "Your Name", "email": "you@example.com", "password": "Change-Me-123"}'
```

Every new account is a viewer. A viewer cannot change anything. Promote your first account once in the
database:

```bash
docker compose exec -T db psql -U postgres -d phaemos \
  -c "UPDATE users SET role = 'admin' WHERE email = 'you@example.com'"
```

Or skip both steps and create an admin directly. The command asks for an email and a password (typed without echo)
and refuses an email that already has an account:

```bash
docker compose exec backend python -m app.scripts.create_admin
```

Registration is open only when `ENVIRONMENT=development`. Set `REGISTRATION_OPEN=false` in `backend/.env` to try the
closed behaviour locally, where `POST /api/v1/auth/register` answers `403`.

Sign in at `http://localhost:3000/login`. The Admin page now lists users, alert rules, maintenance windows,
webhooks and the audit log.

Devices are registered through the API too and need an admin account. `POST /api/v1/devices` with an admin's
bearer token from `POST /api/v1/auth/login` returns the device and its `api_key`, which is shown once. Pass that key to
`phaemos-sim` as described below and the readings appear on the device page.

## Run without Docker

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate      # macOS and Linux
venv\Scripts\activate         # Windows
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --no-access-log --ws-max-size 8192 --ws-per-message-deflate false
```

The backend still needs PostgreSQL and Redis. Point `DATABASE_URL` and `REDIS_URL` in `.env` at your own
instances. To run just those two in Docker instead, use `docker compose up db redis -d`.

### Dashboard

```bash
cd frontend
npm install
npm run dev
```

## Quick API smoke test

This checks the core backend flows without any hardware. Start the backend, then in a second terminal:

```bash
cd backend
python scripts/quick_api_smoke.py
```

It covers:

- registering and logging in
- registering a device
- posting telemetry with the generated device API key
- reading the latest telemetry back
- the ML score endpoint

## Simulating machines

The Python simulator in `client/python` produces readings for any of the four node types and can inject
faults, so the dashboard, alerts and anomaly scoring can be exercised on a laptop.

```bash
pip install -e client/python
phaemos-sim --node esp32 --count 5 --dry-run
phaemos-sim --node esp32 --fault bearing --count 60 --interval 1 --api-key <device key>
```

`--dry-run` prints readings instead of posting them. With `--api-key` the readings go to the API at
`--api-url`, which defaults to `http://localhost:8000`. See [client/README.md](https://github.com/phaemos/phaemos/blob/main/client/README.md) for every
option and for the Go CLI.

## Tests and linting

| Command | What it runs |
| --- | --- |
| `make test` | The backend pytest suite inside the backend container, against its own `phaemos_test` database that the target creates on first use |
| `make lint` | Ruff on the backend and ESLint on the dashboard |
| `npm test` in `frontend/` | The dashboard unit tests, through the Node test runner (Node 22.18 or later) |
| `make build` | A production build of the dashboard |
| `make migrate` | The initial SQL schema against the running database |
| `make seed` | Demo data, useful after `docker compose down -v` wipes the volume |
| `make docs` | This documentation site, served locally with live reload |

The suite drops every table when it finishes, so `conftest.py` refuses to start unless the database name in
`DATABASE_URL` ends in `_test`. The name check runs before the application is imported, so a database
with any other name is never opened.

The SDK, the CLI and the edge gateway each have their own checks, listed in
[client/README.md](https://github.com/phaemos/phaemos/blob/main/client/README.md) and [edge/README.md](https://github.com/phaemos/phaemos/blob/main/edge/README.md). CI runs every one of them on
each pull request.
