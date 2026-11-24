# Admin components

One panel per tab of `/admin`. The page (`app/(app)/admin/page.tsx`) picks the panel from `?tab=` (see `lib/adminTabs.ts`).

| File | Calls |
|---|---|
| PeoplePanel.tsx | The People tab: `GET /users` and the admin actions on a person (change role, deactivate and reactivate, clear two-step, send a reset link, remove), each through `components/ui/ProofDialog.tsx`; with InviteForm.tsx (`POST /auth/invite`) and Invitations.tsx (`GET` and `DELETE /invitations`) |
| AlertRulesPanel.tsx | `GET /alert-rules`, `GET /devices`, `POST /alert-rules`, `PUT /alert-rules/{id}`, `DELETE /alert-rules/{id}` |
| WebhooksPanel.tsx | `GET` (paged at 50) and `POST /webhooks` (chat or signed JSON, with an `Idempotency-Key`), `PATCH /webhooks/{id}`, `POST /webhooks/{id}/test` and `/rotate-secret`, `DELETE /webhooks/{id}` |
| MaintenanceWindowsPanel.tsx | `GET /maintenance-windows`, `GET /devices`, `POST /maintenance-windows`, `DELETE /maintenance-windows/{id}` |
| AuditLog.tsx | `GET /audit-logs` (and `GET /users` to show emails) |
| FirmwarePanel.tsx | `POST /firmware/upload` |
| Pager.tsx | Previous and next for the lists the API pages (`skip` or `offset` with `limit`), with an optional total from `X-Total-Count` |
| SecretOnceDialog.tsx | Shows a webhook's signing secret once, with the same close-asks-first pattern as a machine key |
