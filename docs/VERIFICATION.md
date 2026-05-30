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

---

## Backend

- [x] FastAPI app with CORS and Prometheus metrics
- [x] PostgreSQL via SQLAlchemy ORM
- [x] Redis configured
- [x] JWT authentication (register, login, /me endpoint)
- [x] Devices CRUD
- [x] Telemetry ingest (POST) and history (GET)
- [x] Alert rules and alert history
- [x] Ticket CRUD
- [x] WebSocket real-time telemetry push
- [x] OTA firmware upload route
- [x] Discord and SMTP notification service
- [x] ML route (score, anomaly history)
- [x] Package __init__.py stubs
- [x] audit_service.py (log_action)
- [x] 001_initial_schema.sql full schema
- [x] ML evaluate.py skeleton
- [ ] Isolation Forest model trained on real data (Week 10)
- [ ] ML evaluate.py fully implemented
- [ ] audit_log route (GET /api/v1/audit)
- [ ] User management route (GET /api/v1/auth/users admin only)

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
- [x] TicketForm (stub)
- [x] UserTable (stub)
- [x] AuditLog (stub)
- [x] Device detail page stub
- [ ] TicketForm wired to POST /api/v1/tickets
- [ ] UserTable wired to GET /api/v1/auth/users
- [ ] AuditLog wired to GET /api/v1/audit
- [ ] Login page

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
- [x] 12-week plan (docs/week_by_week.md)
- [x] Verification tracker (this file)
