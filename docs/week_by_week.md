# 12-Week Implementation Plan

This is the v2 implementation plan updated to reflect the full multi-node hardware specification. Weeks are relative to the start of the build, not calendar dates.

---

## Before Components Arrive

These tasks can be completed before any hardware is in hand. Start here if your components are on order.

- Set up the backend FastAPI project structure and write all route stubs
- Write the PostgreSQL schema migration (001_initial_schema.sql) covering the full v2 telemetry schema
- Write the Next.js frontend structure with page stubs for Dashboard, Devices, Alerts, Tickets, and Admin
- Set up Docker Compose with backend, PostgreSQL, Redis, and frontend containers
- Study the Arduino IDE documentation and set up the ESP32 board package
- Study the STM32CubeIDE documentation and set up the STM32F411 board support package
- Set up MicroPython tooling for Pico 2W (mpremote, Thonny)
- Write firmware modules in Arduino IDE using simulated/dummy sensor values to validate the POST payload format
- Write the Isolation Forest training pipeline skeleton using sample data

---

## Weekly Plan

| Week | Phase | Goal | Status |
|---|---|---|---|
| 1 | Hardware + Firmware | Wire ESP32 with BME280 and MPU6050 on breadboard. Confirm serial readings in Arduino IDE Serial Monitor. Validate I2C addresses with i2cscanner sketch. | Hardware Required |
| 2 | Backend | FastAPI backend running locally in Docker. Telemetry POST endpoint accepting v2 payload. Pytest passing for health and telemetry routes. | Software Only |
| 3 | Integration | ESP32 POSTing live BME280 and MPU6050 data to local API over Wi-Fi. Verify data appears in PostgreSQL. | Mixed |
| 4 | Frontend | Next.js dashboard showing live temperature, humidity, and gyro charts from the API. SensorGrid component rendering all v2 fields. | Software Only |
| 5 | Hardware + Firmware | Wire remaining ESP32 sensors: INA219, MLX90614, VL53L0X, MQ-2, AS5600, DS18B20, FC-28. All sensors reading in firmware and included in POST payload. | Hardware Required |
| 6 | Firmware + Backend | Alert rules engine operational. Buzzer tone on alert trigger. WS2812B LED colour changes with system status. Alert history stored in PostgreSQL. | Mixed |
| 7 | Backend + Frontend | JWT authentication (register, login, /me). Role-based access (admin vs viewer). Ticket CRUD routes. Ticket list page in frontend. | Software Only |
| 8 | Hardware + Firmware | Wire Nano, STM32 Black Pill, and Pico 2W. All four nodes posting data to the API simultaneously. STM32 FFT results streaming via UART to ESP32. | Hardware Required |
| 9 | Backend + Frontend | Audit log (log_action on all mutations). Admin panel page. Full dashboard polish (loading skeletons, error toasts, status badges). UserTable and AuditLog wired to live API. | Software Only |
| 10 | ML | Collect 24-48 hours of baseline sensor data. Preprocess into feature vectors. Train Isolation Forest model. Evaluate on held-out normal and anomaly samples. | Mixed |
| 11 | ML + Frontend | ML scoring live via /api/v1/ml/score. Anomaly history stored. Anomaly indicators highlighted on dashboard charts. Anomaly history page or panel added. | Software Only |
| 12 | Hardware + Docs | Create Proteus ISIS schematic for ESP32 node (Phase 2). Begin PCB layout in ARES. Write final README sections. Record demo video showing all four nodes live on the dashboard. | Mixed |

---

## Notes

- Weeks marked **Hardware Required** cannot be completed without physical components on the bench.
- Weeks marked **Software Only** can be completed in parallel with hardware delivery delays.
- Weeks marked **Mixed** have a software deliverable that can proceed and a hardware deliverable that requires components.
- The ML week (Week 10) requires at least several hours of real sensor data; the model will not generalise on simulated data.
