# API stability

What `/api/v1` promises and how a change is announced.

- **v1 changes by addition only.** A new route, an optional field, a new code or a new optional query parameter does not need a
  new version. Clients must ignore fields and codes they do not know.
- **A removal is announced for 90 days.** The old route answers with `Deprecation: true`, a `Sunset` date and a `Link` to its
  successor (`rel="successor-version"`) and is marked `deprecated` in [`openapi.json`](openapi.json). The change is in the
  changelog under "Breaking". After the sunset date the route is removed.
- **Frozen for the life of v1:** `POST /api/v1/telemetry` (it may gain optional fields and nothing else) and the two firmware
  routes, because firmware in the field stores the URL and the body. `GET /status` and the live socket follow the same rule.
- **Experimental routes** are marked so in their description and may change without notice.
- **Versions.** The release (for example 2.5.0) is shown at `GET /` as `version` and is the version of the OpenAPI document. The
  API version is the path prefix (`v1`, `api_version` at `GET /`). They move independently: a release can add routes to v1.
- **Paths have no trailing slash.** `/api/v1/devices/` is a 404 (`not_found`), never a redirect. Use the paths as the reference spells them.
- **Error codes** are part of the contract and the sentences are not. A code is never reused for a different situation.

## Deprecated now

The account routes moved out of `/auth` in this release. The old paths still work, answer with the headers above and go on
**Saturday 20 February 2027**.

| Old path | New path |
| --- | --- |
| `GET /auth/users` | `GET /users` |
| `POST /auth/users/{id}/deactivate`, `reactivate`, `clear-two-step`, `reset-link`, `PATCH /auth/users/{id}/role`, `DELETE /auth/users/{id}` | the same under `/users/{id}` |
| `GET /auth/invitations`, `DELETE /auth/invitations/{id}` | `GET /invitations`, `DELETE /invitations/{id}` |
| `POST /auth/invite` | `POST /invitations` |
| `GET`, `POST /auth/tokens`, `DELETE /auth/tokens/{id}` | `GET`, `POST /tokens`, `DELETE /tokens/{id}` |
| `GET /health/summary` | `GET /fleet/summary` |

An alias runs the same code as its new path, so it has exactly the same auth class, limit and proof.
