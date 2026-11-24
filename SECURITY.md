# Security Policy

## Supported Versions

Only the latest commit on `main` is actively maintained.

| Version | Supported |
| ------- | --------- |
| Latest on `main` | Yes |
| Older commits | No |

## Reporting a Vulnerability

> [!IMPORTANT]
> Do not open a public issue or post in Discord. Report privately so the problem stays undisclosed until a fix is ready.

- Use [GitHub private vulnerability reporting](https://github.com/phaemos/phaemos/security/advisories/new).
- Or email [security@phaemos.com](mailto:security@phaemos.com) with a description and the steps to reproduce and the likely impact. A suggested fix helps.

The Discord server is not a reporting route. Not even a direct message or a `/ticket` is read as a security report. We remove posts that describe a vulnerability.

We reply within 72 hours. Once a fix is ready we publish a disclosure with the patched release.

## Implemented Security Controls

See [docs/security.md](docs/security.md) for the record of implemented security measures, including JWT auth, refresh tokens, OAuth, 2FA/TOTP, rate limiting, brute-force lockout, security headers, account data export and deletion, WebSocket auth, CORS configuration and an audit log of selected changes. The public security page lists the controls in place and the known limits.

## Scope

In scope:

- The backend API: authentication and authorisation and device keys and API tokens and replay protection and rate limits
- The dashboard, including cross-site scripting and unsafe handling of data from nodes
- The firmware on the ESP32 and STM32 and Arduino Nano and Pico 2W nodes, including how keys and Wi-Fi details are stored
- The edge gateway, its disk spool and its forwarding
- The Python SDK and `phaemosctl`
- The Docker Compose stack and deploy scripts in `infra/`, including secrets exposed by default configuration
- The Discord tooling in `discord/`: the GitHub relay and the slash command worker

Out of scope:

- Attacks that need physical access to a node or the machine it monitors
- Denial of service against a deployment exposed without a reverse proxy or rate limiting
- Vulnerabilities in third-party dependencies with no demonstrated impact on PHAEMOS (report those upstream)

## Responsible Disclosure

Please give reasonable time for a fix to be released before any public disclosure. We appreciate responsible reporting.
