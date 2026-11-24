# Components

| Folder | Contents |
|---|---|
| [ui/](ui/) | The shared system: Button, Panel, Badge, StatusBadge, Tabs, Segmented, DataTable, forms, dialogs, headings, Time, Skeleton, Spinner and more. Read its README before writing a new control |
| [shell/](shell/) | The dashboard shell: AppShell (sidebar and page, with the drawer below 768 px), TopBar (a bar below 1024 px only), FleetStatus, UserMenu and the page names |
| [website/](website/) | The public site's own components: SiteHeader, SiteFooter, HeroActions, HomePreview, ScoreDiagram, ReadingFlow, ReleaseTimeline, ChangelogView, SensorTable and ContactSent. The folder is not called `site` because the repo's .gitignore ignores that name |
| [content/](content/) | The frame and pieces of the content pages: PageShell, Section, Prose, TextLink, StatusCheck, Breadcrumbs, JsonLd, the FAQ answers and the legal date |
| [dashboard/](dashboard/) | The overview: StatStrip, NeedsAttention, MachineGrid, ReadingChart, ChartBoundary, MaintenanceBanner and the sample overview for the home page |
| [machines/](machines/) | The machines list and a machine's page: MachinesView, MachineTable, MachineStatus, MonitoringHealth, LatestReadings, AddMachineDialog, FirmwareDialog, ExportCsvButton |
| [alerts/](alerts/) | The alerts page: AlertsView, AlertList, AlertRow, RangeMark |
| [tickets/](tickets/) | The tickets page: TicketsView, TicketTable, TicketDetail, TicketForm, TicketDialog |
| [admin/](admin/) | One panel per tab of `/admin` |
| [profile/](profile/) | One section per block of the profile page |
| Sidebar.tsx | The dashboard sidebar: three groups, the fleet status, the Alerts count badge, Docs and Changelog links and the user menu. 240 px wide, a 64 px icon rail from 768 to 1024 px and a drawer below 768 px |
| AlertBanner.tsx | One active alert with its Create ticket action |
| DeviceCard.tsx | One machine as a panel: status, node, last seen and its headline readings |
| TelemetryChart.tsx | The live readings: a time range control and one chart per sensor (manages its own fetch and the WebSocket) |
| ContactForm.tsx | The contact form |
| CookieBanner.tsx | Consent banner. Shown only when `NEXT_PUBLIC_GA_ID` is set. Shown again when the visitor opens Cookie settings |
| CookieSettingsButton.tsx | Button that reopens the consent banner (site footer, the app user menu and the privacy page) |
| GoogleAnalytics.tsx | Loads Google Analytics after consent, stops it and clears its cookies after a decline |
