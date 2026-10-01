# Contributing

Thank you for helping build PHAEMOS.

> [!NOTE]
> All development happens in [phaemos/phaemos](https://github.com/phaemos/phaemos). The component repositories (`backend`, `frontend`, `firmware`, `hardware`, `infra`, `client` and `edge`) are read-only copies published from here, so open issues and pull requests in this repository.

## Where to start

- Issues labelled [`good first issue`](https://github.com/phaemos/phaemos/labels/good%20first%20issue) are a gentle way in.
- The [roadmap board](https://github.com/orgs/phaemos/projects/1) and the [milestones](https://github.com/phaemos/phaemos/milestones) show what is planned and in which order.
- [docs/development.md](docs/development.md) covers running the stack locally, the simulator and the tests.

## How to contribute

1. Pick an issue or open one, so the change is agreed before the work starts.
2. Branch from an up-to-date `main`, named as in the table below.
3. Keep each pull request to one focused change.
4. Add an entry to `CHANGELOG.md` under `[Unreleased]` when the change affects users or other contributors.
5. Open a pull request with the template and link the issue with `Closes #N`.
6. Every CI check must pass before merge. Pull requests are squash merged.

## Branch naming

| Prefix | When to use |
| --- | --- |
| `feat/short-description` | New capability |
| `fix/short-description` | Bug correction |
| `docs/short-description` | Documentation only |
| `refactor/short-description` | Internal restructure |
| `chore/short-description` | Tooling or configuration work |

## Commit messages

```text
type: short description
```

- Supported types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`, `perf` and `revert`.
- Keep the subject to 72 characters or fewer, in the imperative mood (`add` not `added`) with no full stop.
- An optional body, separated by a blank line, explains why the change was made rather than how.

## Style

- UK English in prose, comments and names: `colour`, `organisation`, `licence` as a noun.
- No Oxford comma: write "x, y and z".
- No em dashes or en dashes. Use a hyphen or rewrite the sentence.
- Comments explain why rather than what, written in the first person ("I debounce this because...").
- Backend: PEP 8, checked with `ruff check backend/`. Dashboard: TypeScript strict mode, checked with `npm run lint`.
- Edge gateway: `cargo fmt` and `cargo clippy`. Go CLI: `gofmt` and `go vet`.
- Run `make lint` and `make test` before pushing.

## Email addresses

Pages and templates that show a contact address use the right phaemos.com address:

| Address | Use for |
| --- | --- |
| `contact@phaemos.com` | Legal pages and general enquiries |
| `hello@phaemos.com` | The landing page and marketing copy |
| `dev@phaemos.com` | Technical queries and security disclosures |
| `support@phaemos.com` | User support pages |
| `no-reply@phaemos.com` | Automated application emails, with the reply-to set to `support@phaemos.com` |

Never put a personal email address anywhere in this repository.

## Questions and discussion

Use [GitHub Discussions](https://github.com/phaemos/phaemos/discussions) for setup questions, architecture questions, feature ideas and anything you have built with PHAEMOS. Issues are for confirmed bugs and accepted feature work.

## Reporting bugs

Use the issue forms: **Bug report** for something broken, **Feature request** for a new capability.

> [!IMPORTANT]
> Never report a security vulnerability in a public issue. Follow [SECURITY.md](SECURITY.md) or use the [security policy](https://github.com/phaemos/phaemos/security/policy) to report it privately.

## Licence

By contributing you agree that your work is released under the same licence as the part of PHAEMOS it changes. [NOTICE.md](NOTICE.md) explains which licence covers what.
