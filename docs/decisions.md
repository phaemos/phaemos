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
