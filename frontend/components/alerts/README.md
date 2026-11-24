# Alert Components

| File | Description |
|---|---|
| AlertsView.tsx | The page: filters, refresh, resolve actions and the loading, error, empty and loaded states |
| AlertList.tsx | One row for each alert, critical first and then the most recently seen |
| AlertRow.tsx | One long-lived alert: when the condition first held, when it was raised, whether it is still occurring, the readings that met it, the peak and the latest value. A model alert adds its evidence in words and the range mark |
| RangeMark.tsx | A small mark of a sensor's value against its usual range. Position and shape carry the meaning, never colour |
| NotificationLimitNotice.tsx | Says when the daily email or text limit has stopped messages. Every signed-in role, read from `daily_limits` on `GET /alert-metrics` (admins fall back to the audit log) |
| alertText.ts | One alert in words, for a row and for a ticket title |
