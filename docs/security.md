# Security Measures

Full record of security controls implemented in PHAEMOS. Updated after every session that adds or changes a security-relevant feature.

Last updated: 2026-10-01

---

## Summary Table

| # | Measure | Layer | Status | PR |
| - | ------- | ----- | ------ | -- |
| 1 | JWT authentication (HS256, 15-min access token expiry) | Backend | Done | PR 55 |
| 2 | Bcrypt password hashing (passlib) | Backend | Done | PR 55 |
| 3 | Role-based access control (admin / technician / viewer) | Backend | Done | PR 55 |
| 4 | Rate limiting on POST /auth/login (5/min via slowapi) | Backend | Done | PR 74 |
| 5 | Brute-force lockout (5 failures = 15-min lock, stored in DB). Wrong passwords and wrong two-factor codes both count | Backend | Done | PR 74 |
| 6 | Password strength validation (8+ chars, 1 uppercase, 1 digit) | Backend | Done | PR 74 |
| 7 | WebSocket JWT auth - validate before accept(), access tokens from a live session only, close 1008 on fail | Backend | Done | PR 74 |
| 8 | Telemetry GET and export require Bearer token | Backend | Done | PR 74 |
| 9 | Firmware upload 2 MB cap | Backend | Done | PR 74 |
| 10 | CORS locked to explicit origin list (no wildcard) | Backend | Done | PR 74 |
| 11 | API key rotation endpoint POST /devices/{device_id}/rotate-key | Backend | Done | PR 74 |
| 12 | Audit logging on all mutating routes | Backend | Done | PRs 55-56 |
| 13 | SQLAlchemy parameterised queries (no raw string interpolation) | Backend | Done | All |
| 14 | SQLAlchemy text() wrapping for raw audit_service inserts | Backend | Done | PR 74 |
| 15 | Last login timestamp tracking | Backend | Done | PR 74 |
| 16 | Next.js edge middleware route guard (all routes require valid token cookie) | Frontend | Done | PR 75 |
| 17 | JWT stored in httpOnly-style cookie for middleware + localStorage for API | Frontend | Done | PR 75 |
| 18 | WS client skips retry on close 1008 - prevents token-expiry loop | Frontend | Done | PR 77 |
| 19 | Refresh token - 7-day httpOnly cookie, separate `type:"refresh"` JWT claim, 15-min access tokens with `type:"access"` | Backend | Done | PR 89 |
| 20 | 2FA / TOTP - optional per-user enrolment with a QR code, confirm before activation. Once enrolled it is required at every sign-in, password and OAuth alike, through a 5-minute challenge token. Each code is accepted once | Backend | Done | PR 93 |
| 21 | OAuth (Google + GitHub) - `state` checked against a short-lived cookie, only provider-verified emails sign in or link accounts, no tokens in redirect URLs | Backend | Done | PR 92 |
| 22 | Rate limiting - slowapi per-IP on login (5/min), register (10/hr), password change (10/min), contact (3/hr), ML retrain | Backend | Done | PR 99 |
| 23 | Rate limiting proxy headers - X-Real-IP from Nginx used as key, trusted only from addresses in `TRUSTED_PROXIES` | Backend | Done | PR 135 |
| 24 | Security headers - X-Frame-Options: DENY, X-Content-Type-Options: nosniff, Referrer-Policy: strict-origin-when-cross-origin, Permissions-Policy: camera=(), microphone=(), geolocation=() | Frontend | Done | PR 103 |
| 25 | Cookie consent - GDPR-compliant banner, GA4 loads only after accept, consent stored in localStorage | Frontend | Done | PR 114 |
| 26 | GDPR - DELETE /auth/me anonymises tickets and wipes personal data; GET /auth/me/export returns full JSON bundle | Backend | Done | PR 94 |
| 27 | Input validation - Pydantic Field(max_length=...) on all string inputs in device, ticket and webhook schemas prevents storage exhaustion | Backend | Done | PR 135 |
| 28 | Session versioning - every token carries the account's session version; changing the password or two-factor settings ends every other session | Backend | Done | PR 310 |
| 29 | Device permissions - admins manage every device, technicians their own or unassigned devices, viewers are read-only; key rotation follows the same rule | Backend | Done | PR 310 |
| 30 | Container ports bound to 127.0.0.1 so only Nginx faces the internet, since Docker's published ports bypass a host firewall | Infra | Done | PR 310 |

---

## Notes

**JWT storage dual-write:** The token is written to both `localStorage` (for the axios interceptor on API calls) and a plain cookie (for the Next.js edge middleware). The cookie is not httpOnly because the edge middleware reads it at the JS level. This is a known trade-off for a single-developer internal tool - a future hardening step would move to a server-side session or a separate refresh token flow.

**Rate limiting in Docker:** slowapi uses the client IP for rate limiting. If running behind a reverse proxy, set `FORWARDED_ALLOW_IPS` or configure `X-Forwarded-For` trust to avoid all requests appearing as the proxy IP.

**CORS:** `allowed_origins` is set in `app/config.py` via the `CORS_ORIGINS` environment variable. The default allows `http://localhost:3000` for local development only. Set this to the production frontend URL before deploying.
