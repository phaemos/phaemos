# Alerts Page

Route: `/alerts`
Shows active or resolved alerts, grouped by machine, metric and severity or as a flat list in time order.
Filters (state, severity, machine, view) live in the query string. Polls every 10 seconds while the tab is visible.
Resolve is available to every signed-in role because `PATCH /alerts/{id}/resolve` has no role check. The API has no acknowledge or delete.
Logic: `lib/alertFilters.ts`. Components: `components/alerts/`.
