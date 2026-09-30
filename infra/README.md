# Infra

The PHAEMOS runtime stack: Docker Compose for the database, cache, backend and dashboard, the Prometheus and Grafana monitoring overlay and the SQL used for reporting and demo data.

> [!NOTE]
> This folder is published to [phaemos/infra](https://github.com/phaemos/infra) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

| Path | Contents |
|---|---|
| `docker-compose.yml` | PostgreSQL 15, Redis 7, the FastAPI backend and the Next.js dashboard |
| `monitoring/` | Prometheus scrape config and Grafana provisioning, started as an overlay |
| `sql/queries/` | Reporting queries: anomaly report, device summary, telemetry export |
| `sql/seed/` | Demo devices for a fresh database |

## Running the stack

From the root of a `phaemos/phaemos` checkout:

```bash
docker compose up --build
```

The root `docker-compose.yml` includes this folder's stack, so the Makefile targets (`make dev`, `make test`, `make seed`) work unchanged. The Compose project name is pinned to `phaemos`, so containers keep names like `phaemos-db-1`.

With monitoring:

```bash
docker compose -f infra/docker-compose.yml -f infra/monitoring/docker-compose.monitoring.yml up -d
```

> [!IMPORTANT]
> The stack builds the backend and dashboard from `../backend` and `../frontend`. It needs a full `phaemos/phaemos` checkout. A copy of this repository on its own can run the monitoring overlay and the SQL, but not build the application images.

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
