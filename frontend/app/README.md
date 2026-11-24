# Pages

Next.js App Router pages. Route groups in brackets organise the shells and do not appear in the URL.

| Group | Shell | Routes |
|---|---|---|
| root | `layout.tsx` holds the html, the three typefaces, the theme script, providers, the cookie banner and analytics | `not-found.tsx`, `error.tsx`, `sitemap.ts` |
| (site) | Public shell: sticky top nav and footer | `/` home, `/about`, `/blog`, `/blog/[slug]`, `/changelog`, `/changelog/[version]`, `/changelog/filter/[type]`, `/docs`, `/faq`, `/support`, `/contact`, `/status`, `/security`, `/privacy`, `/terms` |
| (auth) | A centred card with no navigation | `/login`, `/accept-invite` |
| (app) | Dashboard shell: sidebar and a bar below 1024 px | `/dashboard`, `/devices`, `/devices/[id]`, `/alerts`, `/tickets`, `/compare`, `/admin`, `/profile` |

Each group layout renders the one `main` landmark, so a page component never renders its own `main`. The signed-in shell owns the outer padding and width, so every app page starts on the same left edge.

The proxy (`proxy.ts`, named `middleware.ts` before Next 16) lets `/` and the public pages through and sends every other route to `/login` without a `token` cookie. Signing in lands on `/dashboard`. `next.config.mjs` redirects `/changelog?type=fixed` to the static filter page.

| Route | File | Description |
|---|---|---|
| / | (site)/page.tsx | Public home page |
| /dashboard | (app)/dashboard/page.tsx | Overview: the fleet summary, alerts that need attention, a panel per machine and the live readings |
| /devices | (app)/devices/page.tsx | The machines list. Search, filters and sort live in the address |
| /devices/[id] | (app)/devices/[id]/page.tsx | One machine: details, live readings, latest readings and CSV export |
| /alerts | (app)/alerts/page.tsx | Active and resolved alerts, grouped or as a list |
| /tickets | (app)/tickets/page.tsx | Maintenance tickets with a detail panel |
| /compare | (app)/compare/page.tsx | Live readings of up to 3 machines side by side |
| /admin | (app)/admin/page.tsx | Users, alert rules, webhooks, maintenance windows, audit log and firmware |
| /profile | (app)/profile/page.tsx | Account, phone, password, two-step sign-in, providers and data export |
| /login | (auth)/login/page.tsx | Sign in |

A signed-in route sets its tab title in its own `layout.tsx` (the pages are client components). The group has `loading.tsx` and `error.tsx`. `sitemap.ts` lists the public pages, each blog post and each changelog release and no signed-in route.
