# Changelog

All notable changes to PHAEMOS are recorded in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- Repo health files: LICENSE, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT and SECURITY
- GitHub Actions CI pipeline for backend linting and frontend type-checking
- Gitleaks secret scanning workflow
- Issue templates for bug reports and feature requests
- Pull request template
- Dependabot configuration for automated dependency updates
- CODEOWNERS file
- `.editorconfig` for consistent formatting across editors

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
