# PHAEMOS

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Discussions](https://img.shields.io/github/discussions/zaccesss/phaemos)](https://github.com/zaccesss/phaemos/discussions)

I built PHAEMOS as a smart maintenance platform: it collects real-time sensor data from ESP32, STM32 and Arduino hardware nodes, shows it on a live dashboard, fires alerts when readings cross a threshold and uses machine learning to flag anomalies before they turn into failures.

## Name, pronunciation and meaning

- Pronunciation: **FAY-mos**
- Meaning: "an ordered system that reveals"
- Origin: coined from Ancient Greek roots tied to revelation and structure

I chose the name because PHAEMOS reveals hidden machine behavior through telemetry, alerting, anomaly detection and maintenance workflows before a failure becomes visible. My tagline for it: reveal before failure.

## Quick navigation

<p align="center">
      <a href="#architecture">Architecture</a> •
      <a href="#quickstart">Quickstart</a> •
      <a href="#project-structure">Project structure</a> •
      <a href="#docs">Docs</a> •
      <a href="#release-flow">Release flow</a> •
      <a href="#hardware">Hardware</a> •
      <a href="#tech-stack">Tech stack</a> •
      <a href="#languages--tools-used">Languages &amp; tools used</a>
</p>

## Architecture

```
[ Hardware Layer - 4 nodes ]
  ESP32 Primary Node          -- 11 sensors, OLED, buzzer, RGB LED, relay
  STM32 Black Pill F411CEU6   -- MPU6050 at 100Hz + FFT, UART to ESP32
  Arduino Nano                -- BME280 + LDR + FC-28, serial to ESP32
  Raspberry Pi Pico 2W        -- BME280 + LDR + OLED, direct Wi-Fi POST
        |
  [ Firmware Layer ]
  Nano (serial 9600) -------> ESP32 (parses + merges payload)
  STM32 (UART 115200) ------> ESP32 (FFT peak Hz forwarded to API)
  Pico 2W (Wi-Fi) ----------> API directly
  ESP32 (Wi-Fi POST) -------> API every 5 seconds
        |
        | HTTP POST /api/v1/telemetry
        v
  [ Backend - FastAPI ]
  /telemetry  /devices  /alerts  /tickets  /auth  /ml  /ws
        |
   PostgreSQL 15 + Redis 7
        |
  [ ML Layer - Isolation Forest ]
  anomaly scoring runs on every ingest; POST /api/v1/ml/retrain refits on the
  last 10,000 rows. The shipped model.pkl is trained on synthetic data and
  will be retrained on real sensor data once Phase 5 hardware bring-up is done
        |
  [ Frontend - Next.js 15 ]
  live dashboard, sensor grid, device list, ticket system, admin panel
        |
  [ Observability ]
  Prometheus + Grafana monitoring overlay (docker-compose.monitoring.yml)
```

## Quickstart

### Prerequisites

- Docker and Docker Compose
- Node.js 18+
- Python 3.11+

### Run with Docker

```bash
cp .env.example .env
make dev
```

Or without Make:

```bash
docker compose up --build
```

Frontend: http://localhost:3000
Backend API: http://localhost:8000
API docs: http://localhost:8000/docs

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

### Quick API smoke test (no hardware)

I use this when I want to validate core backend flows quickly without wiring up sensors.

```bash
cd backend
uvicorn app.main:app --reload
```

In a second terminal:

```bash
python scripts/quick_api_smoke.py
```

What it tests:

- auth register and login
- device registration
- telemetry ingest with a generated device API key
- latest telemetry fetch
- ML score endpoint

## Project structure

```
phaemos/
├── firmware/
│   ├── esp32/              v2 primary node (sensors/, outputs/, comms/, esp32.ino)
│   ├── stm32_blackpill/    HAL vibration node (Core/Src + Core/Inc)
│   ├── arduino_nano/       BME280 + LDR + FC-28 secondary node
│   └── pico_w/             MicroPython ambient node
├── backend/
│   ├── app/                FastAPI routes, models, schemas, services
│   ├── ml/                 Isolation Forest training and evaluation
│   ├── migrations/         SQL schema for all tables
│   └── tests/              pytest suite
├── frontend/
│   ├── app/                Next.js App Router pages
│   ├── components/         Dashboard, tickets, admin, UI primitives
│   ├── hooks/              useTelemetry, useAlerts, useWebSocketTelemetry
│   └── lib/                Axios API client, utility functions
├── hardware/
│   ├── schematics/         Proteus schematic placeholders (Phase 5)
│   ├── wiring/             Pin connection tables for all 4 nodes
│   └── pcb/                PCB design guide for Proteus ARES (Phase 5)
├── docs/                   Architecture, API reference, sensor reference, security, deployment
├── monitoring/             Grafana + Prometheus overlay
├── Makefile                make dev / test / lint / build / migrate / seed
├── docker-compose.yml
├── CHANGELOG.md
├── SUPPORT.md
├── SECURITY.md
├── .env.example
└── README.md
```

## Docs

- [Architecture overview](docs/architecture.md)
- [Database schema](docs/schema.md)
- [API reference](docs/api-reference.md)
- [Sensor reference](docs/sensor_reference.md)
- [Security controls](docs/security.md)
- [Deployment guide](docs/deployment.md)
- [Deployment checklist](docs/deployment-checklist.md)
- [Development timeline](docs/week_by_week.md)
- [Decision log](docs/decisions.md)
- [Verification tracker](docs/VERIFICATION.md)
- [Support](SUPPORT.md)
- [Changelog](CHANGELOG.md)

## Release flow

PHAEMOS uses tag-based releases with changelog validation.

1. Update `CHANGELOG.md` with a new version section: `## [X.Y.Z] - DD-MM-YYYY`.
1. Commit and merge to `main`.
1. Create and push the tag:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

1. The GitHub Actions `Release` workflow validates the changelog entry and creates the GitHub release.

See [docs/deployment.md](docs/deployment.md) for the full VPS, Vercel and DNS setup guide. See [docs/deployment-checklist.md](docs/deployment-checklist.md) for the pre-release checklist.

## Hardware

I currently run four physical nodes. Phase 5 (wiring the boards, validating readings and training the ML model on real data) has not started yet, so the firmware and backend below are ready but unverified against live hardware. See [docs/week_by_week.md](docs/week_by_week.md) for the full phase breakdown.

| Board | Language | Role |
| --- | --- | --- |
| ESP32 DevKit | C++ (Arduino IDE) | Primary node, 11 sensors, Wi-Fi POST, OLED, buzzer, RGB LED, relay |
| STM32 Black Pill F411CEU6 | C (STM32 HAL) | Vibration node, MPU6050 at 100Hz, FFT, UART to ESP32 |
| Arduino Nano | C++ (Arduino IDE) | Secondary node, BME280, LDR, FC-28, serial CSV to ESP32 |
| Raspberry Pi Pico 2W | MicroPython | Ambient node, BME280, LDR, OLED, direct Wi-Fi POST |

| Sensor | Measures | Interface | Node |
| --- | --- | --- | --- |
| BME280 | Temperature, humidity, pressure | I2C 0x76 | ESP32, Nano, Pico 2W |
| MPU6050 | Acceleration + gyroscope (6-axis) | I2C 0x68 | ESP32, STM32 |
| INA219 | Bus voltage, current, power | I2C 0x40 | ESP32 |
| MLX90614 | Contactless IR surface temperature | I2C 0x5A | ESP32 |
| VL53L0X | Time-of-flight distance | I2C 0x29 | ESP32 |
| MQ-2 | Gas and smoke concentration | Analog GPIO34 | ESP32 |
| AS5600 | Magnetic shaft angle and RPM | I2C 0x36 | ESP32 |
| MAX4466 | Acoustic / sound level | Analog GPIO32 | ESP32 |
| DS18B20 | Precision contact temperature | OneWire GPIO4 | ESP32 |
| LDR | Ambient light | Analog GPIO33 | ESP32, Nano, Pico 2W |
| FC-28 | Moisture / water ingress | Analog GPIO36 | ESP32, Nano |

See [hardware/wiring/](hardware/wiring/) for full pin connection tables and [docs/sensor_reference.md](docs/sensor_reference.md) for library details.

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 15, TypeScript, Tailwind CSS |
| Backend | FastAPI (Python 3.11) |
| Database | PostgreSQL 15 |
| Cache | Redis 7 |
| ML | scikit-learn (Isolation Forest), pandas, numpy |
| Auth | JWT (python-jose), bcrypt, TOTP 2FA, Google/GitHub OAuth |
| Firmware | C++ (Arduino IDE), C (STM32 HAL), MicroPython |
| Hardware | ESP32, STM32 Black Pill F411CEU6, Arduino Nano, Raspberry Pi Pico 2W |
| Containers | Docker, Docker Compose |
| Monitoring | Prometheus, Grafana |
| Deployment | Vercel (frontend + docs), DigitalOcean VPS (backend + DB) |

## Languages & tools used

<div align="center">

### Frontend

| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/nextjs/nextjs-original.svg" width="60" /> | <img src="https://techstack-generator.vercel.app/react-icon.svg" width="60" /> | <img src="https://techstack-generator.vercel.app/ts-icon.svg" width="60" /> | <img src="https://skillicons.dev/icons?i=tailwind" width="60" /> | <img src="https://techstack-generator.vercel.app/js-icon.svg" width="60" /> |
| :----------------------------------------------------------------------------------------------------: | :----------------------------------------------------------------------------: | :-------------------------------------------------------------------------: | :--------------------------------------------------------------: | :-------------------------------------------------------------------------: |
|                                              **Next.js**                                               |                                   **React**                                    |                               **TypeScript**                                |                         **Tailwind CSS**                         |                               **JavaScript**                                |

### Backend & data

| <img src="https://techstack-generator.vercel.app/python-icon.svg" width="60" /> | <img src="https://cdn.simpleicons.org/fastapi/009688" width="60" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" width="60" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/redis/redis-original.svg" width="60" /> | <img src="https://upload.wikimedia.org/wikipedia/commons/0/05/Scikit_learn_logo_small.svg" width="60" /> |
| :-----------------------------------------------------------------------------: | :-----------------------------------------------------------------: | :------------------------------------------------------------------------------------------------------------: | :--------------------------------------------------------------------------------------------------: | :------------------------------------------------------------------------------------------------------: |
|                                   **Python**                                    |                             **FastAPI**                             |                                                 **PostgreSQL**                                                 |                                              **Redis**                                               |                                             **Scikit-Learn**                                             |

### Infrastructure & DevOps

| <img src="https://techstack-generator.vercel.app/docker-icon.svg" width="60" alt="Docker" /> | <img src="https://techstack-generator.vercel.app/github-icon.svg" width="60" alt="GitHub" /> | <img src="https://cdn.simpleicons.org/vercel/000000" width="60" alt="Vercel" /> | <img src="https://cdn.simpleicons.org/digitalocean/0080FF" width="60" alt="DigitalOcean" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/git/git-original.svg" width="60" alt="Git" /> |
| :-------------------------------------------------------------------------------------------: | :-------------------------------------------------------------------------------------------: | :-----------------------------------------------------------------------------: | :-----------------------------------------------------------------------------------------: | :---------------------------------------------------------------------------------------------------------: |
|                                           **Docker**                                          |                                           **GitHub**                                          |                                   **Vercel**                                    |                                      **DigitalOcean**                                       |                                                  **Git**                                                    |

### Firmware & hardware

| <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/arduino/arduino-original.svg" width="60" alt="Arduino" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/c/c-original.svg" width="60" alt="C" /> | <img src="https://techstack-generator.vercel.app/cpp-icon.svg" width="60" alt="C++" /> | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/bash/bash-original.svg" width="60" alt="Shell/Bash" /> | <img src="https://cdn.simpleicons.org/stmicroelectronics/03234B" width="60" alt="STM32" /> | <img src="https://cdn.simpleicons.org/espressif/E7352C" width="60" alt="ESP32" /> |
| :---------------------------------------------------------------------------------------------------------------------: | :---------------------------------------------------------------------------------------------------: | :--------------------------------------------------------------------------------------: | :------------------------------------------------------------------------------------------------------------------: | :----------------------------------------------------------------------------------------: | :--------------------------------------------------------------------------------: |
|                                                      **Arduino**                                                        |                                               **C**                                                   |                                         **C++**                                          |                                               **Shell/Bash**                                                         |                                          **STM32**                                         |                                     **ESP32**                                      |

</div>

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the branch naming convention, commit format, code standards and PR checklist before opening a pull request.

## Community

- [GitHub Discussions](https://github.com/zaccesss/phaemos/discussions): questions, ideas and show-and-tell
- [GitHub Issues](https://github.com/zaccesss/phaemos/issues): bug reports and feature requests

## Contact and support

For general enquiries use the [contact form](https://phaemos.com/contact) or email [contact@phaemos.com](mailto:contact@phaemos.com). For user support email [support@phaemos.com](mailto:support@phaemos.com). See [SUPPORT.md](SUPPORT.md) for the full list of help channels and [SECURITY.md](SECURITY.md) to report a vulnerability.
