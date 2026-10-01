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

Without Make, `docker compose up --build` starts the whole stack. The root `docker-compose.yml` includes
`infra/docker-compose.yml`, so it works from the repository root.

## Run without Docker

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate      # macOS and Linux
venv\Scripts\activate         # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
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
| `make test` | The backend pytest suite inside the backend container |
| `make lint` | Ruff on the backend and ESLint on the dashboard |
| `make build` | A production build of the dashboard |
| `make migrate` | The initial SQL schema against the running database |
| `make seed` | Demo data, useful after `docker compose down` wipes the volume |
| `make docs` | This documentation site, served locally with live reload |

The SDK, the CLI and the edge gateway each have their own checks, listed in
[client/README.md](https://github.com/phaemos/phaemos/blob/main/client/README.md) and [edge/README.md](https://github.com/phaemos/phaemos/blob/main/edge/README.md). CI runs every one of them on
each pull request.
