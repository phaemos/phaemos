# Machine components

| File | Description |
|---|---|
| MachinesView.tsx | The machines page: search, status, tag and sort order (kept in the address through `lib/machineList.ts`), the table, Add a machine and Update firmware by tag |
| MachineTable.tsx | The machines as a table. Each row is one link, so a click anywhere on it opens the machine |
| MachineStatus.tsx | The machine's state and its monitoring link, each a shape and a word |
| MonitoringHealth.tsx | The "Monitoring health" section: faulted sensors (from the node and found by the server) with what to check, replay protection, the node's vitals and, for an admin, claims the server did not act on. Says so plainly when the node has never sent health information |
| LatestReadings.tsx | The newest value of every sensor on one machine, grouped by sensor |
| AddMachineDialog.tsx | `POST /devices`. Hands the new key straight to KeyOnceDialog and keeps nothing of it |
| KeyOnceDialog.tsx | Shows a device key once with a copy button and a warning. Closing asks first and drops the key (`lib/keyOnce.ts`) |
| RotateKeyControl.tsx | `POST /devices/{id}/rotate-key` with the password and code from ProofDialog, then KeyOnceDialog |
| ReplaySection.tsx | Replay protection in the API's own words and, for an admin, `POST /devices/{id}/accept-counter` |
| ModelBadge.tsx | The anomaly model's state for one machine: ready, learning with its hours, legacy, none, refused or error |
| FirmwareDialog.tsx | `POST /devices/batch/firmware-update` for every machine with a tag |
| ExportCsvButton.tsx | `GET /telemetry/export` through `lib/api.ts`, saved as a file |
