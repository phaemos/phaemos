# Frontend

Next.js 16 App Router - the PHAEMOS dashboard web application.

> [!NOTE]
> This folder is published to [phaemos/frontend](https://github.com/phaemos/frontend) as a read-only copy. Open issues and pull requests on [phaemos/phaemos](https://github.com/phaemos/phaemos).

| Folder | Purpose |
|---|---|
| [app/](app/) | Pages and layouts (Next.js App Router) |
| [components/](components/) | Reusable React components |
| [hooks/](hooks/) | Custom React hooks |
| [lib/](lib/) | Axios client and utility functions |
| [types/](types/) | TypeScript interfaces |

Start: `npm run dev` (requires NEXT_PUBLIC_API_URL in .env.local)

Optional build-time values (see `.env.example`):

- `NEXT_PUBLIC_TURNSTILE_SITE_KEY` shows the Cloudflare Turnstile widget on the contact form and adds `challenges.cloudflare.com` to the content security policy.
- `NEXT_PUBLIC_GA_ID` turns on the cookie banner and, once a visitor accepts, Google Analytics. It also adds the Google sources to the policy. Unset, there is no banner and no analytics, the legal pages say so and the build still succeeds.
- `NEXT_PUBLIC_VERCEL_ANALYTICS=1` turns on Vercel Web Analytics on a Vercel production build. Unset, it is off and the legal pages leave it out.
- The production build check (`scripts/check-legal.mjs`) also refuses a placeholder anywhere in `app/`, `components/`, `public/` or the blog: two or more capital words in square brackets, such as `[LEGAL NAME OF THE CONTROLLER]`.
Build: `npm run build`

## One address or two

`NEXT_PUBLIC_APP_URL` holds the dashboard's address and keeps its name for compatibility.

By default the public site and the dashboard answer on one address and nothing below applies. Setting `NEXT_PUBLIC_SITE_URL` and `NEXT_PUBLIC_APP_URL` to two different origins (for example `https://phaemos.com` and `https://dashboard.phaemos.com`) turns on split mode in the same deployment:

- `proxy.ts` sends a request for a dashboard page, the sign-in page or the invitation page that arrives on the site address to the dashboard address and a request for a site page that arrives on the dashboard address to the site address. The overview is `/` on the dashboard address (`/dashboard` redirects to it).
- Static files, `/_next`, `/_vercel`, `/.well-known`, `robots.txt` and `sitemap.xml` are never redirected. The dashboard address answers `robots.txt` with `Disallow: /` and has no sitemap.
- Only the `Host` header is compared with the two configured addresses. A host that is neither (a preview address, `localhost`) is never redirected. A redirect is built from a configured origin plus the path and query, nothing else. The decision is a pure function in `lib/publicPaths.ts` with its tests.
- Every link between the two halves comes from `siteHref(path)` and `appHref(path)` in `lib/links.ts`: absolute in split mode, relative otherwise.
- The sign-in cookie belongs to the dashboard address only, so the site cannot tell whether a visitor is signed in. In split mode the site's button reads "Dashboard" and links to the dashboard address, which sends a signed-out visitor to sign in.
- Canonical addresses and `metadataBase` come from the site address. Both analytics tools run on site pages only: the cookie banner and the Google tag are mounted in the site layout, so the dashboard, sign-in and invitation addresses never load them. The Google tag keeps its cookies on the site's own address (`cookie_domain: 'none'`).
- A request for an address that belongs to neither half gets the 404 page, not the sign-in page. A signed-out visit to a dashboard page goes to sign-in with the page it asked for in `next`, which the sign-in page accepts only as a dashboard path (`safeNextPath`). A move from the `www` form of the site address is a permanent redirect (308).
- Set both values for the Production environment only. On a preview deployment they send every dashboard and legal link to the live site.
- The content security policy needs no change: it names the API origin only and both addresses share the policy. It allows `'unsafe-eval'` for the development server only.

To try it locally without changing a system setting, start a second dev server on its own copy of the project (two `next dev` servers cannot share one `.next` folder) with both values set and send the `Host` header with `curl`: `curl -i -H "Host: dashboard.phaemos.test:3200" http://localhost:3200/about`. Sign-in across two real addresses (the cookie, the OAuth return and the refresh cookie) cannot be proved this way. Check it on the deployed addresses.

## Docker

The image is built from the repository root, because the changelog pages read `CHANGELOG.md`, which sits above this folder. `frontend/Dockerfile.dockerignore` keeps the rest of the monorepo out of the build context.

```sh
docker build -f frontend/Dockerfile -t phaemos-frontend .
```

- The builder stage sets `NODE_ENV=production`, so the legal check (`scripts/check-legal.mjs`) stops the build while a legal page holds a placeholder or a service flag disagrees with the environment. To try the image before the pages are finished pass `--build-arg LEGAL_PLACEHOLDERS=allow`.
- `infra/docker-compose.yml` (the development stack, `docker compose up --build`) passes `LEGAL_PLACEHOLDERS=allow` as a build argument so the build is not stopped by an open placeholder. Production stays strict: a build without that argument stops. Set `LEGAL_PLACEHOLDERS=fail` in your shell to make the compose build strict.
- `NEXT_PUBLIC_API_URL` is read at build time and has no default. A production build stops unless it is an `https://` address, so a bare `docker build` fails with a message. A real image passes `--build-arg NEXT_PUBLIC_API_URL=https://api.example.com`. A local stack that really is http must say so with `--build-arg ALLOW_INSECURE_API_URL=1` (the development compose file passes it).
- The container runs as the unprivileged `node` user. Pass `--build-arg NEXT_PUBLIC_API_URL=https://api.example.com` for a real address.
- Vercel Web Analytics is mounted only on Vercel (`next.config.mjs` sets `NEXT_PUBLIC_ON_VERCEL` from `VERCEL` at build time). Anywhere else its script does not exist, so it is left out and no page logs a 404 for `/_vercel/insights/script.js`.

## Content security policy

`proxy.ts` sets the policy on every page (not `next.config.mjs`, because one of the two needs a fresh nonce for each request).

- **The dashboard, the sign-in page and the invitation page** (`isPrivateSurface` in `lib/publicPaths.ts`) get `buildNonceCsp`: `script-src 'self' 'nonce-...' 'strict-dynamic'` plus the hash of `public/theme.js`, with no `'unsafe-inline'`. An injected inline script has no nonce and does not run. Their layouts are `force-dynamic`, so these pages are rendered for each request. The theme script is a file (`public/theme.js`), allowed by its hash (`lib/themeHash.mjs`).
- **The public site pages** keep `buildCsp` with `'unsafe-inline'` and stay static and cached: a nonce would make every one of them render per request and lose the CDN cache and they never hold the access token.
- All pages send `object-src 'none'`, `base-uri 'self'`, `form-action 'self'` and `frame-ancestors 'none'`, plus `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy` set to `same-origin` (the provider sign-in is a full-page redirect, so nothing needs a window of its own).
- The cookie the proxy reads is `signed_in=1`, a marker that holds no credential. The access token lives in memory and localStorage.
- Admin actions that could be misused by a stolen session (inviting an admin, adding or switching a webhook, uploading firmware) ask for the password (and a code with two-step) through `components/ui/ProofDialog.tsx` and send it in the request.

## Analytics and sessions

- Google Analytics runs on public site pages only. `components/AnalyticsGuard.tsx` sits in the root layout: on a path that is not a site page it switches the tag off (`ga-disable-<id>`) and, if the tag had loaded, reloads the page so the tag is gone. This holds with one address as well as two.
- Sign-in state is in `lib/session.ts`: one refresh at a time per browser (a Web Lock), `clearSession()` for sign-out and a `BroadcastChannel` that signs the other tabs out. The profile page lists the person's own sessions and can end one or all the others.
