# Architecture Overview

## System Diagram

```
[ Physical Layer ]
  DHT22 (temp/humidity)
  MPU6050 (vibration/accel)
  LDR (ambient light)
  DS18B20 (precise temperature)
        |
        | I2C / Analog / OneWire
        v
[ Firmware Layer ]
  Arduino Uno      --> serial --> ESP32 Wi-Fi Gateway
  STM32 (UART)     ----------->  ESP32 Wi-Fi Gateway
  ESP32 (standalone, reads its own sensors too)
        |
        | HTTP POST (JSON) to /api/v1/telemetry
        | Header: X-API-Key: <device api key>
        v
[ Backend Layer - FastAPI ]
  Routes:
    /telemetry   - ingest + alert rule evaluation
    /devices     - device registry + API key management
    /alerts      - alert history + resolve
    /alert-rules - threshold rules per device/metric
    /tickets     - maintenance ticket CRUD
    /auth        - register, login, JWT
    /ml          - anomaly score endpoint
        |
        |---> PostgreSQL 15 (persistent storage)
        |---> Redis (alert queue, rate limiting)
        v
[ ML Layer ]
  Isolation Forest (scikit-learn)
  - trained offline on historical telemetry CSV
  - loaded as model.pkl at startup
  - scores every ingest: 0 (normal) → 1 (anomaly)
  - threshold 0.7+ triggers alert + flags telemetry row
  Phase 3: LSTM for time-series sequence prediction
        |
        v
[ Frontend Layer - Next.js 14 ]
  /               - live dashboard (charts, status cards, recent alerts)
  /devices        - device list + device detail
  /alerts         - alert feed, resolve actions
  /tickets        - ticket table, create/update tickets
  /admin          - user management, device registration, audit logs
```

## Data Flow (Happy Path)

1. ESP32 reads sensors every 5 seconds
2. Builds JSON payload with device_id + readings
3. POSTs to `POST /api/v1/telemetry` with `X-API-Key` header
4. FastAPI validates API key → looks up device
5. ML service scores the reading
6. Alert service checks reading against all rules for that device
7. If rule triggered → inserts alert row → auto-creates ticket if critical
8. Telemetry row saved to PostgreSQL with anomaly_score + is_anomaly
9. Frontend polls `GET /api/v1/telemetry/{device_id}/latest` every 5s
10. Dashboard updates chart and status indicators

## Deployment

| Service      | Platform     | Notes                            |
| ------------ | ------------ | -------------------------------- |
| Frontend     | Vercel       | Auto-deploy from main branch     |
| Backend + DB | Render       | Web service + managed PostgreSQL |
| Redis        | Render Redis | Or Upstash free tier             |

## Security Boundaries

- Device authentication: `X-API-Key` header on all `/telemetry` ingests
- User authentication: JWT Bearer token on all protected routes
- Role enforcement: middleware checks `user.role` on every protected endpoint
- Password storage: bcrypt (cost factor 12)
- No raw SQL: all queries via SQLAlchemy ORM
