# Development Timeline

This document records the development history of PHAEMOS in chronological phases. The rigid week-by-week framing has been replaced with a phase-based structure that reflects how the work actually progressed.

---

## Phase 1 - Foundation (complete)

**Goal:** Get data flowing end-to-end, from firmware to dashboard.

- FastAPI project structure with all route stubs
- PostgreSQL schema (001_initial_schema.sql) - full v2 telemetry schema
- Next.js App Router setup with page stubs
- Docker Compose with backend, PostgreSQL, Redis and frontend containers
- ESP32 v2 firmware - all 11 sensors, OLED, buzzer, RGB LED, relay
- STM32 Black Pill firmware - MPU6050 at 100 Hz, FFT, UART to ESP32
- Arduino Nano firmware - BME280, LDR, FC-28, serial CSV to ESP32
- Pico W MicroPython firmware - BME280, LDR, OLED, direct Wi-Fi POST
- Telemetry POST endpoint accepting full v2 payload
- Isolation Forest training pipeline skeleton
- Live dashboard - device cards, telemetry chart, alert banners
- WebSocket real-time telemetry push with exponential backoff reconnect
- Device detail page - sensor grid, per-sensor time-range charts, CSV export
- Device comparison page - up to 3 side-by-side columns
- Prometheus + Grafana monitoring overlay

---

## Phase 2 - Operations (complete)

**Goal:** Alert management, ticket tracking, authentication and audit trail.

- Alert rules engine - threshold rules per device/metric, all v2 sensor fields
- Alert history and resolve actions
- Ticket CRUD with PHM-0001 ticket number format (SERIAL column, migration 004)
- JWT authentication - register, login, /me endpoint
- Role-based access control - admin / technician / viewer
- Audit logging on all mutating routes (audit_service.log_action)
- Brute-force lockout - 5 failed attempts = 15-minute lock (migration 002)
- Multi-tenant device ownership - nullable owner_id FK on devices (migration 003)
- ML anomaly scoring on every ingest, retrain endpoint with 1-hour cooldown
- Admin panel - user management, alert rules, OTA firmware upload, audit log
- Full light/dark mode across all components
- Login page with JWT cookie, Next.js edge middleware route guard, logout button
- Tickets and devices pages with Prev/Next pagination

---

## Phase 3 - Enterprise Features (complete)

**Goal:** Production-grade auth, notifications, maintenance workflows and GDPR compliance.

- OAuth backend - Google and GitHub OAuth2 via authlib, email-matched to prevent duplicate accounts (PR 92)
- 2FA TOTP backend - enable, confirm, verify, disable via pyotp (PR 93)
- User profile endpoints - PATCH /auth/me, change-password, DELETE /auth/me (GDPR anonymise), GET /auth/me/export (PR 94)
- Refresh token + logout - 15-minute access tokens, 7-day httpOnly refresh cookie (PR 89)
- All routes protected in auth hardening sweep (PR 88)
- Webhooks backend - Slack, Discord and Teams destinations, migration 006 (PR 95)
- Fleet health summary - GET /health/summary, GET /status public endpoint (PR 96)
- Maintenance windows backend - migration 007, suppress_alerts flag (PR 97)
- Device tags ARRAY + search/filter + batch firmware update - migration 008 (PR 98)
- RBAC permissions - migration 009, JSONB permissions column per user
- Invitation flow - signed JWT invite emails via Resend, accept-invite endpoints
- SMS critical alerts via Brevo API (optional, phone_number on users table)
- OAuth user columns added to users table - oauth_provider, oauth_id, phone_number, totp_secret, totp_enabled, permissions (migration 005)
- Axios refresh interceptor on frontend - auto-retries failed requests after token refresh
- Design system - typography, spacing, colour tokens
- Toast notification system - ToastProvider context
- Device search and tag filter on devices list
- Tab visibility pause - polling halts when browser tab is hidden
- Profile page - name/email/phone edit, change password, 2FA enrolment, GDPR export and delete

---

## Phase 4 - Hardening and Polish (complete)

**Goal:** Security hardening, rate limiting, frontend public pages, documentation site, open-source setup.

- Security headers - X-Frame-Options: DENY, X-Content-Type-Options: nosniff, Referrer-Policy, Permissions-Policy
- Rate limiting via slowapi - login (5/min), register (10/hr), password change (5/hr), contact (3/hr), ML retrain; X-Real-IP from Nginx proxy
- Input validation max_length on all string fields (device, ticket, webhook schemas)
- robots.txt and sitemap.xml
- Cookie consent banner - GDPR-compliant, GA4 loads only after accept
- Privacy policy and terms of service pages
- Health summary widget on dashboard
- Webhook management UI and maintenance windows UI in admin panel
- Device tags UI - chips on DeviceCard, inline editor on device detail, batch firmware modal
- About, blog, changelog, docs hub, status, FAQ, support, contact, security pages
- Vercel Analytics and GA4 (consent-gated)
- phaemos.io to phaemos.com domain sweep (PR 114)
- AGPL-3.0 LICENSE file and NOTICE (PR 123)
- CONTRIBUTING.md - branch prefixes, UK English, email alias table, AGPL statement (PR 124)
- Contact page with Cloudflare Turnstile verification (PR 125)
- CodeQL code scanning - Python + JavaScript, push/PR/weekly schedule (PR 127)
- Stale issue workflow - 60-day threshold, security/pinned/in-progress labels exempt (PR 127)
- MkDocs Material documentation site at docs.phaemos.com (PR 128)
- Deployment docs rewritten for DigitalOcean VPS + Nginx + SSL + Docker Compose (PR 129)
- Instatus status page at status.phaemos.com (PR 129)
- Scalability guide - six-stage upgrade path (PR 130)
- STM32 CMSIS-DSP FFT migration - arm_rfft_fast_f32, O(N log N), N=128, ~19 us on 96 MHz Cortex-M4F (PR 131)
- GitHub Discussions setup - four category templates, FAQ expanded to 17 questions in 6 sections (PR 132)
- CI postgres pull retry - replaced services block with explicit docker pull + retry loop (PR 134)

---

## Phase 5 - Hardware (PENDING - hardware-blocked)

**Goal:** Physical assembly, sensor validation, and real-data ML training.

These tasks require physical components on the bench. All firmware and backend code is ready; this phase begins when components arrive.

- Wire ESP32 with all 11 sensors on breadboard, validate I2C addresses
- Confirm serial readings from Arduino Nano in Arduino IDE Serial Monitor
- Test UART bridge from STM32 Black Pill to ESP32 at 115200 baud
- Verify Pico W posting BME280 data directly to the API over Wi-Fi
- Run all four nodes simultaneously and verify data appears in PostgreSQL
- STM32 FFT results visible in fft_peak_hz column in telemetry table
- Collect 24-48 hours of baseline sensor data from all four nodes
- Preprocess into feature vectors and train Isolation Forest model
- Evaluate on held-out normal and anomaly samples
- Validate anomaly scores appear correctly on the dashboard chart
- Begin Proteus ISIS schematic for ESP32 node (Phase 2 in original plan)
- Begin PCB layout in Proteus ARES
- Export Gerber files and order PCBs

---

## Notes

- Tasks in Phases 1-4 are complete and merged to `main`.
- Phase 5 tasks are hardware-blocked and will be updated as components arrive.
- The ML model currently loads `model.pkl` which was trained on synthetic data. It must be retrained once real device data is collected (use `POST /api/v1/ml/retrain` after 24+ hours of data).
