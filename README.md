# PulseWatch

Smart Maintenance Platform - collects real-time sensor data from ESP32/Arduino/STM32 hardware nodes, displays a live dashboard, fires alerts when readings exceed thresholds and uses machine learning to predict faults before they happen.

## Architecture

```
[ Hardware Layer ]
  DHT22 + MPU6050 + LDR + DS18B20
        |
  [ Firmware Layer ]
  Arduino Uno (serial) --> ESP32 (Wi-Fi gateway)
  STM32 (UART) ---------> ESP32 or direct USB
        |
        | HTTP POST / MQTT
        v
  [ Backend - FastAPI ]
  /telemetry  /devices  /alerts  /tickets  /auth  /ml
        |
   PostgreSQL + Redis
        |
  [ ML Layer - Isolation Forest ]
  anomaly scoring on every ingest
        |
  [ Frontend - Next.js ]
  live dashboard, device list, ticket system, admin panel
```

## Quickstart

### Prerequisites

- Docker + Docker Compose
- Node.js 18+
- Python 3.11+

### Run with Docker

```bash
cp .env.example .env
docker-compose up --build
```

Frontend: http://localhost:3000
Backend API: http://localhost:8000
API Docs: http://localhost:8000/docs

### Run without Docker

**Backend**

```bash
cd backend
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

## Project Structure

```
pulsewatch/
├── firmware/           ESP32, Arduino, STM32 firmware
├── backend/            FastAPI backend + ML pipeline
├── frontend/           Next.js dashboard
├── docs/               Architecture, schema, API reference, decisions
├── docker-compose.yml
├── .env.example
└── README.md
```

## Docs

- [Architecture Overview](docs/architecture.md)
- [Database Schema](docs/schema.md)
- [API Reference](docs/api-reference.md)
- [Decision Log](docs/decisions.md)

## Milestone Plan

| Phase | Weeks | Focus                                                 |
| ----- | ----- | ----------------------------------------------------- |
| 1     | 1-4   | Hardware firmware + telemetry ingest + live dashboard |
| 2     | 5-8   | Alert rules + JWT auth + ticket system + audit logs   |
| 3     | 9-12  | ML anomaly detection + maintenance recommendations    |

## Hardware

| Board       | Role                                                         |
| ----------- | ------------------------------------------------------------ |
| ESP32       | Primary IoT node - reads sensors, POSTs to API over Wi-Fi    |
| Arduino Uno | Secondary node - reads sensors over serial, relays via ESP32 |
| STM32       | Advanced node - high-frequency vibration sampling via UART   |

| Sensor  | Measures                           | Board           |
| ------- | ---------------------------------- | --------------- |
| DHT22   | Temperature + humidity             | ESP32 / Arduino |
| MPU6050 | Vibration, acceleration, gyroscope | ESP32 / STM32   |
| LDR     | Ambient light                      | Arduino / ESP32 |
| DS18B20 | Precise temperature                | Any             |

## Tech Stack

| Layer       | Technology                                     |
| ----------- | ---------------------------------------------- |
| Frontend    | Next.js 14 + TypeScript + Tailwind CSS         |
| Backend     | FastAPI (Python 3.11)                          |
| Database    | PostgreSQL 15                                  |
| Cache/Queue | Redis                                          |
| ML          | scikit-learn (Isolation Forest), pandas, numpy |
| Auth        | JWT (python-jose), bcrypt                      |
| Hardware    | ESP32, Arduino Uno, STM32                      |
| Containers  | Docker + Docker Compose                        |
| Deployment  | Vercel (frontend), Render (backend + DB)       |
