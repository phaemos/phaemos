# Pages

Next.js App Router pages. Each folder is a route segment.

| Route | File | Description |
|---|---|---|
| / | page.tsx | Dashboard - device cards, telemetry chart, node filter |
| /compare | compare/page.tsx | Side-by-side comparison of up to 3 devices |
| /alerts | alerts/page.tsx | Active and resolved alert feed |
| /tickets | tickets/page.tsx | Maintenance ticket list and create form |
| /devices | devices/page.tsx | All registered devices |
| /devices/[id] | devices/[id]/page.tsx | Device detail - sensor grid, charts, CSV export |
| /admin | admin/page.tsx | Admin panel - users, alert rules, firmware upload, audit log |
| layout.tsx | | Root layout - nav bar, theme toggle, dark mode script |
