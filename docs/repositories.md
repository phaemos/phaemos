# Repositories

`phaemos/phaemos` is the single source of truth. Issues, pull requests, discussions, milestones and the
project board all live here. Each component folder is also published to its own read-only repository,
so a component can be browsed, cloned or forked on its own.

## Published components

| Folder | Published to |
| --- | --- |
| `backend/` | [phaemos/backend](https://github.com/phaemos/backend) |
| `frontend/` | [phaemos/frontend](https://github.com/phaemos/frontend) |
| `firmware/` | [phaemos/firmware](https://github.com/phaemos/firmware) |
| `hardware/` | [phaemos/hardware](https://github.com/phaemos/hardware) |
| `edge/` | [phaemos/edge](https://github.com/phaemos/edge) |
| `client/` | [phaemos/client](https://github.com/phaemos/client) |
| `infra/` | [phaemos/infra](https://github.com/phaemos/infra) |

`docs/` and `assets/` are not published on their own. The organisation profile and the default community
files live in [phaemos/.github](https://github.com/phaemos/.github).

## How publishing works

The `Publish components` workflow (`.github/workflows/split.yml`) runs on every push to `main`. For each
folder it takes that folder's history with `git subtree split` and pushes it to the component's `main`
branch, so each published repository carries the real commit history of its own files.

> [!IMPORTANT]
> The published repositories are read-only. Anything pushed to them directly is overwritten on the next
> publish. Open issues and pull requests here instead.

## Layout

```text
phaemos/
├── backend/        FastAPI routes, models, schemas, services, the ML model and the pytest suite
├── frontend/       Next.js App Router pages, dashboard, tickets and admin components
├── firmware/       Code for the ESP32, STM32 Black Pill, Arduino Nano and Pico 2W nodes
├── hardware/       Wiring tables, schematics, PCB layouts and the parts inventory
├── edge/           phaemos-edge, the Rust store-and-forward gateway
├── client/         python/ (SDK and phaemos-sim) and go/ (phaemosctl)
├── infra/          Docker Compose stack, Prometheus and Grafana, SQL reports and seed data
├── docs/           This documentation
├── assets/         Logos, colours and the social preview card
├── Makefile        make dev, test, lint, build, migrate, seed and docs
└── docker-compose.yml   includes infra/docker-compose.yml so root commands keep working
```

## Adding a component

1. Create the folder with its own README, LICENSE and CHANGELOG, so the published copy stands on its own.
2. Create the empty repository in the organisation and give the publishing token write access to it.
3. Add the folder to the `folder` matrix in `split.yml`.
4. Add a row to the table above and to the main README.
