# Decision Log

A record of key architectural and technical decisions made during development.

---

## 001 - Use Isolation Forest for anomaly detection (not supervised learning)

**Date:** 2026-04-23
**Status:** Accepted

**Context:**
The system starts with no labeled fault data. We cannot use a supervised classifier (e.g. Random Forest, SVM) without a dataset of labeled normal/fault readings.

**Decision:**
Use Isolation Forest from scikit-learn. It is an unsupervised algorithm that learns what "normal" looks like and flags readings that deviate from it.

**Consequences:**

- Can train immediately once 1-2 weeks of normal data is collected
- No manual labeling required
- Phase 3 upgrade path: LSTM on labeled historical data once faults have been observed and logged

---

## 002 - Device authentication via API key, not JWT

**Date:** 2026-04-23
**Status:** Accepted

**Context:**
ESP32 firmware cannot easily manage JWT refresh cycles. JWTs expire and require re-authentication logic that is complex to implement reliably on embedded hardware.

**Decision:**
Devices authenticate using a static `X-API-Key` header. Keys are generated on device registration and stored hashed in the database.

**Consequences:**

- Simple firmware implementation - set once in config.h
- API keys are long-lived - rotation must be done manually via admin panel
- Keys should be kept out of firmware binaries in production (use NVS on ESP32)

---

## 003 - Monorepo structure (firmware + backend + frontend in one repo)

**Date:** 2026-04-23
**Status:** Accepted

**Context:**
Three layers (firmware, backend, frontend) could each be separate repos. For a portfolio project, monorepo makes it easier to demonstrate the full system in one place.

**Decision:**
Single GitHub repo with `firmware/`, `backend/`, `frontend/` directories.

**Consequences:**

- Simpler for reviewers to navigate
- Docker Compose at root ties all services together
- Each layer still has its own Dockerfile and can be deployed independently

---

## 004 - Poll-based frontend updates (not WebSocket)

**Date:** 2026-04-23
**Status:** Accepted

**Context:**
Real-time WebSocket connections would give instant dashboard updates but add complexity to the backend and deployment.

**Decision:**
Frontend polls `GET /api/v1/telemetry/{device_id}/latest` every 5 seconds. Sensors post every 5 seconds, so polling interval matches ingest rate.

**Consequences:**

- Simpler to implement and deploy
- 5-second polling is acceptable given the 5-second sensor cycle
- Phase 3 upgrade: replace with Server-Sent Events or WebSocket if lower latency is needed

---

## 005 - PostgreSQL over SQLite for development

**Date:** 2026-04-23
**Status:** Accepted

**Context:**
SQLite would be simpler for local development but would require schema changes when deploying to Render/PostgreSQL.

**Decision:**
Use PostgreSQL locally via Docker Compose from Day 1. Same database in dev and production.

**Consequences:**

- Dev/prod parity from the start
- Requires Docker running locally
- UUID primary keys, `gen_random_uuid()` and `TIMESTAMP` types all behave the same in both environments

---

## 006 - APScheduler (in-process) over Celery for background tasks

**Date:** 2026-06-01
**Status:** Accepted

**Context:**
The project needs two background tasks: demo mode telemetry generation (every 5 seconds) and telemetry data retention (daily at 02:00 UTC). Celery would be the production-grade choice but requires a Redis broker and separate worker process.

**Decision:**
Use APScheduler's BackgroundScheduler running in a daemon thread inside the same FastAPI process. Both tasks use their own SQLAlchemy sessions rather than the request-scoped Depends(get_db) session.

**Consequences:**

- Zero extra infrastructure (no Celery worker, no separate broker config)
- Tasks are lost if the process crashes mid-run (acceptable for demo and retention)
- Cannot distribute tasks across workers - one instance runs each job (fine for single-instance Render deployment)
- Upgrade path: swap to Celery when horizontal scaling or task persistence is required

---

## 007 - StreamingResponse for CSV export (not pre-built file)

**Date:** 2026-06-01
**Status:** Accepted

**Context:**
Telemetry exports can be large. Loading all rows into a Python list before sending them would spike memory usage.

**Decision:**
Use FastAPI's `StreamingResponse` with an `io.StringIO` buffer and Python's `csv` stdlib. Rows are serialised in one pass and the buffer is iterated directly into the HTTP response.

**Consequences:**

- Memory usage is bounded regardless of result set size
- Buffered in `io.StringIO` rather than streamed row-by-row (acceptable for current scale; could switch to a generator per row for very large exports)

---

## 008 - TelemetryChart owns its own data fetch (not parent-controlled)

**Date:** 2026-06-01
**Status:** Accepted

**Context:**
The previous design passed `readings: Telemetry[]` as a prop. The chart now has its own time-range picker (1h/6h/24h/7d) which changes what data is fetched.

**Decision:**
Pass `deviceId: string` to TelemetryChart and let it own the `useTelemetry` call internally. The parent no longer manages the readings array.

**Consequences:**

- Time-range changes do not require the parent page to re-render
- The chart can be placed on any page (dashboard, compare, device detail) with one prop
- Slight duplication: device detail page also calls useTelemetry separately for the live sensor grid

---

## 009 - Tailwind class-based dark mode (not media query)

**Date:** 2026-06-01
**Status:** Accepted

**Context:**
The app is dark-only. Adding a light mode toggle was requested. Tailwind supports two dark mode strategies: `media` (follows OS setting) and `class` (controlled by a CSS class on `<html>`).

**Decision:**
Use `darkMode: 'class'` with a pre-hydration inline script in `<head>` that reads `localStorage` and applies the `dark` class before React mounts. This prevents a flash of the wrong theme.

**Consequences:**

- User preference overrides OS setting (intentional - dashboard use case needs explicit control)
- Inline script is `dangerouslySetInnerHTML` but is safe here as it contains no user input

---

## 010 - WebSocket JWT auth via query parameter (not header)

**Date:** 2026-06-01
**Status:** Accepted

**Context:**
The telemetry WebSocket endpoint needed authentication. The WebSocket handshake is a plain HTTP upgrade request, but browser WebSocket APIs do not allow setting custom headers (unlike fetch/XHR).

**Decision:**
Pass the JWT as a `?token=` query parameter. The server validates the token before calling `websocket.accept()` and closes with code 1008 (Policy Violation) on auth failure. The client must not retry on 1008 to avoid looping forever on an expired token.

**Consequences:**

- Token appears in server access logs. Acceptable for an internal maintenance tool where logs are admin-only
- The alternative (httpOnly cookie) does not work for cross-origin WebSocket connections in all browsers

---

## 011 - ML retrain as in-process background task (not a queue worker)

**Date:** 2026-06-02
**Status:** Accepted

**Context:**
The ML retrain endpoint needs to fit an IsolationForest on up to 10,000 rows. This takes a few seconds - too long to block the HTTP response. Several options exist: a Celery/RQ task queue, a subprocess, or FastAPI's built-in BackgroundTasks.

**Decision:**
Use FastAPI BackgroundTasks. The task runs in the same process after the 202 response is sent. A 1-hour in-memory cooldown prevents concurrent runs. The model is written to disk and the in-memory reference reloaded atomically via reload_model().

**Consequences:**

- No extra infrastructure (no Redis queue, no Celery worker). Acceptable for a single-worker deployment
- If the process dies mid-retrain, the old model.pkl remains intact so scoring continues with the previous model
- The cooldown resets on restart - this is acceptable; an admin can immediately trigger a retrain after a restart

---

## 012 - Pagination via skip/limit (not cursor-based)

**Date:** 2026-06-02
**Status:** Accepted

**Context:**
Tickets and devices pages needed pagination to avoid loading unbounded result sets. Two common approaches: offset/limit (simple) and cursor-based (consistent across concurrent mutations).

**Decision:**
Use `skip` and `limit` query params. The frontend uses page state and disables Next when fewer than `PAGE_SIZE` rows are returned, signalling the last page.

**Consequences:**

- Simpler to implement and reason about
- Page boundaries can shift if rows are inserted or deleted between requests. Acceptable for a maintenance tool where exact page consistency is not critical

---

## 013 - Self-hosted Docker Compose on a single VPS (not managed cloud services)

**Date:** 2026-06-02
**Status:** Accepted

**Context:**
Cloud-managed services (Supabase, Neon, Railway, PlanetScale) were evaluated as replacements for the self-hosted Postgres and Redis containers. The question was whether splitting the stack across multiple managed providers would reduce cost or operational burden.

**Decision:**
Keep the entire stack (Postgres, Redis, FastAPI, Next.js) in a single Docker Compose deployment on one Hetzner CX21 or DigitalOcean Basic Droplet (~$4-6/month). The GitHub Student Developer Pack provides $200 of DigitalOcean credit, covering approximately 33 months at $6/month - effectively free for the duration of a university degree.

Managed services are not needed because:

- Docker Compose already runs Postgres and Redis with zero extra cost
- Adding Supabase/Neon would introduce external network latency between services
- It would split the stack across multiple dashboards and connection strings with no benefit
- The free tiers of managed services have row/storage limits that would be hit once real device data accumulates

**Consequences:**

- Total production cost: $0/month while Student Pack credit lasts, then ~$6/month
- Frontend stays on Vercel free tier (separate from the VPS)
- One `docker compose up -d` on the VPS deploys the full backend stack
- Upgrade path: if the project scales beyond one box, extract Postgres to a managed service (Neon or Supabase) at that point - the SQLAlchemy ORM means the change is a one-line `DATABASE_URL` swap
