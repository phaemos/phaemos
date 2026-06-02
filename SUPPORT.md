# Support

PHAEMOS is an internal research and development project. There is no formal commercial support.

## Getting Help

**Bugs and feature requests:** Open an issue on the GitHub repository.

**Security vulnerabilities:** Do not open a public issue. See [SECURITY.md](SECURITY.md) for the responsible disclosure process.

**Questions:** Raise a GitHub Discussion or contact the maintainer directly via the email listed on the GitHub profile.

## Self-Help Resources

- [README.md](README.md) - Project overview and quick start
- [docs/deployment.md](docs/deployment.md) - Full deployment guide (Docker Compose)
- [docs/api-reference.md](docs/api-reference.md) - Complete API reference
- [docs/architecture.md](docs/architecture.md) - System architecture overview
- [docs/sensor_reference.md](docs/sensor_reference.md) - Sensor wiring and data dictionary
- [docs/VERIFICATION.md](docs/VERIFICATION.md) - Feature completion checklist
- `http://localhost:8000/docs` - Interactive Swagger UI when the backend is running

## Common Issues

**Backend crashes on startup after `docker compose down`:**
The postgres data volume is wiped by `docker compose down`. Use `docker compose stop` to preserve data. After a wipe, re-seed with `make seed`.

**Login blocked after 5 failed attempts:**
The account is locked for 15 minutes. Wait or ask an admin to reset the `locked_until` column in the DB directly.

**Frontend shows blank screen:**
Ensure `frontend/.env.local` contains `NEXT_PUBLIC_API_URL=http://localhost:8000`. Run `echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local` on a fresh clone.
