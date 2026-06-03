# Deployment Checklist

Use this checklist before every production deployment.

## 1. Branch and release prep

- [ ] Changes are merged into `main` through a pull request
- [ ] `CHANGELOG.md` has an `[Unreleased]` entry for this release
- [ ] Version number is decided (e.g. `v0.3.0`)
- [ ] Release tag is created from the `main` commit to deploy

## 2. Security and dependency checks

- [ ] GitHub Actions `CI` workflow is green on `main`
- [ ] GitHub Actions `CodeQL` workflow is green on `main`
- [ ] GitHub Actions `Gitleaks Scan` workflow is green on `main`
- [ ] Frontend dependencies updated to latest safe patch line
- [ ] `npm audit` reviewed; any unresolved transitive advisories documented
- [ ] Backend secrets and tokens rotated if required

## 3. VPS backend deployment

- [ ] SSH into the VPS as the `phaemos` user
- [ ] `git pull origin main` in `/home/phaemos/phaemos`
- [ ] `docker compose up -d --build backend` completes with no errors
- [ ] If the PR includes a new migration file, run it:
  - [ ] `docker compose exec backend psql $DATABASE_URL < migrations/NNN_description.sql`
- [ ] Health endpoint returns expected response:
  - [ ] `curl https://api.phaemos.com/health` returns `{"status":"ok",...}`
  - [ ] `status=ok`
  - [ ] `service=PHAEMOS API`
  - [ ] `environment=production`
- [ ] Nginx is running: `sudo systemctl status nginx`
- [ ] SSL certificate is valid: `sudo certbot certificates`

## 4. Vercel frontend deployment (phaemos.com)

- [ ] Vercel deploy triggered automatically by push to `main`
- [ ] Vercel build logs show no TypeScript or lint errors
- [ ] All required environment variables are set in Vercel dashboard:
  - [ ] `NEXT_PUBLIC_API_URL=https://api.phaemos.com`
  - [ ] `NEXT_PUBLIC_TURNSTILE_SITE_KEY`
  - [ ] `TURNSTILE_SECRET_KEY`
  - [ ] `CONTACT_EMAIL_TO`
- [ ] Dashboard loads and can fetch data from `api.phaemos.com`
- [ ] `phaemos.com` custom domain resolves correctly

## 5. Vercel docs deployment (docs.phaemos.com)

- [ ] Vercel docs build triggered automatically by push to `main`
- [ ] `docs.phaemos.com` loads the MkDocs Material site
- [ ] All nav links resolve

## 6. Status page (status.phaemos.com)

- [ ] Instatus monitors show green for Platform and API components
- [ ] `status.phaemos.com` loads correctly
- [ ] Confirm no active incidents or maintenance windows

## 7. Post-deploy validation

- [ ] Login flow works for all intended roles
- [ ] Telemetry ingestion endpoint accepts valid device payloads
- [ ] Alerts and tickets pages load without runtime errors
- [ ] ML score endpoint returns expected response format
- [ ] Contact form submits successfully (Turnstile + SMTP)
- [ ] No new errors in Vercel or Docker Compose logs

## 8. Release finalisation

- [ ] Move `[Unreleased]` entries to a dated version section in `CHANGELOG.md`
- [ ] Use changelog date format `DD-MM-YYYY` for version headings
- [ ] Push tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
- [ ] Confirm GitHub `Release` workflow completed successfully
- [ ] Publish release notes and link key changes
