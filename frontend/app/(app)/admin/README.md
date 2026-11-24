# Admin Page

Route: `/admin`
One tab each for users, alert rules, webhooks, maintenance windows, the audit log and firmware upload. The tab lives in the address (`?tab=`, see `lib/adminTabs.ts`). Components: `components/admin/`.
Requires an admin token: the endpoints answer 401 or 403 without one.
