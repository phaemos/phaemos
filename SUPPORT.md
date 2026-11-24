# Support

## Getting help

**Platform status and incidents:** The status page at status.phaemos.com goes live with the [Launch milestone](https://github.com/phaemos/phaemos/milestone/3). Until then, outages and incidents are announced in [GitHub Discussions](https://github.com/phaemos/phaemos/discussions).

**Questions and discussion:** Start a thread in [GitHub Discussions](https://github.com/phaemos/phaemos/discussions). This is the primary help channel for setup questions, usage questions and feature ideas.

**Community chat:** join the [PHAEMOS Discord server](https://discord.gg/C6WRDzSrG). Ask in `help` for software and in `hardware` for build questions so the answer helps the next person. Bugs and decisions still live on GitHub.

**Private help:** type `/ticket` on the server for an account problem or a privacy request or a conduct matter. Only you and the moderators can read it. We aim to reply within two days. Nobody is on call.

**Bugs and confirmed issues:** Open an issue on the [GitHub repository](https://github.com/phaemos/phaemos/issues). Use the bug report template and include reproduction steps.

**Security vulnerabilities:** Do not open a public issue. See [SECURITY.md](SECURITY.md) for the responsible disclosure process.

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
- [docs/development.md](docs/development.md) - Running locally, the smoke test, the simulator and the test commands
- The browsable documentation site at docs.phaemos.com goes live with the Launch milestone. `make docs` serves it locally today
- `http://localhost:8000/docs` - Interactive Swagger UI when the backend is running locally

---

## Common issues

**Database empty after `docker compose down -v`:**
The `-v` flag deletes the `postgres_data` volume. Plain `docker compose down` and `docker compose stop` both keep it. After a wipe, re-run migrations with `make migrate`.

**Login blocked after 5 failed attempts:**
Wrong passwords and wrong authentication codes both count. The account is never locked. The place you sign in from waits 30 seconds after five wrong tries and the wait doubles up to 15 minutes. Wait or sign in from a browser you have used before.

**Frontend shows blank screen:**
Ensure `frontend/.env.local` contains `NEXT_PUBLIC_API_URL=http://localhost:8000`. Run:

```bash
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local
```

**Contact form not sending emails:**
Check that `RESEND_API_KEY` and `FROM_EMAIL` are set in the API environment and that the sending domain is verified in Resend. Outside development the contact endpoint answers 503 when the key is missing or Resend refuses the message. In development with no key it logs the message and answers 204.

**Rate limit hit on login:**
The login endpoint is limited to 5 requests per minute per IP. Wait one minute and try again. If you are behind a shared NAT, the limit is per the shared IP.
