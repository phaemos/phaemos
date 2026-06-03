# Support

## Getting help

**Platform status and incidents:** Check [status.phaemos.com](https://status.phaemos.com) first during an outage. Subscribe to incident updates on the status page.

**Questions and discussion:** Start a thread in [GitHub Discussions](https://github.com/zaccesss/phaemos/discussions). This is the primary help channel for setup questions, usage questions and feature ideas.

**Bugs and confirmed issues:** Open an issue on the [GitHub repository](https://github.com/zaccesss/phaemos/issues). Use the bug report template and include reproduction steps.

**Security vulnerabilities:** Do not open a public issue. See [SECURITY.md](SECURITY.md) for the responsible disclosure process.

**Contact form:** Use the [contact form](https://phaemos.com/contact) for general enquiries.

**General enquiries by email:** [contact@phaemos.com](mailto:contact@phaemos.com)

**User support by email:** [support@phaemos.com](mailto:support@phaemos.com)

---

## Self-help resources

- [README.md](README.md) - Project overview and quickstart
- [docs/deployment.md](docs/deployment.md) - Full VPS, Vercel and DNS setup guide
- [docs/api-reference.md](docs/api-reference.md) - Complete API reference
- [docs/architecture.md](docs/architecture.md) - System architecture overview
- [docs/sensor_reference.md](docs/sensor_reference.md) - Sensor wiring and data dictionary
- [docs/VERIFICATION.md](docs/VERIFICATION.md) - Feature completion checklist
- [docs.phaemos.com](https://docs.phaemos.com) - Browsable documentation site
- `http://localhost:8000/docs` - Interactive Swagger UI when the backend is running locally

---

## Common issues

**Backend crashes on startup after `docker compose down`:**
The Postgres data volume is wiped by `docker compose down`. Use `docker compose stop` to preserve data. After a wipe, re-run migrations with `make migrate`.

**Login blocked after 5 failed attempts:**
The account is locked for 15 minutes. Wait, or ask an admin to clear the `locked_until` column in the database directly.

**Frontend shows blank screen:**
Ensure `frontend/.env.local` contains `NEXT_PUBLIC_API_URL=http://localhost:8000`. Run:

```bash
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local
```

**Contact form not sending emails:**
Check that `SMTP_HOST`, `SMTP_USER` and `SMTP_PASS` are set in `.env`. The contact endpoint is a silent no-op when `smtp_host` is empty - no error is returned but no email is sent.

**Rate limit hit on login:**
The login endpoint is limited to 5 requests per minute per IP. Wait one minute and try again. If you are behind a shared NAT, the limit is per the shared IP.
