# Deployment Checklist

Use this checklist before every production deployment.

## 1. Branch and Release Prep

- [ ] Changes are merged into `main` through a pull request.
- [ ] `CHANGELOG.md` has an `[Unreleased]` entry for this release.
- [ ] Version number is decided (for example `v0.3.0`).
- [ ] Release tag is created from the `main` commit to deploy.

## 2. Security and Dependency Checks

- [ ] GitHub Actions `CI` workflow is green on `main`.
- [ ] GitHub Actions `Gitleaks Scan` workflow is green on `main`.
- [ ] Frontend dependencies updated to latest safe patch line.
- [ ] `npm audit` reviewed and any unresolved transitive advisories documented.
- [ ] Backend secrets and tokens rotated if required.

## 3. Render Backend Deployment

- [ ] Render service points to the correct `main` branch.
- [ ] Environment variables are set in Render:
  - [ ] `DATABASE_URL`
  - [ ] `REDIS_URL`
  - [ ] `SECRET_KEY`
  - [ ] `ALGORITHM`
  - [ ] `ACCESS_TOKEN_EXPIRE_MINUTES`
  - [ ] `ALLOWED_ORIGINS`
  - [ ] `ENVIRONMENT=production`
- [ ] Health endpoint returns expected metadata:
  - [ ] `status=ok`
  - [ ] `service=PHAEMOS API`
  - [ ] correct `version`
  - [ ] `environment=production`
- [ ] API docs endpoint is reachable for smoke checks.

## 4. Vercel Frontend Deployment

- [ ] Vercel project points to the correct repository and branch.
- [ ] Required environment variable is set:
  - [ ] `NEXT_PUBLIC_API_URL` points to the Render backend URL
- [ ] Frontend build logs show no TypeScript or lint errors.
- [ ] Dashboard loads and can fetch backend data.

## 5. Post-Deploy Validation

- [ ] Login flow works for all intended roles.
- [ ] Telemetry ingestion endpoint accepts valid device payloads.
- [ ] Alerts and tickets pages load without runtime errors.
- [ ] ML score endpoint returns expected response format.
- [ ] No new errors in deployment platform logs.

## 6. Release Finalisation

- [ ] Move relevant `[Unreleased]` entries to a dated version section in `CHANGELOG.md`.
- [ ] Push tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
- [ ] Confirm GitHub `Release` workflow completed successfully.
- [ ] Publish release notes and link key changes.
