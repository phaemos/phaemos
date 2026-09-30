# Monitoring

Grafana and Prometheus configuration for the PHAEMOS observability stack.

| Folder | Purpose |
|---|---|
| [grafana/](grafana/) | Grafana dashboard and datasource provisioning |
| [prometheus/](prometheus/) | Prometheus scrape config |

Start with, from the repository root: `docker compose -f infra/docker-compose.yml -f infra/monitoring/docker-compose.monitoring.yml up -d`
Grafana: http://localhost:3001 (admin / admin on first login)
Prometheus: http://localhost:9090
