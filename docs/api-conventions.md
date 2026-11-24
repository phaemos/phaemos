# API conventions

The rules every route follows, so a client can guess the second route from the first. They are enforced by tests
(`backend/tests/test_api_guards.py` and `backend/tests/test_access_tokens.py`) and the generated
[`openapi.json`](openapi.json) and [route table](api-routes.md) come from the code, so they cannot drift.

## Glossary

| Word | Means | Use it for |
| --- | --- | --- |
| device | the API's noun for a machine that posts readings | paths, fields and code (`/devices`, `device_id`) |
| machine | the same thing, in the words people use | prose, the dashboard and the command line tool's help |
| device key | the credential a device sends as `X-API-Key` | everywhere (the older name "API key" for it is retired) |
| API token | a `pht_...` credential for a script, a service or the command line tool | everywhere (not "access token", which only ever means the short-lived token of a signed-in session) |
| access token | the 15 minute token a signed-in session sends as a bearer | the dashboard's sign-in |
| service account | an account owned by an integration. It has a role and API tokens and cannot sign in | scripts that must outlive their author |
| two-step | the second sign-in factor | every sentence a person reads. The paths `/2fa/*` and the fields `mfa_required`, `mfa_token` and `totp_enabled` keep their names for v1 |
| proof | the password (and two-step code) asked for before a dangerous action | `proof_required`, `proof_wrong` |

## Paths

`/api/v1/<plural-noun>` and `/<plural-noun>/{id}`, in kebab-case. A thing that belongs to another is filtered by query
(`GET /alerts?device_id=`) and never by a path segment on the child. Actions are `POST /<noun>/{id}/<verb>`. A path parameter
is `{<noun>_id}`. Ids are UUID strings (an API token's id is 12 hex characters). Account security is under `/auth`. Account
administration is outside it: `/users`, `/invitations`, `/service-accounts` and `/tokens`.

## Methods and status

GET 200. POST create 201 with the resource. POST action 200 with the resource or 202 with `{"message": ...}` when the work
continues. PATCH 200 with the resource. DELETE 204. No new PUT.

| Status | Meaning |
| --- | --- |
| 400 | proof missing or wrong (only) |
| 401 | no credential or a bad or expired one |
| 403 | may read, may not do this (or a session is needed) |
| 404 | does not exist or the caller may not read it |
| 409 | conflicts with the current state: a duplicate, the last admin, a stale replay |
| 413 | too large |
| 422 | the request is malformed or a value is not acceptable |
| 429 | limited, always with `Retry-After` |
| 503 | a dependency is down or the work timed out |

A failure is never a 200. `GET /status` is the one exception: it answers 200 with `"status": "degraded"` because uptime
monitors read the body.

## Errors

Every non-2xx answer has one shape:

```json
{"code": "device_not_found", "detail": "No such device", "request_id": "9f2c..."}
```

`detail` is always a sentence for a person. `code` is stable snake_case and is the contract: **read the code and never match the
sentence**, which can change. Validation adds `errors`, a list of `{"loc", "msg", "type"}`. A success body never uses `detail`
(it uses `message`; a few routes repeat `detail` for one release because the dashboard reads it).

`request_id` is also the `X-Request-ID` header on every answer. Send your own `X-Request-ID` (8 to 64 characters of letters,
digits, dot, underscore or hyphen) to follow a call through the logs. Anything else is replaced.

An error raised the old way (`HTTPException`) is still sent in this shape with a code taken from its status: `bad_request`,
`unauthenticated`, `forbidden`, `not_found`, `conflict`, `unprocessable`, `rate_limited`, `internal_error`...

### Codes

The codes are one list in `backend/app/errors.py` (`Code`). Each is used for one situation.

**Generic, used when a status has no more specific code**

| Code | When |
| --- | --- |
| `bad_request` | Bad request |
| `unauthenticated` | Unauthenticated |
| `forbidden` | Forbidden |
| `not_found` | Not found |
| `method_not_allowed` | Method not allowed |
| `conflict` | Conflict |
| `payload_too_large` | Payload too large |
| `unprocessable` | Unprocessable |
| `rate_limited` | Rate limited |
| `internal_error` | Internal error |
| `not_implemented` | Not implemented |
| `bad_gateway` | Bad gateway |
| `unavailable` | Unavailable |
| `gateway_timeout` | Gateway timeout |
| `database_error` | Database error |

**Request validation**

| Code | When |
| --- | --- |
| `validation_failed` | the body, query or path did not fit. `errors` says where |
| `nul_character` | text holding a NUL character, refused before it reaches a handler |
| `invalid_filter` | a filter value that is not one of the allowed values |
| `invalid_range` | a time range or window that is reversed or too wide |
| `body_too_large` | a body over the route's cap |

**Credentials and sessions**

| Code | When |
| --- | --- |
| `token_invalid` | a bearer token that is unknown, malformed, expired or revoked |
| `session_ended` | the session or its access token is no longer valid |
| `refresh_missing` | no refresh cookie was sent |
| `sign_in_again` | a two-step step whose challenge is gone or has expired |
| `invalid_credentials` | a wrong password, an unknown address or an account that cannot sign in |
| `origin_not_allowed` | a cookie route called from a page on another origin |
| `device_key_invalid` | an unknown or revoked device key |
| `account_disabled` | the account is deactivated |
| `session_required` | a route a token may never call. Sign in with a session |
| `scope_too_low` | the API token's scope does not allow this method or route |
| `admin_required` | the route is for admins |
| `registration_closed` | Registration closed |
| `provider_not_configured` | Provider not configured |
| `provider_error` | the sign-in provider answered with an error |
| `provider_link_refused` | Provider link refused |
| `provider_already_linked` | Provider already linked |
| `email_from_provider` | the email comes from the sign-in provider and cannot change here |
| `email_in_use` | the address is already registered |
| `oauth_state_invalid` | the provider return was not started in this browser or has expired |

**Proof of ownership**

| Code | When |
| --- | --- |
| `proof_required` | a password is needed and was not sent |
| `proof_wrong` | the password or code sent is wrong |
| `code_required` | a two-step code is needed and was not sent |
| `provider_proof_required` | sign in through the provider again, within 5 minutes |
| `proof_rate_limited` | too many proofs in a minute |
| `no_password` | the account has no password |
| `password_wrong` | the current password given to change it is wrong |

**Two-step**

| Code | When |
| --- | --- |
| `two_step_already_on` | Two step already on |
| `two_step_not_on` | Two step not on |
| `two_step_not_started` | confirm was called before enable |
| `two_step_code_wrong` | Two step code wrong |

**Accounts and administration**

| Code | When |
| --- | --- |
| `user_not_found` | User not found |
| `session_not_found` | Session not found |
| `self_action_refused` | an admin acting on their own account where that is refused |
| `last_admin` | Last admin |
| `account_deactivated` | the target account is deactivated |
| `owns_machines` | hand the account's machines to someone first |
| `reset_link_invalid` | Reset link invalid |
| `reset_link_recent` | one was sent a moment ago |
| `email_not_sent` | Email not sent |
| `email_changes_limit` | Email changes limit |
| `invitation_not_found` | Invitation not found |
| `invitation_invalid` | unknown, expired or cancelled |
| `invitation_used` | Invitation used |
| `account_exists` | Account exists |
| `service_account_refused` | a service account cannot do this (sign in, change a password...) |
| `export_failed` | Export failed |

**API tokens**

| Code | When |
| --- | --- |
| `token_not_found` | Token not found |
| `no_token_in_use` | DELETE /tokens/current from a session, which has no API token |
| `token_limit` | 20 live tokens already |
| `token_scope_forbidden` | an admin token asked for by someone who is not an admin |
| `token_account_rate_limited` | Token account rate limited |

**Phone**

| Code | When |
| --- | --- |
| `phone_missing` | Phone missing |
| `phone_code_wrong` | Phone code wrong |
| `phone_codes_limit` | Phone codes limit |
| `texts_not_set_up` | Texts not set up |
| `text_not_sent` | Text not sent |

**Machines, readings, alerts, tickets and the rest**

| Code | When |
| --- | --- |
| `device_not_found` | Device not found |
| `device_access_denied` | may read the machine, may not change it |
| `owner_not_found` | Owner not found |
| `admin_only_field` | a field only an admin may change |
| `key_rotation_forbidden` | Key rotation forbidden |
| `telemetry_not_found` | Telemetry not found |
| `alert_not_found` | Alert not found |
| `rule_not_found` | Rule not found |
| `ticket_not_found` | Ticket not found |
| `ticket_access_denied` | Ticket access denied |
| `assignee_not_found` | Assignee not found |
| `assignee_refused` | Assignee refused |
| `webhook_not_found` | Webhook not found |
| `webhook_url_refused` | Webhook url refused |
| `window_not_found` | Window not found |
| `firmware_not_found` | Firmware not found |
| `firmware_file_invalid` | Firmware file invalid |
| `firmware_too_large` | Firmware too large |
| `nothing_to_score` | Nothing to score |

**Ingest answers (the wire contract of POST /telemetry)**

| Code | When |
| --- | --- |
| `replay_stale` | a reading older than the device's last accepted one |
| `replay_pair_missing` | a device that signs its readings with boot and seq sent a reading without them |
| `counter_out_of_range` | a boot or seq no machine could reach |
| `observed_at_too_old` | an observed_at further back than a backlog may reach |
| `replay_counter_back` | the counter went back without a new boot |
| `replay_held` | held after a counter reset until an admin accepts it |
| `device_rate_limited` | one device posting faster than its allowance |
| `batch_too_large` | more readings in a batch than one request may carry |

**Limits and reads**

| Code | When |
| --- | --- |
| `sign_in_slowed` | too many failed sign-ins for this account or source |
| `read_busy` | too many heavy reads at once or in a minute |
| `retrain_cooldown` | Retrain cooldown |
| `query_too_slow` | a read took too long. Ask for less |

**Contact form and services**

| Code | When |
| --- | --- |
| `challenge_failed` | the bot check did not pass |
| `challenge_unavailable` | Challenge unavailable |
| `contact_unavailable` | Contact unavailable |
| `contact_not_sent` | Contact not sent |

**Service accounts, idempotency, stability**

| Code | When |
| --- | --- |
| `idempotency_key_reused` | the same key with a different body |
| `idempotency_in_progress` | the first request with this key is still running |
| `endpoint_removed` | Endpoint removed |

**Webhooks**

| Code | When |
| --- | --- |
| `webhook_template_invalid` | a template that uses a placeholder that does not exist |
| `webhook_not_json` | the json format was asked for and the body is not JSON |
| `webhook_delivery_failed` | the test delivery did not reach the address |

## Bodies

snake_case. Times are UTC ISO 8601 ending in `Z`, with names ending in `_at`. Durations carry the unit as `_s`, sizes `_bytes`.
A fixed set of values is a `Literal` on the request and the response. A nullable field is always present as `null`. Every route
with a body has a response model.

## Updates

PATCH only. A field left out is kept. `null` clears a field that can be cleared and is a 422 on any other
(`app/patching.py`, `apply_patch`). PUT is kept only as an alias where it already existed.

## Lists

`limit` (default 50, maximum 200 unless the route says more) and `offset` (up to 100,000), through one dependency. `skip` is an
older name for `offset` and is accepted for this release. The order is stable and ends in `id`. Every paged list sends
`X-Total-Count`. Time filters are `from` and `to`, read as UTC when no zone is given. An unknown filter value is a 422. A list
that grows without bound (telemetry, alerts) also takes a keyset filter (`before`).

## Limits

Every route has a limit. A route with none of its own is counted by the default of its class:

| Class | Counted by | Default |
| --- | --- | --- |
| anonymous (no credential) | address (IPv6 by /64) | `RATE_LIMIT_ANONYMOUS`, 120 a minute |
| signed in (a session or an API token) | account or token | `RATE_LIMIT_SIGNED_IN`, 600 a minute |
| device key | the device, by its own allowance | not in the default (ingest allowance, firmware limits) |
| write, sensitive | account | `RATE_LIMIT_WRITE` 120 a minute, `RATE_LIMIT_SENSITIVE` 20 an hour |

A key is only ever taken from a credential that has been checked, so a made-up header never gets a count of its own. Every 429
has `Retry-After` and `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`. `X-RateLimit-Limit` is the allowance of a counted window and `0` for a cooldown or a sign-in slowdown, which has no plain count. Honour `Retry-After`, otherwise wait
a minute and never retry a 409 or 422. Counters are in Redis outside development and fall back to memory, with a warning in
the log, if Redis fails: a Redis outage never takes the API down. The generated [route table](api-routes.md) lists the limit of
every route.

## Which writes are safe to repeat

| Write | Safe to repeat? | A client that timed out should |
| --- | --- | --- |
| `POST /telemetry` with `boot` and `seq` | yes: 200 duplicate | resend the same body |
| `POST /telemetry` without the pair | no: a second row | not resend. Send the pair |
| `POST /devices` | no: a second device and key | list by name first |
| `POST /tickets`, `/alert-rules`, `/webhooks`, `/maintenance-windows` | no | read back before retrying |
| `POST /devices/{id}/rotate-key` | dangerous: the key changed and the answer is gone | rotate again |
| `POST /invitations` | mostly: a new one cancels the old | retry |
| `POST /tokens` | no: an orphan token | list and revoke |
| PATCH, DELETE, `resolve`, `accept-counter`, firmware upload | yes (a second DELETE is 404) | retry |

## Adding a route

Dependencies come from `app/routes/auth.py` and `app/deps.py`. Raise `ApiError(status, Code.X, "sentence")`. Give the route a
response model and one auth class (it is in the table in `tests/test_access_tokens.py`). Use `Page` for a list and
`apply_patch` for a PATCH. Run `make openapi`. A route that forgets any of these fails `tests/test_api_guards.py`.
