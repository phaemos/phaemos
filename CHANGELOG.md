# Changelog

All notable changes to PHAEMOS are recorded in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Security

- Bumped backend `python-jose` to 3.4.0, `scikit-learn` to 1.5.0, `pytest` to 9.0.3 and `python-dotenv` to 1.2.2, closing 5 Dependabot alerts. Pinned a frontend `sharp` override to `^0.35.0` via npm `overrides`, closing 1 more. The remaining 21 open alerts (`authlib`, `python-multipart`) are already at their fixed versions in requirements.txt from earlier merged PRs, pending GitHub's next dependency graph rescan to auto-close
- Resolved CodeQL high-severity findings in backend: webhook URL platform detection now uses `urlparse` netloc comparison instead of substring matching to prevent bypass; phone number removed from SMS warning log to prevent PII exposure
- Pinned transitive `postcss` dependency to 8.5.10 via npm `overrides` to address GHSA-qx2v-qp2m-jg93 (XSS via unescaped `</style>` in CSS stringify output); the vulnerability was in the version of postcss bundled internally by next
- The OAuth login path's refresh cookie was hardcoded `secure=False` with a stale comment saying to gate it in production, unlike the password and TOTP verify paths which correctly gate on environment; now matches the same pattern

### Added

- A **Research** discussion form for papers, datasets and open questions that are not an issue yet
- A **Docs update** issue form and a **Q&A** discussion form
- `assets/brand/`: the PHAEMOS logo and emblem in light and dark versions with transparent backgrounds, the single-colour emblem, a 1280 by 640 social preview card and the full brand board, with the colours, type and usage rules
- New docs pages: `development.md` (running locally, the smoke test, the simulator and the test commands), `releases.md`, `tech-stack.md` and `repositories.md` (the monorepo layout and how publishing works), all in the docs site navigation
- `client/`: the `phaemos-client` Python SDK, the `phaemos-sim` simulator for all four node types with injectable faults and `phaemosctl`, a Go tool for status checks, sending readings and ingest load testing
- `edge/`: `phaemos-edge`, a Rust gateway that spools readings to disk and forwards them in order, so an outage loses nothing (ADR 020)
- `infra/` holds the Compose stack, the Prometheus and Grafana overlay and the SQL queries and seed data, published to its own repository. A root `docker-compose.yml` includes it, so every existing command still works from the root
- `backend`, `frontend`, `firmware` and `hardware` are published to their own read-only repositories on every merge to `main` (`split.yml`), each with its own licence and a note pointing back to the monorepo
- GitHub Sponsors added to `.github/FUNDING.yml` as first entry; order updated to github, buy_me_a_coffee, patreon
- `Repo maintenance` workflow (`update-pr-branches.yml`) to delete merged PR branches the merge could not clean up
- `.markdownlint.json` and a `markdownlint.yml` CI workflow, with a `.github/workflows/README.md` documenting every workflow in the repository
- YAML issue forms (`bug_report.yml`, `feature_request.yml`) replacing the old markdown issue templates
- `.github/ISSUE_TEMPLATE/config.yml` disabling the blank issue option, pointing to status page, Discussions, the security policy and the contact form instead

### Changed

- Hardware designs in `hardware/` are now licensed under the CERN Open Hardware Licence v2, Strongly Reciprocal (CERN-OHL-S-2.0), matching MELOPHOS. Everything else stays AGPL-3.0-or-later. `NOTICE.md` now explains which licence covers what and lists every dependency manifest. The README and docs licence sections say the same
- `CONTRIBUTING.md` rewritten: where to start, the branch, commit and style conventions, the email addresses and how to report a vulnerability, with callouts for the read-only component copies and security reports
- `hardware/README.md` rewritten with the correct firmware folders, the MPU6050 on the STM32 node, a warning about the Nano's 5 V logic and its own licence section
- Issue, discussion and pull request templates rebuilt: bug reports and questions ask for the component, both bug and feature forms ask to search first and the pull request template lists every component
- Callouts where a mistake costs something: private vulnerability reports in `SECURITY.md`, the Nano level shifter, the ESP32 LED strip power budget and `docker compose down` wiping the database
- README rewritten in full around the brand logo, which switches between its light and dark versions with the viewer's theme. It now covers what PHAEMOS does, a short architecture diagram, a table of every component folder and the repository it publishes to, a two-command quickstart and the simulator. The detail it used to carry moved into the docs: running without Docker, the smoke test and the test commands into `development.md`, the release flow into `releases.md`, the tech stack and boards into `tech-stack.md` and the folder tree into `repositories.md`. The docs home page lists every page and uses the current board names
- Auto-merge is now ecosystem-aware: patch and minor Dependabot bumps and major GitHub Actions bumps auto-merge once CI passes, but major `npm` and `pip` bumps are held for manual review since a breaking runtime change could pass lint and build yet still deploy; previously major bumps were skipped entirely
- README rewritten: dropped the leftover animated capsule-render footer banner, switched the prose to first person, fixed a stale architecture line that implied ML anomaly scoring was not yet built (it has been live since Phase 2, only real hardware data is still pending), verified every doc link and image still resolves
- Backend `redis` bumped to 8.1.0, `pandas` to 3.0.5 and `bcrypt` to 5.0.0; frontend `tailwind-merge` bumped to 3.6.0, `react`/`react-dom` to 19 and `eslint`/`eslint-config-next` to 9/16, each held for manual review as a major bump and verified individually rather than merged blind
- Frontend migrated to Tailwind CSS v4: `@tailwindcss/postcss` replaces the old `tailwindcss` + `autoprefixer` PostCSS plugins, `globals.css` uses a single `@import "tailwindcss"` instead of the three `@tailwind` directives and the existing `tailwind.config.ts` stays in effect via `@config` rather than migrating its theme into CSS
- Frontend migrated to ESLint 9's flat config for `eslint-config-next` 16: `.eslintrc.cjs` replaced by `eslint.config.mjs` importing the package's native flat config export directly; `next lint` (deprecated, crashes on ESLint 9 with a circular-JSON error) replaced by calling the `eslint` CLI directly in the `lint` script

### Removed

- Ignore rules for local working folders that no longer exist. The work they listed is tracked in the [roadmap issues](https://github.com/phaemos/phaemos/milestones)
- The Bugs discussion form, which had no matching discussion category. Q&A covers questions about unexpected behaviour
- `firmware/arduino/` and `firmware/stm32/`, the v1 sketches replaced by `arduino_nano/` and `stm32_blackpill/`. Nothing built or documented them and they gave the published firmware repository two STM32 folders. Git history keeps them

### Fixed

- `.github/CODEOWNERS` read `- @zaccesss` instead of `* @zaccesss`, so no pull request requested a review. It now carries the standard header and rule
- UK spelling and sentence joins in `docs/decisions.md`, `edge/README.md` and the audit log page range
- The STM32 driver READMEs called the MPU6050 driver an SPI driver. It talks to the sensor over I2C1, as the node README's wiring section shows
- Health check docs pointed at `/health`, which the API does not serve. Liveness is `GET /` and the public check is `GET /status`, which uptime monitors match on `operational`
- `SUPPORT.md`, `CONTRIBUTING.md` and the new issue page no longer link to phaemos.com, its status page or its docs site, none of which resolve before the Launch milestone. The new issue page links the roadmap board and `SUPPORT.md` instead
- `.github/dependabot.yml` had `open-pull-requests-limit: 0` on all three ecosystems, silently blocking every Dependabot PR since the pause was added; raised back to 5 on each ecosystem to match the limit already used in repo-ops and mirror-ops
- The `pydantic` bump to 2.13 split `email-validator` into an optional extra; schemas here use `EmailStr`, so bare `pydantic` no longer shipped it, added `pydantic[email]` to requirements.txt
- `prometheus-fastapi-instrumentator` 7.1.0 accessed a router attribute the newer `fastapi`/`starlette` no longer exposes; bumped to 8.1.0 alongside the `fastapi` bump it depends on rather than as a separate PR
- Tests asserting 403 for a missing Authorization header were updated to 401, matching newer `starlette`'s `HTTPBearer` behaviour; role-guard 403s for an authenticated but unauthorised user are unaffected
- `passlib` (unmaintained since around 2020) is incompatible with `bcrypt` 4.1+ in two ways: it reads a version attribute bcrypt 4.1+ removed and its own internal self-test hashes a deliberately 255-byte probe string that bcrypt 4.1+ now correctly rejects instead of silently truncating. Restored both the version attribute and the old truncate-rather-than-raise behaviour at the `bcrypt.hashpw`/`checkpw` boundary; real passwords are separately capped at 72 bytes in the password strength validator
- 18 existing call sites across several hooks and components were newly flagged by stricter `react-hooks` rules aimed at React Compiler compatibility, bundled with the `eslint-config-next` 16 upgrade. One (`app/faq/page.tsx`) was a genuine issue, a running counter mutated during render, replaced with a precomputed per-section offset. The other 17 are legitimate, documented patterns (syncing state from an external source on mount, an intentional ref read to batch WebSocket pushes between polls, a standard recursive-reconnect closure) that this new rule set is unable to distinguish from unsafe code; each is annotated with a scoped, justified `eslint-disable` rather than rewritten

### Changed

- Bumped backend `uvicorn` to 0.54.0. SQLAlchemy stays on 2.0.x and Dependabot now ignores 2.1 and later, since 2.1 switches a bare `postgresql://` URL to the `psycopg` driver while the backend uses `psycopg2-binary`.
- Replaced em dashes in comments in `deploy.yml` and the monitoring compose file with plain punctuation. The discussion templates lost their Oxford commas too.

## [2.3.0] - 2026-06-03

### Added

- Multi-tenant device ownership: nullable `owner_id` FK on devices; technicians see only their own devices; admins see all (PR 86)
- Auth hardening: every non-public backend route now requires a valid JWT; admin-only routes require role=admin (PR 88)
- Refresh token flow: 15-minute access tokens + 7-day httpOnly refresh cookie; `POST /auth/refresh` and `POST /auth/logout` endpoints (PR 89)
- Human-readable ticket numbers in PHM-0001 format (SERIAL column, backend + frontend display) (PR 90)
- Google OAuth and GitHub OAuth sign-in (authlib, email-matched upsert, redirect with JWT) (PRs 91, 92)
- TOTP two-factor authentication: enable, confirm, verify, disable endpoints; `pyotp` + QR code via `qrcode` (PR 93)
- User profile management: `PATCH /auth/me`, `POST /auth/change-password`, `DELETE /auth/me` (GDPR erasure), `GET /auth/me/export` (GDPR portability) (PR 94)
- Webhooks backend: Slack, Discord and Teams integrations; auto-detect platform from URL; custom message template; test endpoint (PR 95)
- Fleet health summary: `GET /health/summary` returning online/offline counts and health score; public `GET /status` database and Redis health check (PR 96)
- Maintenance windows: create/update/delete windows; alert suppression during active windows; `POST /api/v1/maintenance-windows` admin endpoint (PR 97)
- Device tags: PostgreSQL ARRAY column; `POST /devices/{id}/tags`, `DELETE /devices/{id}/tags/{tag}`; tag filter on `GET /devices`; `POST /devices/batch/firmware-update` by tag (PR 98)
- RBAC permissions: JSONB `permissions` column on users; `PATCH /auth/users/{id}/permissions` admin endpoint (migration 009) (PR 101)
- SMS critical alerts via Brevo transactional SMS API; graceful no-op when key is not configured (PR 102)
- User invitation flow: `POST /auth/invite` sends signed JWT link via Resend; `GET/POST /auth/accept-invite` for onboarding (PR 104)
- Axios refresh token interceptor: silently retries 401 responses using the httpOnly refresh cookie (PR 99)
- Design system: Tailwind colour tokens (brand, surface, success, warning, critical); Sidebar nav replacing top nav; `SidebarNav` component (PR 100)
- Toast notification system: `ToastProvider` context + reducer; success/warning/error/info variants with 4s auto-dismiss (PR 105)
- Device owner picker (admin only) on device detail page (PR 106)
- Tab visibility pause: telemetry polling pauses when `document.hidden` is true (PR 107)
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`; `robots.txt`; `sitemap.ts` (PR 108)
- Rate limiting on all sensitive endpoints: login (5/min), register (10/hr), password change (5/hr), contact form (3/hr), ML retrain; proxy-aware key function reads `X-Real-IP` from Nginx (PR 109)
- Profile page: name/email/phone edit, password change, 2FA enrolment UI, GDPR export and account deletion (PR 110)
- Health summary widget on dashboard: four stat cards polling `GET /health/summary` every 30s (PR 111)
- Webhook admin UI: list, create, delete, enable/disable toggle, test button (PR 113)
- Privacy policy (`/privacy`), terms of service (`/terms`) and cookie consent banner with localStorage consent gate (PR 114)
- About page (`/about`), blog with three posts (`/blog`), rendered changelog (`/changelog`), docs hub (`/docs`) (PR 115)
- Status page (`/status`): polls `GET /status` every 30s, shows per-component health badges and public Instatus link (PR 116)
- Security (`/security`), FAQ (`/faq`), support (`/support`) public pages; all added to middleware `PUBLIC_PATHS` (PR 118)
- Contact form (`/contact`): Cloudflare Turnstile bot protection, SMTP send, 3/hr rate limit (PR 125)
- Vercel Analytics and Google Analytics 4 (consent-gated, loads only after cookie accept) (PR 120)
- Maintenance windows admin panel and dashboard amber pulsing banner (PR 121)
- Device tag chips on DeviceCard; inline tag add/remove on device detail; batch firmware update modal (PR 122)
- MkDocs Material documentation site (`docs.phaemos.com`); `mkdocs.yml`, `requirements-docs.txt`, `docs/index.md`; `make docs` and `make docs-build` targets (PR 128)
- Instatus external status page setup guide (`docs/instatus.md`); public status card on `/status` page linking to `status.phaemos.com` (PR 129)
- Scalability guide (`docs/scalability.md`): six-stage scaling path from single VPS to distributed (PR 130)
- GitHub Discussions: four category templates; README Community section and badge; support and FAQ pages updated (PR 132)
- CodeQL security scanning workflow (Python + JavaScript, push/PR/weekly schedule); stale issue workflow; `FUNDING.yml` (PR 127)
- GDPR cookie consent gate on GA4; `GoogleAnalytics.tsx` client component reads `cookie_consent` from localStorage (PR 120)
- `frontend/.env.example` documenting all `NEXT_PUBLIC_*` variables (PR 135)
- Input validation `max_length` on all string fields in device, ticket and webhook Pydantic schemas (PR 135)

### Changed

- Deployment platform: Render replaced by DigitalOcean VPS with Docker Compose + Nginx reverse proxy; `docs/deployment.md` fully rewritten (PR 129)
- Rate limiter key function updated to read `X-Real-IP` from Nginx instead of `request.client.host` so per-IP limits work correctly behind a reverse proxy (PR 135)
- `docs/week_by_week.md` rewritten from rigid 12-week table to phase-based structure separating done from pending work (PR 135)
- `docs/architecture.md` updated for v2 hardware, Next.js 15 and DigitalOcean deployment (PR 135)
- `docs/api-reference.md` expanded with all endpoints added since v2.2.0 (PR 135)
- All em dashes in source comments replaced with hyphens per project style guide (PR 135)

### Fixed

- STM32 FFT migrated from custom O(N^2) DFT to `arm_rfft_fast_f32` (CMSIS-DSP); 9x speedup on 96 MHz Cortex-M4F; N=128 power-of-two buffer (PR 131)
- CI postgres service container replaced with explicit pull-with-retry loop to survive transient Docker Hub timeouts (PR 134)
- Broken `uptime-kuma.md` link in `docs/index.md` replaced with `instatus.md` (PR 135)
- `NEXT_PUBLIC_GA_ID` added to `.env.example` (was referenced in code but undocumented) (PR 135)
- Legacy `RENDER_DEPLOY_HOOK_URL` removed from `.env.example` (PR 135)

### Security

- Licence changed from Apache 2.0 to AGPL-3.0; `LICENSE` and `NOTICE` files added; README badge updated (PR 123)
- Responsible disclosure policy updated to use GitHub Security Advisories as primary channel (PR 135)
- Input validation: `Field(max_length=...)` added to all unbounded string fields in device, ticket and webhook schemas - prevents storage exhaustion attacks (PR 135)

## [2.2.0] - 2026-06-02

### Added

- WebSocket reconnect with exponential backoff (1/2/4/8/16s, max 5 attempts). No retry on close code 1008 to prevent token-expiry loop (PR 77)
- `useWebSocketTelemetry` hook; `TelemetryChart` now merges live WS pushes with 5s polling and deduplicates by id (PR 77)
- `POST /api/v1/ml/retrain` - admin-only endpoint; fits IsolationForest on last 10,000 rows, dumps model.pkl and reloads in-memory model; 1-hour cooldown; logs outcome to audit log (PR 80)
- `FEATURE_COLS` constant and `reload_model()` in `ml_service.py` so scoring and retraining use the same feature vector (PR 80)
- SensorGrid on device detail page polls `GET /telemetry/{id}/latest` every 5s via `useTelemetry` - live sensor values without a page refresh (PR 81)
- AlertBanner now has a Create Ticket button that opens a modal with TicketForm prefilled from alert context (device_id, title, severity/timestamp in description) (PR 83)
- Pagination on `GET /tickets` and `GET /devices` - `skip`/`limit` query params (default 0/20) (PR 84)
- Prev/Next pagination controls on Tickets and Devices frontend pages (PR 84)
- `docs/security.md` - 18-measure security table (PR 85)
- `Makefile` - make dev, make test, make lint, make build, make migrate, make seed (PR 85)
- `SUPPORT.md` - self-help resources and common issues (PR 85)
- Three new ADRs in `docs/decisions.md`: WS JWT via query param (010), ML retrain as background task (011), skip/limit pagination (012) (PR 85)

### Fixed

- `alerts.resolved` ORM column changed from `Column(String)` to `Column(Boolean)`. `str(resolved)` cast removed from list-alerts filter - DB schema was already BOOLEAN so no migration required (PR 82)
- Alert rule evaluation now receives all v2 sensor fields. The ingest route previously built `reading` from 6 hardcoded fields; rules on `gas_level`, `shaft_rpm` etc. would never fire (PR 79)
- `/ml/score` endpoint fixed to use `payload.model_dump()` instead of same 6-field hardcoded dict (PR 80)

## [2.1.0] - 2026-06-01

### Added

- Login page and session guard (backlog - next session)
- Hardware inventory tracking: hardware/inventory/owned.md and needed.md with full component list
- README added to every folder and subfolder across the entire repo
- Pico W schematic placeholder added to hardware/schematics/
- PostCSS config (postcss.config.js) - was missing, causing Tailwind CSS to not compile
- alerts.resolved String/Boolean type mismatch fix in routes/alerts.py
- Dashboard selected-device polling bug fix - user selection no longer resets every 5 seconds

### Changed

- TelemetryChart refactored: prop changed from readings[] to deviceId, now manages own data fetch
- Dashboard uses Promise.allSettled so a failing alerts query never blocks device cards
- layout.tsx: suppressHydrationWarning on html element, proper light/dark body classes

## [2.0.0] - 2026-05-30

### Added

- Extended telemetry schema with 18 new sensor columns (v2)
- ESP32 v2 structured firmware: 10 sensor modules, 4 output modules, 3 comms modules
- STM32 Black Pill firmware (FFT vibration analysis)
- Arduino Nano firmware (auxiliary sensor node)
- Raspberry Pi Pico 2W MicroPython firmware (ambient environment node)
- Backend additions: audit_service, Alembic migrations, ML evaluate skeleton
- Frontend additions: SensorGrid, TicketTable, polling hooks, UI components
- Hardware wiring guides for all 4 nodes
- Sensor reference documentation
- Deployment guide and checklist
- VERIFICATION.md tracker
- JWT auth: get_current_user dependency, /auth/me, /auth/users (admin)
- GET /audit-logs endpoint (admin, paginated)
- Audit service calls wired into all mutating routes
- Alert rules CRUD (GET/PUT/DELETE /alert-rules)
- AlertRulesPanel admin component
- TicketForm, UserTable, AuditLog wired to real endpoints
- Device detail page with SensorGrid, TelemetryChart and Export CSV
- TelemetryChart: 4 collapsible per-sensor groups, 1h/6h/24h/7d time range picker
- GET /telemetry/export CSV streaming endpoint
- Device comparison page /compare with up to 3 side-by-side columns
- Global nav bar
- node_type filter on GET /telemetry and dashboard picker buttons
- firmware_version column on Device model and DeviceCard display
- Demo mode: POST /demo/start with APScheduler sinusoidal data generation
- 90-day data retention task via APScheduler cron (02:00 UTC)
- Dark/light mode toggle with ThemeToggle and localStorage persistence
- ML evaluate.py fully implemented: load_model, evaluate_precision_recall, plot_anomaly_distribution, generate_report
- Uptime Kuma setup documentation
- Docs updated: api-reference, architecture, decisions, schema, VERIFICATION

### Added

- Repo health files: LICENSE, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT and SECURITY
- GitHub Actions CI pipeline for backend linting and frontend type-checking
- Gitleaks secret scanning workflow
- GitHub release workflow with changelog version validation on pushed tags
- Biweekly GitHub workflow that opens or updates a security issue when `npm audit --omit=dev` reports frontend production vulnerabilities
- Issue templates for bug reports and feature requests
- Pull request template
- Dependabot configuration for automated dependency updates
- CODEOWNERS file
- `.editorconfig` for consistent formatting across editors
- Deployment checklist for Render backend and Vercel frontend
- Docker build-context ignore files for backend and frontend images
- pytest test suite with PostgreSQL service container in CI and transaction-rollback test isolation
- WebSocket real-time telemetry push endpoint (`/ws/telemetry`)
- OTA firmware upload route and ESP32 OTA sketch
- Discord webhook and SMTP email notification service
- Grafana and Prometheus monitoring overlay (`monitoring/`)
- Auto-deploy workflow triggering Render on CI pass

**v2.0 hardware spec additions (30-05-2026)**

- Extended telemetry schema with 18 new sensor columns: node\_type, pressure (BME280), gyro\_x/y/z (MPU6050), bus\_voltage/current\_ma/power\_mw (INA219), ir\_temperature (MLX90614), distance\_mm (VL53L0X), gas\_level/gas\_alert (MQ-2), shaft\_angle/shaft\_rpm (AS5600), sound\_level (MAX4466), contact\_temp (DS18B20), moisture\_level/water\_detected (FC-28), fft\_peak\_hz/vib\_magnitude (STM32 FFT output)
- ESP32 v2 firmware structured subfolder layout: `firmware/esp32/sensors/` (10 sensor pairs), `firmware/esp32/outputs/` (OLED, buzzer, RGB LED, relay), `firmware/esp32/comms/` (WiFi manager, HTTP client, serial parser), new `esp32.ino` v2 main sketch
- STM32 Black Pill firmware (`firmware/stm32_blackpill/`): HAL I2C register-level MPU6050 driver, DFT FFT implementation, 100Hz TIM2 sampling, UART output
- Arduino Nano firmware (`firmware/arduino_nano/`): BME280 + LDR + FC-28, CSV serial output at 9600 baud for ESP32 to parse
- Raspberry Pi Pico 2W firmware (`firmware/pico_w/`): MicroPython BME280 driver with full datasheet compensation, SSD1306 OLED driver, Wi-Fi connect helper, urequests HTTP POST
- Backend package `__init__.py` stubs for models, routes, schemas, services directories
- `audit_service.py`: standalone `log_action()` using raw SQL so audit entries survive ORM changes
- `backend/migrations/001_initial_schema.sql`: complete CREATE TABLE schema for all 7 tables with indexes
- `backend/ml/evaluate.py`: skeleton with docstrings for `load_model`, `evaluate_precision_recall`, `plot_anomaly_distribution`, `generate_report`
- `backend/.env.example`: all 15 environment variables documented
- Frontend `useTelemetry` and `useAlerts` polling hooks with setInterval cleanup
- `lib/utils.ts`: formatDate, formatSensorValue, severityColor, clamp, nodeTypeLabel helpers
- `StatusBadge`, `LoadingSkeleton`, `ErrorToast` UI primitive components
- `SensorGrid` dashboard component showing all 11 v2 sensor categories
- `TicketTable` (sortable), `TicketForm` (stub), `UserTable` (stub), `AuditLog` (stub) components
- Device detail page stub at `app/devices/[id]/page.tsx`
- `hardware/` folder: Proteus schematic placeholders, wiring guides for all 4 nodes, PCB design guide
- `docs/sensor_reference.md`: full sensor tables with I2C addresses and library references
- `docs/deployment.md`: Render + Vercel + Docker self-hosted deployment guide
- `docs/week_by_week.md`: updated 12-week implementation plan
- `docs/VERIFICATION.md`: living checklist tracking verified vs pending features
- Repo settings: auto-merge enabled, auto-delete-branch-on-merge enabled
- Branch protection on main requiring all 4 CI checks to pass before merge

### Changed

- Frontend upgraded from `next@14.2.3` to `next@15.5.15`
- Frontend PostCSS pinned to `8.5.10` in direct dev dependencies
- Release changelog date heading format standardised to `DD-MM-YYYY`
- README architecture diagram updated to show all 4 nodes and full sensor list
- README hardware table updated to v2 hardware spec
- README project structure updated to include hardware/ folder
- README tech stack updated to Next.js 15 and full firmware language list
- `backend/requirements.txt` extended with `python-dotenv` and `pytest-asyncio`

### Fixed

- Next.js 15 async params type in `app/devices/[id]/page.tsx` (params is now `Promise<{ id: string }>`)

### Security

- Removed previously reported critical and high severity frontend advisories by moving off the vulnerable Next 14 line
- Remaining moderate transitive PostCSS advisory is currently upstream in Next.js and is tracked for future patch updates
- `.gitignore` extended to exclude Arduino build artefacts (`*.elf`, `*.bin`, `*.hex`, `*.map`) and Proteus files (`*.DBK`, `*.LKS`, `*.SDF`)

---

## [0.2.0] - 2025-05-06

### Added

- `version` and `environment` fields in the root health endpoint response

---

## [0.1.0] - 2025-05-01

### Added

- FastAPI backend with telemetry ingestion, device registry, alert rules and ticket system
- JWT authentication with role-based access control (admin, technician, viewer)
- PostgreSQL data models and SQLAlchemy ORM layer
- Isolation Forest ML anomaly scoring pipeline
- Next.js frontend with live dashboard, device list, alert feed and ticket management
- ESP32 firmware for DHT22 temperature/humidity and MPU6050 vibration readings
- Arduino Uno secondary firmware
- STM32 high-frequency vibration firmware
- Docker Compose local development stack
- Initial project documentation

[Unreleased]: https://github.com/zaccesss/phaemos/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/zaccesss/phaemos/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/zaccesss/phaemos/releases/tag/v0.1.0
