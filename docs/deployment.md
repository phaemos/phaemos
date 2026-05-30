# Deployment Guide

This guide covers deploying Phaemos to Render (backend), Vercel (frontend), and via Docker for self-hosted setups.

---

## Section 1: Backend on Render

Render is the recommended platform for the Phaemos backend. It provides managed PostgreSQL, automatic deploys, and a free tier suitable for development.

### Steps

1. Go to [render.com](https://render.com) and sign in with your GitHub account.
2. Click **New** -> **Web Service** and connect your GitHub repository.
3. Set the **Root Directory** to `backend/`.
4. Set the **Runtime** to Python 3.
5. Set the **Build Command** to:
   ```
   pip install -r requirements.txt
   ```
6. Set the **Start Command** to:
   ```
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
7. Under **Environment Variables**, add all variables from `backend/.env.example`. At minimum:
   - `DATABASE_URL` - will be set automatically when you attach a Render Postgres database
   - `SECRET_KEY` - a long random string for JWT signing
   - `ALGORITHM` - `HS256`
   - `ACCESS_TOKEN_EXPIRE_MINUTES` - `30`
   - `REDIS_URL` - set after adding a Redis instance
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` - optional, for email alerts
   - `DISCORD_WEBHOOK_URL` - optional, for Discord alerts
8. Click **Add Database** -> **PostgreSQL** to create a managed Postgres instance. Render will automatically inject `DATABASE_URL` into your environment.
9. After the first deploy completes, open the Render Shell for your service and run migrations:
   ```
   psql $DATABASE_URL < migrations/001_initial_schema.sql
   ```
10. Your backend URL will be `https://your-service-name.onrender.com`. The health endpoint is `GET /health`.

---

## Section 2: Frontend on Vercel

Vercel is the recommended platform for the Next.js frontend.

### Steps

1. Go to [vercel.com](https://vercel.com) and sign in with your GitHub account.
2. Click **Add New Project** and import your GitHub repository.
3. Set the **Framework Preset** to **Next.js** (Vercel usually detects this automatically).
4. Set the **Root Directory** to `frontend/`.
5. Under **Environment Variables**, add:
   - `NEXT_PUBLIC_API_URL` - set this to your Render backend URL, for example `https://phaemos-backend.onrender.com`
6. Click **Deploy**.
7. Vercel will build and deploy the frontend. Your frontend URL will be `https://your-project.vercel.app`.

For a custom domain, go to **Project Settings** -> **Domains** in the Vercel dashboard and add your domain.

---

## Section 3: Docker (Self-Hosted)

For running Phaemos on your own server or locally without cloud services, use Docker Compose.

### Start all services

```bash
docker-compose up -d
```

This starts:
- `backend` - FastAPI application on port 8000
- `postgres` - PostgreSQL database on port 5432
- `redis` - Redis cache on port 6379
- `frontend` - Next.js application on port 3000

### Run database migrations

After the first start, run migrations inside the backend container:

```bash
docker-compose exec backend psql $DATABASE_URL < migrations/001_initial_schema.sql
```

Or using the Postgres container directly:

```bash
docker-compose exec postgres psql -U postgres -d phaemos < migrations/001_initial_schema.sql
```

### Check logs

To tail logs for the backend service:

```bash
docker-compose logs -f backend
```

To tail all services:

```bash
docker-compose logs -f
```

### Stop all services

```bash
docker-compose down
```

To also remove database volumes (destroys all data):

```bash
docker-compose down -v
```

---

## Section 4: Updating After a New PR Merges to Main

### Render (backend)

Render can be configured to automatically deploy whenever a push is made to the `main` branch. To enable this:

1. Go to your Web Service in the Render dashboard.
2. Under **Settings** -> **Build and Deploy**, enable **Auto-Deploy**.
3. Select the branch as `main`.

After each automatic deploy, check the deploy logs in the Render dashboard to confirm the build succeeded. If the PR includes database schema changes, you must manually run the new migration SQL file in the Render shell:

```bash
psql $DATABASE_URL < migrations/002_your_migration.sql
```

Render does not run migrations automatically.

### Vercel (frontend)

Vercel automatically deploys on every push to `main` with no additional configuration required. The deploy status appears in the Vercel dashboard and as a commit status check in GitHub.

### Database migrations

Schema migrations are not applied automatically on either Render or Vercel. After any PR that modifies `migrations/*.sql`:

1. Connect to the Render shell for the backend service.
2. Run the new migration file: `psql $DATABASE_URL < migrations/NNN_description.sql`
3. Verify the migration succeeded by checking the table structure.

Keep migration files numbered sequentially (`001_`, `002_`, ...) and never modify an already-deployed migration file. Always write new migration files for schema changes.
