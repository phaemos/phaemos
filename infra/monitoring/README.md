# Monitoring

Grafana and Prometheus configuration for the PHAEMOS observability stack.

| Folder | Purpose |
|---|---|
| [grafana/](grafana/) | Grafana dashboard and datasource provisioning |
| [prometheus/](prometheus/) | Prometheus scrape config |

Start with, from the repository root: `docker compose -f infra/docker-compose.yml -f infra/monitoring/docker-compose.monitoring.yml up -d`
Grafana: http://localhost:3001 (user `admin`, password from `GRAFANA_ADMIN_PASSWORD` in the `.env` file at the repository root, which git ignores. The stack does not start without it. The password is read only when Grafana first creates its data volume: to change it later use the Grafana user page.)
Prometheus: http://localhost:9090
