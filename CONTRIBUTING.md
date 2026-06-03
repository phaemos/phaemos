# Contributing

Thank you for taking the time to contribute to PHAEMOS.

---

## Workflow

1. Create or pick an issue from the issue tracker.
2. Create a branch from `main` following the naming convention below.
3. Make focused changes with clear commit messages.
4. Update `CHANGELOG.md` under `[Unreleased]` for public-facing changes only.
5. Push your branch and open a pull request using the PR template.
6. Wait for CI to pass, then merge.

---

## Branch Naming

| Prefix                       | When to use            |
| ---------------------------- | ---------------------- |
| `feat/short-description`     | New capability         |
| `fix/short-description`      | Bug correction         |
| `docs/short-description`     | Documentation only     |
| `refactor/short-description` | Internal restructure   |
| `chore/short-description`    | Tooling or config work |

---

## Commit Message Format

```text
type: short description
```

Subject line must be 72 characters or fewer, written in the imperative mood
(`add` not `added`) with no full stop at the end.

Supported types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`,
`perf` and `revert`.

An optional body (separated by a blank line) should explain **why** the change
was made, not how.

---

## Pull Request Checklist

- Title follows `type: short description`
- Summary section explains what changed and why
- Changes are listed as short bullet points
- Steps to test are included
- Related issue is linked with `closes #NUMBER`

---

## Code Standards

- All new code must include comments explaining non-obvious logic.
- **Write all comments in first person.** "I use this to..." not "Uses..." or "This function...".
- Use UK English in all prose, comments and variable names (colour not color, organisation not organization).
- No Oxford commas in prose or commit messages.
- No em dashes or en dashes - use hyphens instead.
- Backend: follow PEP 8. Run `ruff check backend/` before committing.
- Frontend: TypeScript strict mode. Run `npm run lint` before committing.

---

## Reporting Issues

Use the issue templates provided:

- **Bug report** for something that is broken.
- **Feature request** for a new capability.

Do not open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md) or the [security policy page](https://phaemos.com/security) for responsible disclosure instructions.

---

## Email Aliases

When adding or editing pages that include contact email addresses, use the correct phaemos.com alias:

| Alias | Use for |
| ----- | ------- |
| `contact@phaemos.com` | Legal pages, general enquiries |
| `hello@phaemos.com` | Landing page, marketing-facing copy |
| `dev@phaemos.com` | Technical queries, security disclosures |
| `support@phaemos.com` | User-facing support pages |
| `no-reply@phaemos.com` | Automated application emails (set reply-to: support@) |

Never use a personal email address in any file in this repository.

---

## Licence

By contributing you agree that your work will be released under the
[GNU Affero General Public License v3](LICENSE).
