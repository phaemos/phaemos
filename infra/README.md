# Infra

The PHAEMOS runtime stack: Docker Compose for development and for the production droplet, the Nginx site, the server scripts, the Prometheus and Grafana monitoring overlay and the SQL used for reporting and demo data.

> [!NOTE]
> This folder is published to [phaemos/infra](https://github.com/phaemos/infra) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

| Path | Contents |
|---|---|
| `docker-compose.yml` | The development stack: PostgreSQL 15, Redis 7, the FastAPI backend and the Next.js dashboard |
| `docker-compose.prod.yml` | The production stack for one small droplet: database, Redis and backend only. Images pinned by digest, every container with all capabilities dropped, a read-only root, process, memory and CPU limits, a Redis password and a limited database login for the API |
| `nginx/api.phaemos.com.conf` | The complete Nginx site for the API: TLS, HSTS, request and body limits, slow-client timers and the refusal of unknown host names. Certbot only issues the certificate |
| `logrotate/phaemos-nginx` | The log rotation rule that keeps the Nginx logs for 14 days, installed to `/etc/logrotate.d/nginx` |
| `scripts/` | `harden.sh`, `install.sh`, `deploy.sh`, `backup.sh`, `restore.sh`, `db-role.sh` and `check-nginx.sh` for the droplet and `lib.sh` which they share |
| `sql/roles/` | The SQL that makes the API's limited database login and the check of it |
| `monitoring/` | Prometheus scrape config and Grafana provisioning, started as an overlay |
| `sql/queries/` | Reporting queries: anomaly report, device summary, telemetry export |
| `sql/seed/` | Demo devices for a fresh database |

## Running the stack in development

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

## Production

Production runs `docker-compose.prod.yml` and never the development file. Every setting comes from `backend/.env`. A missing required value stops the start. The full steps are in the [deployment guide](https://github.com/phaemos/phaemos/blob/main/docs/deployment.md). In short, on a fresh Ubuntu 24.04 droplet:

```bash
# as root, after verifying the release tag with a command that is not in the checkout (the guide, Section 2)
DEPLOY_SUDO=full bash infra/scripts/harden.sh   # deploy user, SSH keys and named users only, ufw, fail2ban, swap
DEPLOY_USER=deploy bash infra/scripts/install.sh  # Docker Engine, Nginx, Certbot, age (run as root, not through sudo from a root shell)
# as the deploy user, from a verified and checked out tag
bash infra/scripts/deploy.sh         # a signed tag only: build, make the API login, apply the migrations once each, check /status and Nginx
bash infra/scripts/backup.sh         # encrypted dump (age), keeps the newest seven, optional off-server copy
bash infra/scripts/restore.sh FILE KEY   # inside tmux: decrypts with the key file you give and loads it in one transaction after a typed confirmation
```

The scripts need a full `phaemos/phaemos` checkout, not this read-only copy, because they build the backend and read `backend/.env`. They print no secret and are safe to run twice. The API is published on `127.0.0.1:8000` only and Nginx faces the internet. Nginx reaches the API through the Docker network gateway, so the compose file pins the `edge` network to `172.29.0.0/24` with the gateway `172.29.0.1` (the database and Redis sit on a second, internal network that has no route out) and trusts only that address for `X-Real-IP`. The memory limits add up to 704 MiB so the 1 GB droplet keeps room for the system.

The development stack reads its signing key from `infra/.env.dev`, which `make dev` (or `make dev-key`) creates with a random value on the first run. The file is ignored by git.

### Refreshing the pinned images

The production file pins `postgres:15` and `redis:7-alpine` by tag and digest. To move to a newer build of the same tag: `docker pull postgres:15`, then `docker image inspect postgres:15 --format '{{index .RepoDigests 0}}'` and put the printed `postgres@sha256:...` digest after the tag in `docker-compose.prod.yml`. Do the same for Redis. Run the stack on a copy first, then deploy from a signed tag. `docker buildx imagetools inspect postgres:15` prints the current digest without pulling.

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
