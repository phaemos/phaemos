# Dashboard components

| File | Description |
|---|---|
| StatStrip.tsx | Presentational fleet summary: four lines, each a figure with the words that say what it means (health word and shape, machines online, active alerts by severity, tickets). No bar or gauge |
| HealthSummary.tsx | Container that fetches `/health/summary` and renders StatStrip |
| NeedsAttention.tsx | The most urgent active alerts, one row each (AlertRow), critical first |
| MachineGrid.tsx | Presentational grid of machine panels (uses `components/DeviceCard.tsx`) |
| ReadingChart.tsx | One sensor as a chart: a title with its unit, lines named where they end, 3 to 5 solid gridlines, ticks with units, a one-sentence description and the data as a table for screen readers. No animation. Colours come from the `--chart-*` properties in `app/globals.css` |
| ChartBoundary.tsx | Error boundary for one chart, so a chart that fails to draw does not take the page down |
| InlineError.tsx | The earlier name for `ui/ErrorNotice` |
| keyReadings.ts | Picks a machine's two or three headline readings from telemetry rows |
| FirstRun.tsx | The overview for a fleet with no machines: the first steps in order, the admin-only ones for admins |
| OverviewPreview.tsx | The overview from fixed sample data, with no requests and no live controls, for the public home page |
| MaintenanceBanner.tsx | Notice shown while a maintenance window is active |
