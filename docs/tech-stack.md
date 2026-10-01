# Tech stack

Every language and tool PHAEMOS uses, by layer. The reasons behind the main choices are in
[decisions.md](decisions.md).

| Layer | Technology |
| --- | --- |
| Dashboard | Next.js 15, React, TypeScript, Tailwind CSS |
| Backend | FastAPI on Python 3.11 |
| Database | PostgreSQL 15 |
| Cache and pub/sub | Redis 7 |
| Machine learning | scikit-learn (Isolation Forest), pandas, NumPy |
| Auth | JWT (python-jose), bcrypt, TOTP two-factor sign-in, Google and GitHub OAuth |
| Firmware | C++ (Arduino), C (STM32 HAL with CMSIS-DSP), MicroPython |
| Edge gateway | Rust |
| SDK and simulator | Python |
| CLI and load testing | Go |
| Containers | Docker, Docker Compose |
| Monitoring | Prometheus, Grafana, Instatus |
| Hosting | Vercel (dashboard and docs), DigitalOcean (backend and database) |
| Documentation | MkDocs |
| CI | GitHub Actions, CodeQL, gitleaks |

## Hardware

| Board | Language | Role |
| --- | --- | --- |
| ESP32 DevKit | C++ (Arduino) | Primary node: 11 sensors, OLED, buzzer, RGB LED, relay, Wi-Fi to the API |
| STM32 Black Pill F411CEU6 | C (STM32 HAL) | Vibration node: accelerometer sampled at 100 Hz, FFT, UART to the ESP32 |
| Arduino Nano | C++ (Arduino) | Secondary node: BME280, LDR and FC-28, serial to the ESP32 |
| Raspberry Pi Pico 2W | MicroPython | Ambient node: BME280, LDR and OLED, Wi-Fi straight to the API |

Every sensor, its interface and its expected range are in [sensor_reference.md](sensor_reference.md).
