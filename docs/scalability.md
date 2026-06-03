# Scalability

Phaemos is deployed as a single Docker Compose stack on one VPS. This document describes when and how to scale each layer as device count or user load grows.

---

## Current baseline

| Layer | Current setup | Practical limit |
| --- | --- | --- |
| Backend | 1 FastAPI process, Uvicorn, 1 VPS | ~500 concurrent WebSocket connections, ~2,000 req/min |
| Database | PostgreSQL 15, single container | ~100 concurrent connections before lock contention |
| Cache | Redis 7, single container | Single point of failure; fine up to ~10,000 ops/sec |
| Frontend | Vercel (auto-scales) | No limit at current pricing tier |
| Telemetry ingest | One backend process handling all POSTs | ~200 devices posting every 5 seconds |

---

## Scaling signals

Scale when you observe any of the following:

- `docker stats` shows the backend container consistently above 80% CPU
- Postgres `pg_stat_activity` shows more than 80 active connections
- Telemetry ingest latency climbs above 500ms (check via the `/health` response time)
- Redis memory usage above 75% of available RAM
- More than ~500 concurrent dashboard users

---

## Stage 1: Vertical scaling (cheapest first)

Before splitting services, upgrade the VPS:

- CX21 (1 vCPU / 2 GB) -> CX31 (2 vCPU / 8 GB) at ~$12/month
- This doubles Postgres connection capacity and gives the backend room to handle more concurrent requests
- No code changes required

---

## Stage 2: Horizontal backend scaling

Run multiple FastAPI workers behind an Nginx upstream.

### Option A: Multiple workers on one machine (simplest)

Change the Uvicorn start command to use multiple workers:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

This runs 4 processes sharing the same port. Each process has its own in-memory APScheduler instance - the daily retention job will run 4 times. Guard against this by checking if the process is the primary worker, or migrate background tasks to Celery (see Stage 4).

### Option B: Multiple machines with a load balancer

Add a second VPS and configure Nginx to round-robin between them:

```nginx
upstream phaemos_backend {
    server backend-1:8000;
    server backend-2:8000;
}

server {
    listen 443 ssl;
    server_name api.phaemos.com;

    location / {
        proxy_pass http://phaemos_backend;
    }
}
```

Requirements for multiple machines:

- Session state must be in Redis (already the case for rate limiting)
- The ML model file (`backend/ml/model.pkl`) must be on shared storage (NFS or S3) or each machine must reload from the database
- Background tasks must not run on multiple workers simultaneously - migrate to Celery

---

## Stage 3: Database scaling

### Connection pooling (first step)

Add PgBouncer between the backend and Postgres. PgBouncer multiplexes many application connections into a smaller pool of real Postgres connections:

```yaml
# docker-compose.yml addition
pgbouncer:
  image: pgbouncer/pgbouncer:latest
  environment:
    DATABASES_HOST: postgres
    DATABASES_PORT: 5432
    DATABASES_DBNAME: phaemos
    PGBOUNCER_POOL_MODE: transaction
    PGBOUNCER_MAX_CLIENT_CONN: 500
    PGBOUNCER_DEFAULT_POOL_SIZE: 20
```

Point `DATABASE_URL` at PgBouncer (port 6432) instead of Postgres directly.

### Read replicas

PostgreSQL streaming replication adds one or more read replicas. Direct read-heavy queries (telemetry history, exports, ML training data) to the replica:

```python
# I use a separate read-only engine for queries that don't need the primary.
read_engine = create_engine(settings.database_url_replica)
```

The primary handles all writes. The replica handles `GET /telemetry`, exports, and ML training data fetches.

### Managed Postgres (when self-hosted becomes a burden)

The SQLAlchemy ORM means migrating to a managed service is a one-line `DATABASE_URL` swap:

```
DATABASE_URL=postgresql://user:pass@db.neon.tech/phaemos?sslmode=require
```

Recommended providers:

- **Neon** - serverless Postgres, free tier, autoscales, branching for staging
- **Supabase** - Postgres + realtime + auth, free tier
- **DigitalOcean Managed Postgres** - same cloud as the VPS, low latency

---

## Stage 4: Redis high availability

The current single Redis container is a single point of failure. If it restarts, all rate-limit counters and session data are lost.

### Redis Sentinel (recommended for single-VPS HA)

Redis Sentinel runs a primary and two replicas. If the primary fails, Sentinel automatically promotes a replica:

```yaml
# docker-compose.yml addition
redis-primary:
  image: redis:7
  command: redis-server --appendonly yes

redis-replica:
  image: redis:7
  command: redis-server --replicaof redis-primary 6379

redis-sentinel:
  image: redis:7
  command: redis-sentinel /etc/redis/sentinel.conf
```

### Redis Cluster (for horizontal scaling)

Redis Cluster shards data across multiple nodes. Use this when Redis memory becomes the bottleneck (storing millions of telemetry readings in-memory, for example).

---

## Stage 5: Background tasks - migrate to Celery

The current APScheduler runs inside the FastAPI process. With multiple workers this causes duplicate job runs. Migrate to Celery when running more than one worker:

```python
# Current (APScheduler)
scheduler.add_job(run_retention, 'cron', hour=2)

# Celery equivalent
@celery_app.task
def run_retention():
    ...

celery_app.conf.beat_schedule = {
    'retention': {
        'task': 'app.tasks.run_retention',
        'schedule': crontab(hour=2),
    }
}
```

Celery uses Redis as its broker (already in the stack). The upgrade adds one `celery worker` container and one `celery beat` container to `docker-compose.yml`.

---

## Stage 6: CDN and edge caching

The Next.js frontend on Vercel is already served from Vercel's global edge network. No action needed for the frontend.

For the API, if telemetry read endpoints are called frequently by many users viewing the same device, add a short-lived cache header:

```python
# I cache public-safe telemetry reads for 5 seconds to reduce DB load at scale.
response.headers["Cache-Control"] = "public, max-age=5"
```

Do not cache authenticated endpoints or anything that writes state.

---

## Upgrade path summary

| When | Action |
| --- | --- |
| CPU > 80% sustained | Upgrade VPS (Stage 1) |
| >80 DB connections | Add PgBouncer (Stage 3) |
| >1 backend worker needed | Migrate to Celery (Stage 4/5) |
| Redis is a SPOF concern | Add Sentinel (Stage 4) |
| Self-hosted DB is a burden | Migrate to Neon/Supabase (Stage 3) |
| >500 concurrent users | Multiple backend machines + load balancer (Stage 2B) |
