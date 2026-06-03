# Security Policy

## Supported Versions

Only the latest commit on `main` is actively maintained.

| Version | Supported |
| ------- | --------- |
| Latest on `main` | Yes |
| Older commits | No |

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Report vulnerabilities privately via [GitHub Security Advisories](https://github.com/zaccesss/phaemos/security/advisories/new). This keeps the disclosure private until a fix is ready.

If you cannot use Security Advisories, email [dev@phaemos.com](mailto:dev@phaemos.com) with:

- A clear description of the vulnerability
- Steps to reproduce it
- The potential impact
- Any suggested fix if you have one

You will receive a response within 72 hours. Once the issue is confirmed and a fix is prepared, a public disclosure will be made alongside the patched release.

## Implemented Security Controls

See [docs/security.md](docs/security.md) for the full table of 27 implemented security measures, including JWT auth, refresh tokens, OAuth, 2FA/TOTP, rate limiting, brute-force lockout, security headers, GDPR endpoints, WebSocket auth, CORS configuration and audit logging.

## Scope

This policy covers the backend API, frontend application and firmware code within this repository. Third-party dependencies are out of scope but should be reported to the relevant upstream maintainers.

## Responsible Disclosure

Please give reasonable time for a fix to be released before any public disclosure. We appreciate responsible reporting.
