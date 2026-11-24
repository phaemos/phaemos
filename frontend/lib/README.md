# Lib

Pure logic and small helpers. Most files have a test beside them (`*.test.mts`, run by `npm test`). A file that a test loads has no relative imports without a file extension.

| File | Purpose |
|---|---|
| api.ts | Axios instance with baseURL from NEXT_PUBLIC_API_URL. Attaches the JWT from localStorage on every request. Every request that meets a 401 waits for the one shared refresh and is retried once |
| apiError.ts | `describeApiError`: turns a failed request into one plain sentence |
| apiDetail.ts | The message the API wrote for a refused request, when it is meant for the person |
| session.ts | Everything that starts, renews or ends a session: stores the access token in localStorage and the `signed_in` marker cookie the proxy reads (it holds no token), `clearSession()` (awaits `POST /auth/logout` then clears this browser and tells other tabs) and `refreshAccessToken()` (one refresh at a time per browser profile through a Web Lock, because a refresh cookie works once) |
| cn.ts | `cn(...)` joins class names and lets the last Tailwind utility win |
| format.ts | Dates and times: `formatDate`, `formatDateTime`, `formatDateTimeExact`, `formatRelative`. UK English, day first, 24-hour clock |
| relativeTime.ts | `relativeTime` and `absoluteTime`, re-exported from `format.ts` for older imports |
| units.ts | `formatReading` and `tieUnit`: a number and its unit with a non-breaking space |
| status.ts | The one map from machine status, reading status, alert severity, ticket status and ticket priority to a word, a shape and a tone |
| theme.ts | The browser chrome colour for each theme |
| site.ts | The organisation's repository URL |
| csp.mjs | Builds the Content-Security-Policy header value for `next.config.mjs` |
| consent.ts | The analytics consent choice (read, write, subscribe), the settings prompt state and the helpers that stop analytics |
| wsUrl.ts | Builds the live telemetry WebSocket URL with no query string and the first auth frame (at most 4096 characters) |
| role.ts | The role claim inside the access token |
| adminTabs.ts | The admin tabs and their addresses |
| alertFilters.ts, alertGroups.ts, alertMetrics.ts | The alerts page: filters kept in the address, grouping by machine, metric and severity and the readings a rule can watch |
| machineList.ts | The machines list: filter, sort, the view kept in the address and owner names |
| readingGroups.ts | A machine's latest readings grouped by sensor |
| telemetryRange.ts | How the live readings chart asks for each time range and describes what it drew |
| exportFile.ts | The CSV export window and file name |
| nodeTypes.ts | The node types and their plain names |
| ticketView.ts | The tickets page: filters in the address, ticket numbers, assignees and the update body |
| password.ts, phone.ts, signInErrors.ts | The password and phone rules the API enforces and what a 429 from sign-in means |
| blog.ts, blogSource.ts | The blog: reading a post (pure) and reading `content/blog` |
| changelog.ts, changelogSource.ts | The changelog: parsing `CHANGELOG.md` (pure) and reading the file at build time |
| siteStatus.ts | What the API's public `/status` route returns and how the status page reads it |
| designRules.test.mts | Scans `app/` and `components/` and fails on the design rules that must not come back (see the file for the allow-list) |
| machineState.ts | The machine's state (healthy, warning, fault, unknown with its reason) and its link (online, late, offline), the fleet split behind the bar and the sensor faults in words. Tested by `machineState.test.mts` |
| analytics.ts | `track`: a Google Analytics event with fixed words only, sent only when the tag is on the page |
| contactSent.ts | The mark that lets the thank-you page tell a real send from a direct visit |
| ogImage.tsx | The share card every public page draws at build time: emblem, wordmark, title and one line |
| links.ts | `siteHref`, `appHref`, `appPath`, `dashboardCta`: links between the site and the dashboard for one address or two |
| publicPaths.ts | The public and dashboard path lists, the host and path routing decision for two addresses (`routeRequest`, tested) and the analytics scope |
| inviteToken.ts | Reads the invitation token from the address fragment (or the older query) and gives the address to show once it is read |
| providers.ts | The sign-in providers the page shows, from `GET /auth/providers` |
