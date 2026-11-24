# Deployment Checklist

Walk this list in order against production once every service is live. Each line gives the exact thing to do and the exact result to expect. Mark a line done only when the result matches. Stop at the first line that does not match and fix it before going on, because later lines depend on earlier ones. Setup steps are in the [deployment guide](deployment.md).

On the droplet, `pc` stands for `docker compose --env-file backend/.env -f infra/docker-compose.prod.yml` run from `/home/deploy/phaemos`.

The first admin is created with `pc exec backend python -m app.scripts.create_admin` and the first machine with an API call, both in Section 10 of the deployment guide. Registration is closed in production, so `curl -X POST https://api.phaemos.com/api/v1/auth/register` is expected to answer `403`. Do those before line 19. The shell variables `DEVICE_ID` and `DEVICE_KEY` below hold the `id` and `api_key` that the machine registration returned.

## 1. Release and checks

1. Open the `main` branch on GitHub. Expect the `CI`, `CodeQL` and `Gitleaks Scan` workflows all green on the latest commit.
2. Open `CHANGELOG.md`. Expect an `[Unreleased]` entry for this release and a decided version number.

2a. Sign and publish the release tag **before anything is deployed from it**. A maintainer with a release key runs `git config gpg.format ssh`, `git config user.signingkey ~/.ssh/release_key.pub`, `git tag -s vX.Y.Z -m "vX.Y.Z"` and `git push origin vX.Y.Z`. Run `git verify-tag vX.Y.Z` with the allowed signers file configured. Expect `Good "git" signature`. An unsigned `git tag vX.Y.Z` is refused by the droplet, so a plain tag cannot be deployed.

## 2. The droplet and the API

3. On the droplet, first verify the tag with a command that is not part of the checkout, then check it out and deploy: `git fetch --tags && git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile=$HOME/.config/phaemos/allowed_signers verify-tag vX.Y.Z && git checkout vX.Y.Z && bash infra/scripts/deploy.sh` (the first install uses `DEPLOY_FIRST_INSTALL=yes DEPLOY_SKIP_NGINX_CHECK=yes`, once). Expect `Good "git" signature`, then the tag and commit, then `deployed: vX.Y.Z at commit ...` and no error. Run `deploy.sh` once from a checkout that is not at a tag and once with an untracked file in `backend/migrations` and expect it to refuse both.
3a. After a release that changes how readings are scored, sign in as an admin and run `curl -X POST https://api.phaemos.com/api/v1/ml/retrain -H "Authorization: Bearer $TOKEN"`. Expect `202`. A trained model saved by an older release passes through unscored readings as 0.0 until this is done. Read `pc logs backend --tail 50` for a warning about a model file saved before missing values stopped being filled with zero, which means the retrain is still needed.
4. Run `pc ps`. Expect `db`, `redis` and `backend` all showing `Up` with `(healthy)` in the status column (the `schema` job has finished and is not listed).
4a. Run `pc exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select rolname, rolsuper, rolcreaterole from pg_roles where rolname = '"'"'$POSTGRES_APP_USER'"'"'"'`. Expect `f` and `f`. Then run `bash infra/scripts/db-role.sh --check` and expect `application database role: ok`. Run `pc exec backend env | grep -c POSTGRES_PASSWORD=.` and expect `0`. Run `pc exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -c "select count(*), max(applied_at) from schema_migrations"'` and expect one row per file in `backend/migrations` and a time that is the first deploy's.
4b. Run `for c in db redis backend; do docker inspect phaemos-prod-$c-1 --format '{{.Name}} {{.HostConfig.CapDrop}} {{.HostConfig.SecurityOpt}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.PidsLimit}}'; done`. Expect `[ALL]`, `[no-new-privileges:true]`, `true` and a number on every line. Run `pc exec redis redis-cli ping` and expect `PONG` (the container carries the password). Run `docker run --rm --network phaemos-prod_internal redis:7-alpine redis-cli -h redis ping` and expect `NOAUTH`.
5. Run `curl http://localhost:8000/` on the droplet. Expect `"status":"ok"` and no environment name (the root no longer names it). Run `pc exec -T backend python -c 'from app.config import settings; print(settings.environment, settings.is_development)'`. Expect `production False`.
6. Run `ss -tlnp | grep -E '5432|6379|8000'`. Expect only `127.0.0.1:8000` and no listener for the database or Redis.
7. Run `sudo ufw status`. Expect `Status: active` with only ports 22, 80 and 443 allowed. In the DigitalOcean panel open **Networking** -> **Firewalls**. Expect a firewall on the droplet that allows port 22 from your own addresses only. Run `sudo -n true`. Expect a refusal, because the deploy user's sudo rule lists exact commands only. Run `grep -E '^(AllowUsers|PermitRootLogin|PasswordAuthentication)' /etc/ssh/sshd_config.d/00-phaemos-hardening.conf`. Expect `AllowUsers deploy`, `PermitRootLogin no` and `PasswordAuthentication no`.
8. Run `sudo systemctl status nginx` and `sudo certbot certificates`. Expect Nginx `active (running)` and a certificate for `api.phaemos.com` that is valid for more than 14 days.
9. From any computer run `curl -i https://api.phaemos.com/status`. Expect status `200` with `"status":"operational"`, `"database":"ok"` and `"redis":"ok"`.
10. From any computer run `curl -i http://api.phaemos.com/status`. Expect a `301` redirect to `https://api.phaemos.com/status`.
10a. From any computer run `curl -i https://api.phaemos.com/status`. Expect the headers `Strict-Transport-Security: max-age=31536000`, `X-Content-Type-Options: nosniff` and `Cache-Control: no-store` and no `server: uvicorn` header. Run `curl -ik --resolve stranger.example:443:YOUR_DROPLET_IP https://stranger.example/` and expect the handshake to be refused. Run `curl -i -X POST https://api.phaemos.com/api/v1/auth/login -H 'Content-Type: application/json' --data-binary @<(head -c 70000 /dev/zero | tr '\0' a)`. Expect `413`. Run `for i in $(seq 1 40); do curl -s -o /dev/null -w '%{http_code}\n' https://api.phaemos.com/api/v1/auth/me; done | sort | uniq -c`. Expect some `429` answers once the burst of 10 is used.
10b. On the droplet run `bash infra/scripts/check-nginx.sh`. Expect `nginx: the installed site is the repository's file, byte for byte and it is the one running`. Add a space to a comment in `/etc/nginx/sites-available/api.phaemos.com.conf` from the Droplet Console and run it again: expect `WRONG in the Nginx set-up` and a non-zero exit. Put the file back.
10c. Open 300 plain requests at the live socket path at once: `seq 300 | xargs -P 300 -I{} curl -s -o /dev/null -w '%{http_code}\n' https://api.phaemos.com/ws/telemetry/x | sort | uniq -c`. Expect many `429` answers (the request limit and the cap of 60 sockets) and not 300 reaching the API.
11. From any computer run `curl -i https://api.phaemos.com/metrics`. Expect `404`.
12. From any computer run `curl -i https://api.phaemos.com/docs`. Expect `404`, because the interactive docs are off in production.
13. From any computer run `curl https://api.phaemos.com/`. Expect `"status":"ok"` and no `environment` field. Run `curl -i -X POST https://api.phaemos.com/api/v1/telemetry/ -d '{}'` (a trailing slash). Expect `404` from the API (it no longer redirects) and no `Location:` header at all.
13a. Open the dashboard, then in the browser console run `fetch('https://api.phaemos.com/api/v1/auth/login', {method: 'POST'})` about 20 times in a loop. Expect later answers to be `429` with a JSON body `{"code":"rate_limited",...}` that the page can read (no CORS error) and a `Retry-After: 2` header. Expect `/api/v1/users` (signed in) to never answer 429 in the same test.
14. The morning after the first scheduled backup run `ls -l ~/backups`. Expect a `phaemos-...sql.gz.age` file from that day that is larger than a few kilobytes and a `backup.log` that ends with `backup written` and either `offsite copy written` or the warning that no off-server copy is set. Expect no plain `.sql.gz` file. Run `head -c 21 ~/backups/phaemos-*.sql.gz.age | head -1` and expect `age-encryption.org/v1`. Run `ls ~/.config ~ | grep -i key` and expect no age private key on the droplet.
14c. In the object store expect the same file in the bucket and expect the droplet's credential to be refused when it tries to list or delete.
14a. On the droplet run `pc exec backend sh -c "tr '\\0' ' ' < /proc/1/cmdline"`. Expect the uvicorn command to include `--no-access-log`, `--ws-max-size 8192`, `--ws-per-message-deflate false` and `--limit-concurrency 150`.
14aa. Run `pc exec backend id`. Expect `uid=10001(phaemos)`, not root. Then upload a firmware file as an admin. Expect `201`, which proves the firmware volume is writable by that user (on an existing droplet run the `chown` step in the deployment guide, Section 15, first).
14b. Run `grep -c WS_TOKEN_IN_URL backend/.env`. Expect `0` or a line set to `false`. Production should refuse the `?token=` socket address. Then run `sudo nginx -T | grep -E 'limit_conn (ws_per_addr|api_per_addr)'`. Expect both lines.

## 2a. Monthly

M1. Restore test, once a month and not on production. Fetch the newest backup from the off-server copy, restore it into a copy of the stack with the private key (Section 14), sign in and check the machines and their latest readings are there and `/status` is `operational`. Expect all three. Write the date and the result next to this line. Delete the decrypted data and the copy afterwards. Do not restore the model file: retrain.
M2. Refresh the pinned images (Section 6) and read the Ubuntu and Docker security notices. Expect the digests in `infra/docker-compose.prod.yml` to be the current ones for `postgres:15` and `redis:7-alpine`.
M3. Review the addresses in the cloud firewall and the keys in `~/.config/phaemos/allowed_signers`. Expect only people who still work on the product.

## 3. The dashboard

15. In Vercel open the latest production deployment of the dashboard. Expect `Ready` and a build log with no TypeScript or lint errors.
16. In Vercel open **Settings** -> **Environment Variables**. Expect `NEXT_PUBLIC_API_URL=https://api.phaemos.com`, `NEXT_PUBLIC_TURNSTILE_SITE_KEY` and, if analytics is wanted, `NEXT_PUBLIC_GA_ID`. All are read at build time, so a change needs a redeploy.
17. Open `https://phaemos.com`. Expect the site to load over TLS on the custom domain. Run `curl -I https://www.phaemos.com`. Expect `308` to `https://phaemos.com`.
17a. Open `https://dashboard.phaemos.com`. Expect the sign-in page when signed out and the overview at `/` when signed in. Open `https://dashboard.phaemos.com/about`. Expect a redirect to `https://phaemos.com/about`. Open `https://phaemos.com/dashboard`. Expect a redirect to `https://dashboard.phaemos.com/`.
17b. Run `curl -i https://dashboard.phaemos.com/robots.txt`. Expect `Disallow: /`. Run `curl -i https://dashboard.phaemos.com/sitemap.xml`. Expect `404`. Run `curl https://phaemos.com/robots.txt`. Expect a `Sitemap:` line with `https://phaemos.com/sitemap.xml`.
17c. In Vercel **Settings** -> **Environment Variables** expect `NEXT_PUBLIC_SITE_URL=https://phaemos.com` and `NEXT_PUBLIC_APP_URL=https://dashboard.phaemos.com`, each scoped to **Production** only (previews then run as one address). Both are read at build time and by the proxy, so redeploy after a change.
17d. On `https://phaemos.com` expect the main button to read "Dashboard" and link to `https://dashboard.phaemos.com/`. In the page source expect `<link rel="canonical" href="https://phaemos.com/...">`.
18. Open `https://docs.phaemos.com`. Expect the documentation site with every navigation link resolving.

The build stops by itself on a production deployment (Vercel `VERCEL_ENV=production` or `NODE_ENV=production` on a build that is not on Vercel) while any placeholder a visitor could see is left in `frontend/content/legal`. A placeholder is any `[words]` in the text that is not a link or a `version` that is not a real date. Preview builds only warn and a page with a placeholder is `noindex` and left out of the sitemap. `LEGAL_PLACEHOLDERS=fail` stops any build and `LEGAL_PLACEHOLDERS=allow` lets one through. Run `node --no-warnings scripts/check-legal.mjs` in `frontend/` to list what is left with its file and line. Also set each service line in `frontend/content/legal/services.ts` to match what is switched on, because the privacy notice and the cookies page name only those services. The two-address wording on those pages follows `NEXT_PUBLIC_SITE_URL` and `NEXT_PUBLIC_APP_URL`, the same values the app uses. `https://phaemos.com/.well-known/security.txt` is served by the site with an `Expires` date 330 days after the build, so redeploy at least once a year.

## 4. Sign-in

19. On `https://dashboard.phaemos.com/login` sign in with the admin account from the deployment guide. Expect to land on the overview at `https://dashboard.phaemos.com/` with the Admin page available. Check once from a clean browser profile, because sign-in across the two addresses cannot be proved on localhost.
20. Open the browser developer tools, then **Application** -> **Cookies** -> `https://api.phaemos.com`. Expect the refresh cookie with `Secure` and `HttpOnly` ticked. A cookie without `Secure` means the API is not running as production.
21. Sign out and choose **Continue with Google**. Expect the Google consent screen then a return to `https://dashboard.phaemos.com` signed in. An error naming a redirect address means `GOOGLE_REDIRECT_URI` or the Google app settings do not match.
21a. Sign in, copy the `refresh_token` cookie value from the developer tools, then press Sign out. Expect the cookie to disappear. Send `curl -i -X POST https://api.phaemos.com/api/v1/auth/refresh -H 'Cookie: refresh_token=<the copied value>'`. Expect `401`, because sign-out ended the session on the server.
22. Sign out and choose **Continue with GitHub**. Expect the GitHub consent screen then a return to `https://dashboard.phaemos.com` signed in.
23. Sign in once for each other role you intend to use. Expect each to see only what its role allows.

## 5. Contact form and email

24. Open `https://phaemos.com/contact`. Expect the Turnstile widget to appear and complete.
25. Submit the form with a real address of yours and a short message. Expect the page to say the message was sent.
26. Open the contact mailbox. Expect the message within a minute with the sender's address as Reply-To. A 503 on the form means Resend is not set up or refused the message: run `pc logs --tail 50 backend` for the reason.
27. Submit the form again with the Turnstile step incomplete. Expect it to be refused.
28. As the admin create an invitation. Log in as in the deployment guide to get `TOKEN`, then run `curl -s -X POST https://api.phaemos.com/api/v1/auth/invite -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"email": "invitee@example.com", "role": "viewer"}'` with a real address. Expect `"email_sent": true` and an email from the `FROM_EMAIL` address with a link starting `https://phaemos.com/accept-invite?token=`. The dashboard page behind that link is still to come, so finish the invitation with `POST /api/v1/auth/accept-invite`.

## 6. Analytics

29. Open `https://phaemos.com` in a private window. Expect a cookie banner and no request to a Google host before you choose.
30. Choose **Accept**, then open the console and the network tab and reload. Expect requests to Google Analytics and no content security policy error. A blocked Google host means it must be added in `frontend/lib/csp.mjs`.
31. Open the Google Analytics real-time report. Expect your visit within a minute.
32. Repeat in another private window and choose **Decline**. Expect no request to a Google host.

## 7. Telemetry

33. Register a machine with `POST /api/v1/devices` as in Section 10 of the deployment guide. Expect status `201` and a response with `id` and `api_key`. Keep both. The key is shown once.
34. Send one reading with that key:

    ```bash
    curl -i -X POST https://api.phaemos.com/api/v1/telemetry \
      -H "Content-Type: application/json" \
      -H "X-API-Key: $DEVICE_KEY" \
      -d '{"device_id": "'"$DEVICE_ID"'", "temperature": 34.2, "humidity": 61.5}'
    ```

    Expect status `201` with an `id` and an `anomaly_score`.
35. Send the same request with a wrong key. Expect exactly `401` and no new reading.
36. Open the device page in the dashboard. Expect the reading in the chart and the device `online`.
37. Keep the device page open and send another reading. Expect the chart to update without a reload. That proves the WebSocket at `wss://api.phaemos.com/ws/telemetry/{device_id}` is upgraded through Nginx.
38. With a real device powered on, expect its readings to appear every cycle and `last_seen` to move.

## 8. Alerts

39. Give the device owner a phone number in E.164 form (for example `+447700900000`) on their profile page. Expect the profile to save. Any other format is refused.
40. Add a critical rule on that device with a threshold the next reading will cross (`POST /api/v1/alert-rules`), then send one reading above it. Expect an alert in the dashboard, one alert email at every address in `ALERT_EMAIL_TO` within a minute and one text to the owner's phone.
41. Send a second reading above the threshold straight away. Expect no second email and no second text. A repeat goes at most once an hour while the rule stays breached.
42. Run `pc restart redis backend`, wait until `pc ps` shows both `(healthy)` and send another breaching reading. Expect still no repeat, which proves the window survived the restart in Redis.
43. After an hour with the rule still breached send one more reading. Expect exactly one repeat email and one repeat text.
44. Add a warning rule and breach it. Expect an email and no text. Add an info rule and breach it. Expect neither.
45. Delete the test rules and close the test alerts. Expect an empty open alert list.

## 9. Status and docs

46. Open `https://status.phaemos.com`. Expect every component `Operational` and no active incident or maintenance window.
47. In Instatus open the API monitor. Expect it to check `https://api.phaemos.com/status` for the keyword `operational` and show green.
48. On `https://docs.phaemos.com` use the search box to look for `deployment`. Expect results that include the deployment guide.

## 10. Logs and release

49. Run `pc logs --since 1h backend`. Expect no traceback and no repeated warning other than a cap message you caused on purpose.
50. Open the Vercel project logs. Expect no new runtime errors.
51. Move the `[Unreleased]` entries in `CHANGELOG.md` to a dated version section with the date as `YYYY-MM-DD`, as the other version headings do.
52. Confirm the tag from step 2a is the one that is deployed: run `git describe --tags` on the droplet and expect `vX.Y.Z` with nothing after it. The tag was signed and pushed in step 2a, before the deploy. Do not tag after deploying.
53. Publish the release notes and link the key changes.
