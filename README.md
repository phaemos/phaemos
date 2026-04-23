# PHAEMOS

Smart Maintenance Platform - collects real-time sensor data from ESP32/Arduino/STM32 hardware nodes, displays a live dashboard, fires alerts when readings exceed thresholds and uses machine learning to predict faults before they happen.

## Name, Pronunciation, and Meaning

- Pronunciation: **FAY-mos**
- Meaning: **"an ordered system that reveals"**
- Origin: coined from Ancient Greek roots tied to revelation/appearance and structure/order

Why this fits: PHAEMOS reveals hidden machine behavior through telemetry, alerting, anomaly detection, and maintenance workflows before visible failure occurs.

Suggested tagline: **Reveal before failure.**

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
phaemos/
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

## Languages & Tools Used

<div align="center">

| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/nextjs/nextjs-original.svg" width="60" /> | <img src="https://techstack-generator.vercel.app/react-icon.svg" width="60" /> | <img src="https://techstack-generator.vercel.app/ts-icon.svg" width="60" /> | <img src="https://skillicons.dev/icons?i=tailwind" width="60" /> | <img src="https://techstack-generator.vercel.app/js-icon.svg" width="60" /> |
| :----------------------------------------------------------------------------------------------------: | :----------------------------------------------------------------------------: | :-------------------------------------------------------------------------: | :--------------------------------------------------------------: | :-------------------------------------------------------------------------: |
|                                              **Next.js**                                               |                                   **React**                                    |                               **TypeScript**                                |                         **Tailwind CSS**                         |                               **JavaScript**                                |

| <img src="https://techstack-generator.vercel.app/python-icon.svg" width="60" /> | <img src="https://cdn.simpleicons.org/fastapi/009688" width="60" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" width="60" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/redis/redis-original.svg" width="60" /> | <img src="https://upload.wikimedia.org/wikipedia/commons/0/05/Scikit_learn_logo_small.svg" width="60" /> |
| :-----------------------------------------------------------------------------: | :-----------------------------------------------------------------: | :------------------------------------------------------------------------------------------------------------: | :--------------------------------------------------------------------------------------------------: | :------------------------------------------------------------------------------------------------------: |
|                                   **Python**                                    |                             **FastAPI**                             |                                                 **PostgreSQL**                                                 |                                              **Redis**                                               |                                             **Scikit-Learn**                                             |

| <img src="https://techstack-generator.vercel.app/docker-icon.svg" width="60" /> | <img src="https://techstack-generator.vercel.app/github-icon.svg" width="60" /> | <img src="https://cdn.simpleicons.org/vercel/000000" width="60" /> | <img src="https://cdn.simpleicons.org/render/46E3B7" width="60" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/git/git-original.svg" width="60" /> |
| :-----------------------------------------------------------------------------: | :-----------------------------------------------------------------------------: | :----------------------------------------------------------------: | :----------------------------------------------------------------: | :----------------------------------------------------------------------------------------------: |
|                                   **Docker**                                    |                                   **GitHub**                                    |                             **Vercel**                             |                             **Render**                             |                                             **Git**                                              |

| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/arduino/arduino-original.svg" width="60" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/c/c-original.svg" width="60" /> | <img src="https://cdn.simpleicons.org/stmicroelectronics/03234B" width="60" /> | <img src="https://cdn.simpleicons.org/espressif/E7352C" width="60" /> |
| :------------------------------------------------------------------------------------------------------: | :------------------------------------------------------------------------------------------: | :----------------------------------------------------------------------------: | :-------------------------------------------------------------------: |
|                                               **Arduino**                                                |                                            **C**                                             |                                   **STM32**                                    |                               **ESP32**                               |

</div>
