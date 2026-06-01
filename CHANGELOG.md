# Changelog

All notable changes to PHAEMOS are recorded in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
