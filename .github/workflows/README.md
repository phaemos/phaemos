# Workflows

| Workflow | Runs on | What it does |
| --- | --- | --- |
| [`ci.yml`](ci.yml) | Push to `main`, every pull request | Lints, tests and builds the backend and frontend |
| [`codeql.yml`](codeql.yml) | Push to `main`, every pull request, weekly schedule | CodeQL static analysis |
| [`gitleaks-scan.yml`](gitleaks-scan.yml) | Push to `main`, every pull request | Scans for committed secrets |
| [`markdownlint.yml`](markdownlint.yml) | Push to `main`, every pull request | Lints every markdown file against [`.markdownlint.json`](../../.markdownlint.json) |
| [`deploy.yml`](deploy.yml) | After CI passes on `main` | Triggers the backend deploy hook on Render |
| [`release.yml`](release.yml) | Tag push matching `v*` | Validates the CHANGELOG entry and creates the GitHub Release |
| [`biweekly-security-issue.yml`](biweekly-security-issue.yml) | Fortnightly schedule | Opens a recurring reminder issue for a security review pass |

`codeql.yml`, `markdownlint.yml` and `biweekly-security-issue.yml` are runnable manually via `workflow_dispatch` from the Actions tab. The rest only run on their triggers above.
