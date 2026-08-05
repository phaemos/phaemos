# Phaemos Verification Tracker

This is a living checklist for verifying every feature in Phaemos. Update status as work is completed and tested.

- [x] = verified and merged to main
- [ ] = pending implementation or hardware testing

---

## Infrastructure

- [x] GitHub repo created
- [x] CI pipeline (ruff, tsc, pytest)
- [x] Gitleaks secret scanning
- [x] Dependabot configured
- [x] CODEOWNERS defined
- [x] Issue templates
- [x] PR template
- [x] Biweekly security issue workflow
- [x] Grafana + Prometheus monitoring overlay
- [x] Auto-merge enabled on repo
- [x] Auto-delete branches on merge enabled
- [x] CodeQL workflow (Python + JavaScript, push/PR/weekly schedule)
- [x] Stale issue workflow (60-day threshold, security label exempt)
- [x] GitHub Discussions enabled with four category templates

---

## Backend

- [x] FastAPI app with CORS and Prometheus metrics
- [x] PostgreSQL via SQLAlchemy ORM
- [x] Redis configured
- [x] JWT authentication (register, login, /me endpoint)
- [x] Refresh token (httpOnly 7-day cookie) + logout endpoint
- [x] Devices CRUD
- [x] Telemetry ingest (POST) and history (GET)
- [x] Alert rules and alert history
- [x] Ticket CRUD
- [x] Ticket numbers (PHM-0001 format, SERIAL column)
- [x] WebSocket real-time telemetry push
- [x] OTA firmware upload route
- [x] Firmware latest + download endpoints (X-API-Key auth)
- [x] Discord and SMTP notification service
- [x] ML route (score, anomaly history)
- [x] Package __init__.py stubs
- [x] audit_service.py (log_action)
- [x] 001_initial_schema.sql full schema
- [x] ML evaluate.py skeleton
- [ ] Isolation Forest model trained on real data (waiting for hardware)
- [x] ML evaluate.py fully implemented (load_model, evaluate_precision_recall, plot_anomaly_distribution, generate_report)
- [x] audit_log route (GET /api/v1/audit-logs, admin-only, paginated)
- [x] Audit log CSV export with HMAC-SHA256 signature header
- [x] User management route (GET /api/v1/auth/users, admin-only, paginated)
- [x] PATCH /api/v1/auth/users/{user_id}/permissions (per-user RBAC overrides)
- [x] GET /api/v1/alert-rules (list, optional ?device_id=)
- [x] PUT /api/v1/alert-rules/{id} and DELETE /api/v1/alert-rules/{id}
- [x] GET /telemetry/export CSV streaming endpoint
- [x] from_ts/to_ts time-range filter on GET /telemetry/{device_id}
- [x] node_type filter on GET /telemetry/{device_id}
- [x] Demo mode (POST /demo/start, POST /demo/stop, APScheduler)
- [x] 90-day telemetry retention background task (APScheduler cron, daily 02:00 UTC)
- [x] firmware_version column on Device + exposed in DeviceResponse
- [x] Security hardening - rate limiting, lockout, WS JWT, telemetry Bearer auth, CORS, API key rotation
- [x] Rate limiting proxy headers - X-Real-IP read from Nginx, not request.client.host
- [x] alert rule evaluation extended to all v2 sensor fields
- [x] POST /api/v1/ml/retrain - admin only, background task, 1-hour cooldown
- [x] alerts.resolved ORM column corrected to Boolean
- [x] GET /devices and GET /tickets pagination via skip/limit
- [x] Multi-tenant device ownership - nullable owner_id FK on devices, GET /devices auth-gated with role filter
- [x] All routes protected (auth hardening sweep)
- [x] OAuth backend - Google and GitHub OAuth2 via authlib (email-matched)
- [x] 2FA TOTP backend - enable, confirm, verify, disable (pyotp)
- [x] User profile endpoints - PATCH /auth/me, change-password, DELETE /auth/me (GDPR), GET /auth/me/export
- [x] Webhooks backend - Slack/Discord/Teams (migration 006)
- [x] Fleet health summary endpoint (GET /health/summary)
- [x] Public status endpoint (GET /status - no auth)
- [x] Maintenance windows backend (migration 007)
- [x] Device tags ARRAY + search/filter (migration 008)
- [x] Batch firmware update by tag (POST /devices/batch/firmware-update)
- [x] RBAC permissions - migration 009, JSONB permissions column on users
- [x] Invitation flow (POST /auth/invite, GET/POST /auth/accept-invite)
- [x] slowapi rate limiting on login (5/min), register (10/hr), password change (5/hr), contact (3/hr), ML retrain
- [x] Input validation max_length on device, ticket, webhook schemas
- [x] Contact form backend (POST /api/v1/contact, Turnstile verify, SMTP send, 3/hr rate limit)

---

## Telemetry Schema (v2)

- [x] node_type column
- [x] pressure (BME280)
- [x] gyro_x, gyro_y, gyro_z (MPU6050)
- [x] bus_voltage, current_ma, power_mw (INA219)
- [x] ir_temperature (MLX90614)
- [x] distance_mm (VL53L0X)
- [x] gas_level, gas_alert (MQ-2)
- [x] shaft_angle, shaft_rpm (AS5600)
- [x] sound_level (MAX4466)
- [x] contact_temp (DS18B20)
- [x] moisture_level, water_detected (FC-28)
- [x] fft_peak_hz, vib_magnitude (STM32 FFT)

---

## Firmware

- [x] ESP32 v1 sketch (main.ino, dht22.ino, mpu6050.ino)
- [x] ESP32 OTA update (ota.ino)
- [x] ESP32 v2 main sketch (esp32.ino)
- [x] ESP32 v2 sensor modules (10 sensor pairs in sensors/)
- [x] ESP32 v2 output modules (4 pairs in outputs/)
- [x] ESP32 v2 comms modules (3 pairs in comms/)
- [x] ESP32 v2 README with wiring tables
- [x] STM32 Black Pill firmware (Core/Src + Core/Inc)
- [x] STM32 CMSIS-DSP FFT migration (arm_rfft_fast_f32, O(N log N), N=128, ~19 us on 96 MHz Cortex-M4F)
- [x] Arduino Nano firmware (nano_node/ with sensors.h/cpp)
- [x] Pico 2W MicroPython firmware (7 files in pico_w/)
- [ ] All firmware hardware-tested on physical boards (waiting for components)

---

## Frontend

- [x] Next.js App Router setup
- [x] Dashboard page (live chart, device cards, alert banner)
- [x] WebSocket real-time telemetry
- [x] Devices list page
- [x] Alerts page
- [x] Tickets page
- [x] Admin page
- [x] useTelemetry polling hook
- [x] useAlerts polling hook
- [x] lib/utils.ts helpers
- [x] StatusBadge UI component
- [x] LoadingSkeleton UI component
- [x] ErrorToast UI component
- [x] SensorGrid dashboard component (all v2 fields)
- [x] TicketTable (sortable)
- [x] TicketForm wired to POST /api/v1/tickets (controlled form, ErrorToast on failure)
- [x] UserTable wired to GET /api/v1/auth/users (role-coloured table)
- [x] AuditLog wired to GET /api/v1/audit-logs (paginated, action badges)
- [x] Device detail page full implementation (sensor grid + chart + export button)
- [x] TelemetryChart per-sensor groups with 1h/6h/24h/7d time range picker
- [x] AlertRulesPanel admin UI (inline edit, delete, new rule form with device picker)
- [x] Device comparison page /compare with up to 3 side-by-side columns
- [x] Global nav bar added to layout.tsx
- [x] Dark/light mode toggle (ThemeToggle + localStorage + pre-hydration script)
- [x] useTickets polling hook
- [x] Login page /login (JWT + cookie)
- [x] Next.js edge middleware route guard (all routes require valid token cookie)
- [x] LogoutButton in navbar
- [x] Full light mode - dark: variants across all components
- [x] useWebSocketTelemetry hook with exponential backoff reconnect
- [x] TelemetryChart wired for live WS pushes
- [x] SensorGrid on device detail page polls every 5s - live updates
- [x] AlertBanner Create Ticket button with prefilled modal
- [x] Tickets and Devices pages pagination Prev/Next controls
- [x] Axios refresh interceptor (auto-retry on 401 using refresh cookie)
- [x] Design system (typography, spacing, colour tokens)
- [x] Toast notification system (ToastProvider context)
- [x] Device search and tag filter on devices list page
- [x] Tab visibility pause (pause polling when tab is hidden)
- [x] Security headers (X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy)
- [x] robots.txt and sitemap.xml
- [x] Cookie consent banner (GDPR - GA4 loads only after accept, stored in localStorage)
- [x] Privacy policy page (/privacy)
- [x] Terms of service page (/terms)
- [x] Profile page (/profile) - name/email/phone edit, change password, 2FA enrolment, export, delete
- [x] Health summary widget on dashboard (HealthSummary component)
- [x] Ticket numbers displayed as PHM-XXXX on ticket table and detail
- [x] Webhook management UI in admin panel (WebhooksPanel)
- [x] About page (/about)
- [x] Blog index + post detail pages (/blog, /blog/[slug])
- [x] Changelog page (rendered CHANGELOG.md, /changelog)
- [x] Docs hub page (/docs)
- [x] Status page (/status) - polls GET /status + link to status.phaemos.com
- [x] Security page (/security)
- [x] FAQ page (/faq) - 17 questions in 6 sections
- [x] Support page (/support)
- [x] Contact page (/contact) with Cloudflare Turnstile widget
- [x] Vercel Analytics (Analytics component in layout.tsx)
- [x] GA4 (GoogleAnalytics component, consent-gated)
- [x] Maintenance windows UI in admin panel (MaintenanceWindowsPanel)
- [x] MaintenanceBanner on dashboard (polls every 60s)
- [x] Device tags UI - chips on DeviceCard, inline add/remove on device detail, batch firmware modal on devices list
- [x] GitHub Discussions card on support page (first card)
- [x] GitHub Discussions card on FAQ page ("Still have questions?" section)

---

## Hardware

- [x] ESP32 wiring guide
- [x] STM32 wiring guide
- [x] Nano wiring guide
- [x] Pico 2W wiring guide
- [x] PCB design guide
- [x] Proteus schematic placeholders
- [ ] Proteus ESP32 schematic (Phase 2)
- [ ] Proteus STM32 schematic (Phase 2)
- [ ] Proteus Nano schematic (Phase 2)
- [ ] PCB layout completed (Phase 3)
- [ ] Gerber files exported and ordered (Phase 3)

---

## Docs

- [x] Architecture overview (docs/architecture.md)
- [x] API reference (docs/api-reference.md)
- [x] Deployment checklist (docs/deployment-checklist.md)
- [x] Schema overview (docs/schema.md)
- [x] Decisions log (docs/decisions.md)
- [x] Sensor reference (docs/sensor_reference.md)
- [x] Deployment guide (docs/deployment.md)
- [x] Development timeline (docs/week_by_week.md)
- [x] Verification tracker (this file)
- [x] Instatus monitoring setup guide (docs/instatus.md)
- [x] Scalability guide (docs/scalability.md)
- [x] MkDocs Material site (mkdocs.yml, deployed at docs.phaemos.com)

---

## Legal and Governance

- [x] AGPL-3.0 licence (LICENSE file at repo root)
- [x] NOTICE file (copyright line)
- [x] CONTRIBUTING.md (branch prefixes, UK English, email alias table, AGPL statement)
- [x] CHANGELOG.md
- [x] SECURITY.md (responsible disclosure via GitHub Security Advisories)
- [x] SUPPORT.md (Discussions first, status.phaemos.com, contact form)
- [x] CODEOWNERS
- [x] FUNDING.yml (GitHub Sponsors, Buy Me a Coffee, Patreon)

---

## Hardware (physical - blocked)

- [ ] Physical assembly of all four nodes
- [ ] All sensors tested on real boards
- [ ] 24-48 hours of baseline data collected
- [ ] Isolation Forest model trained on real data
- [ ] Proteus schematics completed
- [ ] PCB layout completed
- [ ] Gerber files exported and ordered
