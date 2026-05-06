# Contributing

Thank you for taking the time to contribute to PHAEMOS.

---

## Workflow

1. Create or pick an issue from the issue tracker.
2. Create a branch from `main` following the naming convention below.
3. Make focused changes with clear commit messages.
4. Push your branch and open a pull request using the PR template.
5. Wait for review and address any feedback.

---

## Branch Naming

| Prefix                       | When to use            |
| ---------------------------- | ---------------------- |
| `feature/short-description`  | New capability         |
| `fix/short-description`      | Bug correction         |
| `docs/short-description`     | Documentation only     |
| `refactor/short-description` | Internal restructure   |
| `chore/short-description`    | Tooling or config work |

---

## Commit Message Format

```
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
- Use UK English in all prose, comments and variable names
  (e.g. `colour` not `color`, `organisation` not `organization`).
- No Oxford commas in prose.
- No em dashes or en dashes; use hyphens instead.
- Backend: follow PEP 8. Run `ruff check` before committing.
- Frontend: TypeScript strict mode. Run `npm run lint` before committing.

---

## Reporting Issues

Use the issue templates provided:

- **Bug report** for something that is broken.
- **Feature request** for a new capability.

---

## Licence

By contributing you agree that your work will be released under the
[MIT Licence](LICENSE).
