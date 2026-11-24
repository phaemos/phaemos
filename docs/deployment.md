# Deployment Guide

This guide covers the production deployment of Phaemos at the Launch milestone:

- Backend (FastAPI, PostgreSQL and Redis) on one DigitalOcean droplet, behind Nginx with TLS at `api.phaemos.com`
- Frontend (Next.js) on Vercel
- Documentation site (MkDocs) on Vercel
- Status page on Instatus

Everything the droplet needs is in the repository: `infra/docker-compose.prod.yml`, `infra/nginx/api.phaemos.com.conf` and the scripts in `infra/scripts/`. The `Deploy` workflow still holds an earlier Render deploy hook and is disabled, so the backend is deployed by hand with the steps below. See [decision 015](decisions.md).

> [!IMPORTANT]
> Never run `infra/docker-compose.yml` in production. It is the development stack: it hard-codes `ENVIRONMENT: development` and a throwaway database password, reads a development signing key from an ignored file, mounts the source code and starts a dashboard container. Those values override `backend/.env`, so the API would run as development and the refresh cookie would not be marked secure. The production file fixes `ENVIRONMENT` to `production` itself, so a stray value in `backend/.env` or the shell cannot change it.

The order below matters. Work through the sections from top to bottom.

## What an attacker gains from each foothold

Each hardening step below exists because of one of these. Read the table once so the steps are not a list of rules to follow blindly.

| Foothold | What it gives today (before the step) | Steps that limit it |
| --- | --- | --- |
| No account, only the internet | Lock accounts out, learn which addresses have accounts, flood the API with wrong keys or large bodies, probe the host names | Nginx request limits, the 64 kB body limit, slow-client timers and the refusal of unknown host names (Section 9) |
| A stolen device key | Be that one machine: forge its readings and silence its alarms. Nothing else | Not a server step: it is limited by the key being one per machine. The request limits cap how fast one key can post |
| Code running inside the API (a bad dependency or a flaw) | The signing key, the vendor keys and, if the API signs in as the owner, a database superuser that can run commands in the database container | The limited database login (Section 6), read-only containers with no capabilities and no way to gain any (Section 6), the Redis password |
| The deploy user's SSH key | Root on the droplet, because the docker group and passwordless sudo are both root | A cloud firewall that allows SSH from known addresses only, `AllowUsers`, the narrow sudo rule and a key held on hardware (Section 3) |
| A copy of a backup (a stolen laptop copy, a snapshot, the deploy account) | Every email, phone number, password hash, two-step secret and device key | Backups encrypted with a key that is never on the server, an off-server copy that the server cannot delete, a monthly restore test (Section 14) |
| A tampered release or a hijacked deploy | Whatever code the attacker put in the checkout runs with the keys above | Deploying only a tag whose signature verifies against a key you hold (Section 6) |

---

## Prerequisites

### DigitalOcean credit (GitHub Student Pack)

The GitHub Student Developer Pack provides $200 of DigitalOcean credit, covering the $6/month Basic Droplet price for a long time. Apply at [education.github.com/pack](https://education.github.com/pack) with a verified `.edu` email. Credit is applied automatically once approved.

### What the stack needs

| Part | Where | Notes |
| --- | --- | --- |
| API, database and cache | The droplet, in Docker | `infra/docker-compose.prod.yml` |
| TLS and the public address | Nginx and Certbot on the droplet | `api.phaemos.com` |
| Dashboard | Vercel | Does not run on the droplet |

Memory plan for the 1 GB droplet (about 960 MiB usable). In steady state the container limits add up to 704 MiB: the database 256, Redis 64 and the API 384. That leaves about 256 MiB for the kernel, Docker, Nginx, SSH and fail2ban. During a deploy the one-shot schema job (256 MiB) runs while the old API still serves, so for a minute or two the ceilings total 960 MiB, which is the whole machine. They are ceilings and not reservations and a table-creating job uses far less than its ceiling, but the margin is gone and the 2 GB swap file added by `harden.sh` carries it. If the machine is also busy or the stack grows, take the 2 GB droplet (about twice the price) instead. Logs are rotated at 10 MB with 3 copies per container, so they cannot fill the 25 GB disk.

---

## Section 1: Create the droplet

1. Sign in to [cloud.digitalocean.com](https://cloud.digitalocean.com).
2. Click **Create** -> **Droplets**.
3. Choose the following:
   - **Region:** closest to your expected users (for example London or Amsterdam for EU)
   - **Image:** Ubuntu 24.04 LTS
   - **Size:** Basic, 1 vCPU / 1 GB RAM / 25 GB SSD (about $6/month, covered by the Student Pack)
   - **Authentication:** SSH key (paste your public key)
4. Click **Create Droplet** and note the assigned address.
5. Add the DNS record from Section 8 now (`api` pointing at the droplet), so it has spread by the time Certbot needs it.

---

## Section 2: Get the repository onto the droplet

Log in as root once and fetch the repository. The scripts live in it and from here on **root runs them**, so check what you fetched before you run any of it. The check is a command that is not in the repository (a tag can be published by anyone who can write to the repository and a script in the tag would only check itself).

First put the release keys on the droplet, copied from your own computer and never fetched from the repository you are about to verify. The file lists the SSH public keys that sign releases, one per line, in git's allowed signers format (`maintainer@phaemos.com namespaces="git" ssh-ed25519 AAAA...`):

```bash
scp allowed_signers root@YOUR_DROPLET_IP:/root/allowed_signers
```

Then fetch, verify and only then check out. Use the newest signed release tag:

```bash
ssh root@YOUR_DROPLET_IP
apt-get update && apt-get install -y git
git clone https://github.com/phaemos/phaemos.git /root/phaemos
cd /root/phaemos
git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile=/root/allowed_signers verify-tag vX.Y.Z
git checkout vX.Y.Z
```

`verify-tag` must print `Good "git" signature`. If it prints anything else, stop: do not run `harden.sh` or `install.sh`. Do not check out `main` on a droplet.

---

## Section 3: Harden the droplet

`harden.sh` creates a non-root deploy user, turns SSH passwords and root login off, lets only the deploy user in over SSH (`AllowUsers`), allows only ports 22, 80 and 443 in `ufw`, installs fail2ban and unattended security upgrades and adds a 2 GB swap file. It copies the keys root was created with to the new user and refuses to continue when it finds none. Running it twice changes nothing.

Run it the first time with the full sudo rule, because the next sections need root for a few one-off steps. Run it from a terminal (it asks a question before it changes sshd). It needs the deploy user to be named in the list of users sshd lets in and every name in that list to exist and hold a valid key, so it cannot lock out the account you will use:

```bash
DEPLOY_SUDO=full bash /root/phaemos/infra/scripts/harden.sh
```

Just before it reloads sshd it stops and asks you to open a **second terminal** and sign in as the deploy user (`ssh deploy@YOUR_DROPLET_IP`). Do that. If the sign-in works, type `yes`. Keep the first (root) session open: sshd's reload does not end it and it is how you undo a mistake. After the reload the script prints a command to remove the new sshd file, in case a third fresh sign-in fails. A script run without a terminal (for example from a provisioning tool) refuses to continue unless `HARDEN_CONFIRMED=yes` is set, so it cannot reload by accident.

Move the checkout to the deploy user's home:

```bash
mv /root/phaemos /home/deploy/phaemos
chown -R deploy:deploy /home/deploy/phaemos
mkdir -p /home/deploy/.config/phaemos
mv /root/allowed_signers /home/deploy/.config/phaemos/allowed_signers
chown -R deploy:deploy /home/deploy/.config
```

Keep the root session open and do Sections 4 and 9 from it (they need root). Then run `harden.sh` once more without `DEPLOY_SUDO=full`, as the last step of the first set-up (Section 9, last step). The narrow rule is refused until the deploy user is in the `docker` group, which Section 4 does.

### A cloud firewall in front of SSH

`ufw` runs on the droplet, so a break-in or a mistake can switch it off. Add a DigitalOcean cloud firewall as well. It sits outside the droplet. In the control panel open **Networking** -> **Firewalls** -> **Create Firewall**, attach it to the droplet and set:

- Inbound SSH (TCP 22): only the addresses you work from. Use `/32` entries for fixed addresses. Keep the list short and review it when someone leaves.
- Inbound HTTP (TCP 80) and HTTPS (TCP 443): all addresses.
- Outbound: leave open (the droplet needs the package mirrors, Docker's registry and Let's Encrypt).

If your own address changes often, add the new one before you remove the old. The panel's Droplet Console connects through DigitalOcean's agent and not through sshd, so `AllowUsers` and the cloud firewall do not apply to it. Open it once during set-up and confirm you get a prompt, so you know you have a way in before you need one. (We could not test that on a real droplet when we wrote this.)

### What can be narrowed on the deploy user

The deploy user is root-equivalent twice over. It is in the `docker` group and anyone in that group can start a container that mounts the whole disk. That cannot be narrowed without a rootless Docker set-up that the small droplet is not sized for. So the real protection for that account is who can reach port 22 (the cloud firewall and `AllowUsers` above) and the key itself: keep it on a hardware token (a FIDO2 key with `ssh-keygen -t ed25519-sk`) and give it a passphrase.

What does not need root at all is every script in `infra/scripts/` that you run day to day. `deploy.sh`, `backup.sh`, `restore.sh`, `db-role.sh` and `check-nginx.sh` use the docker group and never call `sudo` (only `check-nginx.sh` does and only for `nginx -T`). So the passwordless rule for every command is not needed. By default `harden.sh` now writes a sudoers file that allows exactly these commands and nothing else: `nginx -t`, `nginx -T`, `systemctl reload nginx`, `systemctl status nginx`, `ufw status`, `fail2ban-client status sshd`, `certbot certificates`, `certbot renew --dry-run` and `systemctl reboot`. It also takes the account out of the `sudo` group and adds it to `adm` so it can read the Nginx logs. This stops mistakes and a casual attacker. It does not stop someone who holds the key from using Docker to become root, so do not count it as more than that.

Root work later (a new Nginx site file, a new package, a change to `ufw`) is done through the Droplet Console in the DigitalOcean panel, which does not use sshd. Root login over SSH is off and the deploy user's sudo is narrow, on purpose. If you want to work as root from SSH for a while, open the Droplet Console, run `DEPLOY_SUDO=full bash infra/scripts/harden.sh` there and run it again without that variable when you are done. After a kernel update a reboot is `sudo systemctl reboot`, which the rule allows.

---

## Section 4: Install Docker, Nginx and Certbot

`install.sh` adds Docker's own apt repository and installs Docker Engine with the compose plugin, then Nginx, Certbot and `age` (which encrypts the backups). It also adds a weekly Nginx reload, which renews the TLS session ticket key (see the site file). Run it as root, from the first session:

```bash
cd /home/deploy/phaemos
DEPLOY_USER=deploy bash infra/scripts/install.sh
```

Then check from a fresh sign-in as the deploy user, so the `docker` group applies:

```bash
docker compose version
```

---

## Section 5: Create the backend environment file

```bash
cd /home/deploy/phaemos
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

Generate the secrets on the droplet. `set-secret.sh` writes one random value into one line of the file without the value ever being on a command line or in the shell's history (a `sed -i "s|...|$(openssl rand ...)|"` would put it in both). It refuses to touch a line that already has a value:

```bash
bash infra/scripts/set-secret.sh SECRET_KEY 32
bash infra/scripts/set-secret.sh POSTGRES_PASSWORD 24
bash infra/scripts/set-secret.sh POSTGRES_APP_PASSWORD 24
bash infra/scripts/set-secret.sh REDIS_PASSWORD 24
```

**Keep a safe copy of this file now**, in a password manager or encrypted storage, apart from the backup key. `SECRET_KEY` is not only a signing key. Every machine's key check and every person's two-step secret is derived from it, so a restore on a new droplet with a new `SECRET_KEY` leaves every machine unable to post and every two-step secret unreadable. The `.env` file is backup material in the same way the database is (see Section 14).

Then make the backup key pair on your own computer, never on the droplet. Install `age` there and run `age-keygen -o phaemos-backup.key`. It prints the public key (it starts `age1`). Put that public key in `backend/.env` as `BACKUP_AGE_RECIPIENT`. Keep the key file in a password manager or on an encrypted drive and a second copy somewhere else: without it every backup is unreadable. The droplet never sees it.

Then edit the rest by hand:

```bash
nano backend/.env
```

At minimum, set these:

```env
ENVIRONMENT=production
ALLOWED_ORIGINS=https://dashboard.phaemos.com,https://phaemos.com
DASHBOARD_URL=https://dashboard.phaemos.com
```

What the file must and must not hold:

- `ENVIRONMENT` in this file does not matter on the droplet: the compose file sets `production` itself. `deploy.sh` still fails if the API does not report production. In production the interactive API docs (`/docs`, `/redoc` and `/openapi.json`) are switched off.
- `SECRET_KEY` is checked twice. `deploy.sh` refuses a key shorter than 32 characters before anything starts. The API itself refuses an empty key anywhere and, outside development, a short one or one that looks like a placeholder or a test key.
- `POSTGRES_USER` and `POSTGRES_PASSWORD` are the database owner. They run the migrations and the backups and nothing else. The API signs in as `POSTGRES_APP_USER` with `POSTGRES_APP_PASSWORD`, a role that `deploy.sh` creates and that can read and write the application's tables and do nothing more. The names must differ and so must the passwords and `deploy.sh` checks both. The compose file blanks `POSTGRES_PASSWORD` in the API's own environment, so the API never holds the owner's password. `REDIS_PASSWORD` is the Redis password and the API's address for Redis carries it.
- `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD` start the database and build the schema job's address, so they always match. Use letters and digits in the password because it sits inside a URL. The generated value already does. `deploy.sh` checks this. The password is fixed when the database volume is first created, so changing it in the file later breaks the login. To change it afterwards, change it inside the database too and then in the file. Do it without typing the password into a command: `pc exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'` opens psql and `\password` there asks for the new password twice without echoing it or writing it to history. Then change the line in `backend/.env` with an editor.
- `ALLOWED_ORIGINS` lists the origins the browser may call the API from, separated by commas. With the dashboard on its own address list both the dashboard and the site (its contact form calls the API). The first one is also where the API sends people after a Google, GitHub or Microsoft sign-in, so put the dashboard first.
- A value that contains a dollar sign must be wrapped in single quotes, because Compose reads `$` as the start of a variable. The generated values contain none.
- `ALLOWED_ORIGINS` for production is `https://dashboard.phaemos.com,https://phaemos.com`. `www.phaemos.com` redirects to the apex in Vercel (Section 11), so it is not an origin a browser calls from. With one address for both, list just that one.
- `BACKUP_AGE_RECIPIENT` is the public key above. `backup.sh` refuses to write a backup without it. `BACKUP_RCLONE_REMOTE` is optional and covered in Section 14.
- `TRUSTED_PROXIES`, `REDIS_URL`, `DATABASE_URL`, `ENVIRONMENT`, `FIRMWARE_STORAGE_PATH` and `MODEL_PATH` are set by the compose file for this layout. Leave them alone.

The sections below add the contact form, email, SMS and sign-in values. Come back to this file for each and run `deploy.sh` again afterwards.

### Contact form

Set these two. Only the API reads them:

```env
TURNSTILE_SECRET_KEY=<from the Cloudflare Turnstile dashboard>
# CONTACT_EMAIL_TO=contact@phaemos.com
```

Without `TURNSTILE_SECRET_KEY` the contact form answers 503 in every environment except `ENVIRONMENT=development`, where the check is skipped. `CONTACT_EMAIL_TO` defaults to `contact@phaemos.com`. Leave the line commented unless the messages should go elsewhere, because an empty value replaces the default with nothing. The matching site key goes into Vercel (Section 11).

### Sign-in with Google and GitHub

Create an OAuth app with each provider. Use these redirect addresses:

| Provider | Redirect address |
| --- | --- |
| Google | `https://api.phaemos.com/api/v1/auth/google/callback` |
| GitHub | `https://api.phaemos.com/api/v1/auth/github/callback` |
| Microsoft (optional) | `https://api.phaemos.com/api/v1/auth/microsoft/callback` |

Put each client id and secret in `backend/.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`). The redirect addresses in the API default to localhost, so also uncomment `GOOGLE_REDIRECT_URI` and `GITHUB_REDIRECT_URI` in `backend/.env` with the addresses from the table. They must match the provider settings exactly. After sign-in the API sends the browser to the first entry of `ALLOWED_ORIGINS`.

### Email and SMS

Contact messages, invitations and alert emails go through Resend. Critical alert texts go through Brevo. Set them up in this order:

1. In Resend, add and verify the sending domain (the DNS records Resend lists).
2. Create a Resend API key with Send access.
3. Set `RESEND_API_KEY` and `FROM_EMAIL` (an address on the verified domain, default `no-reply@phaemos.com`) in the API environment.
4. Set `ALERT_EMAIL_TO` to the alert recipients, comma-separated.
5. Set `DASHBOARD_URL` to the public address of the dashboard, for example `https://dashboard.phaemos.com` with no trailing slash. Invitation links are built from it and they carry the token in the address fragment (`/accept-invite#token=...`). It defaults to `http://localhost:3000`.
6. In Brevo, buy SMS credits. A text cannot send without them.
7. Create a Brevo API key and choose the sender name for the text.
8. In the Brevo account, check the authorised IP setting for API keys. If it is on, the droplet's public address must be on the list or Brevo will refuse the call.
9. In the Brevo account, check whether the destination countries need a registered sender name. Some countries do. A text can be dropped or relabelled without it.
10. Set `BREVO_API_KEY` and `BREVO_SMS_SENDER` (11 letters or digits at most. A numeric name may have up to 15 digits. No spaces. Default `PHAEMOS`) in the API environment.
11. Give the device owner a phone number in E.164 form (for example `+447700900000`) on their profile. The profile refuses any other format. Critical alerts text the owner of the device.
12. Run `infra/scripts/deploy.sh` again so the API reads the new values.
13. Confirm the API runs as production (the `pc exec -T backend python -c ...` command in Section 7 prints `production False`) before testing the form. Any value other than `development` makes the contact form answer 503 when Resend is not set up.

Once the dashboard is live, try each of these once. The [deployment checklist](deployment-checklist.md) lists the exact steps and results.

Repeats and limits, so a stuck rule cannot use up the quotas:

- The first notification for a device, metric and severity goes at once. A repeat goes at most once an hour while the rule stays breached. The window is kept in Redis, which writes to a Docker volume, so it holds across workers and restarts. A send that fails frees its window, so the next reading tries again.
- A daily cap counts across all devices and ends at midnight UTC. `ALERT_EMAIL_DAILY_CAP` defaults to 50 and each recipient counts. `ALERT_SMS_DAILY_CAP` defaults to 20. When a cap is reached the API logs one warning for that day and skips the rest.
- The sums: Resend's free plan allows 100 emails a day. With the default cap the alerts use at most 50 of them, which leaves 50 for contact messages and invitations. One stuck rule with one recipient would send 24 emails and 24 texts in a day without the caps. The email cap stops it at 50 in all and the SMS cap at 20 in all.
- The model's anomaly alerts follow the same window and caps under the metric name `anomaly`. A critical anomaly texts the owner like a critical rule does.
- An info alert sends no email. Only warning and critical alerts do. Only critical alerts text.
- A text is at most 160 plain characters, so it is one message part. What a part costs depends on the destination country.

---

## Section 6: Start the stack

The first install has no deploy-user copy of the release keys checked and no Nginx site yet, so it needs two overrides, once. Later deploys need neither:

```bash
cd /home/deploy/phaemos
DEPLOY_FIRST_INSTALL=yes DEPLOY_SKIP_NGINX_CHECK=yes bash infra/scripts/deploy.sh
```

`DEPLOY_FIRST_INSTALL=yes` skips deploy.sh's own signed-tag check and says so in a warning. It is **refused** once the database holds the application's tables, so it cannot be used to deploy an unsigned checkout over a live system. You verified the tag in Section 2 with a command that is not in the tree and that is the check that matters on a first install. `DEPLOY_SKIP_NGINX_CHECK=yes` skips only the Nginx check, until Section 9 has been done. The two are separate so that getting past a failed Nginx check never turns the signature check off. After Section 9 every deploy goes from a signed tag (below).

`deploy.sh` does this in order:

1. Unless the override is set, checks the checkout is exactly at a tag, that no tracked file has changed, that there is no untracked file and no ignored file where the build or the migrations look (an untracked `backend/migrations/999_x.sql` would run as the database owner), that the tag object carries the name of the ref (an old signed tag cannot be filed under a new name) and that its **SSH** signature verifies against the keys in the file named by `DEPLOY_ALLOWED_SIGNERS` (default `~/.config/phaemos/allowed_signers`). A PGP signature is refused, because git would check it against the deploy user's keyring and not against that file. It refuses anything else and prints the tag and the commit it is deploying.
2. Checks `backend/.env` without printing it: a secret key of 32 characters or more, the three passwords and that the API's database user differs from the owner.
3. Starts the database alone and makes or refreshes the API's database login (`infra/scripts/db-role.sh`). This is idempotent, so it is the same step on a first install and on a droplet that already runs.
4. Builds the image, then asks the owner's login whether the schema already exists. On a **database that already holds a schema** the numbered SQL files in `backend/migrations/` are applied first, as the owner, one file at a time in order and each stopping at its first error. The one-shot `schema` job then creates any table the new models need, **as the owner**. The API's own login has no right to create tables, so first-start table creation lives in that job and nowhere else. On a **first install** the job runs first and the migrations follow, once. The new code selects columns that an older database lacks, so in both cases everything is in before the API starts and the API's compose entry waits for the job to finish. The tables belong to the owner and the role's default privileges give the API read and write on them as soon as they exist.
5. Starts the database, Redis and the API with `docker compose up -d --wait`. Redis starts with its password. The API signs in as the limited role.
6. Checks the role again (`db-role.sh --check`): it must not be a superuser, must read and write every table and must own nothing.
7. Waits for `http://127.0.0.1:8000/status` to answer `operational` and asks the API container whether it runs as production (it reads the same settings the API read: the API no longer names its environment to a stranger). Then it checks that a request through the published port is attributed to the caller's own address, so the API believes the proxy's `X-Real-IP` and the rate limits tell visitors apart.
8. Runs `infra/scripts/check-nginx.sh`. It compares the installed site file and the text Nginx has loaded, with `infra/nginx/api.phaemos.com.conf` byte for byte and fails loudly on any difference. A grep for the limits, HSTS and the handshake refusal is a second test on the whole running configuration.
9. Removes old images and prints `deployed: <tag> at commit <hash>`.

It prints no secret and is safe to run again. The equivalent plain command is `docker compose --env-file backend/.env -f infra/docker-compose.prod.yml up -d`. The `--env-file` matters: without it the checks for missing values cannot see `backend/.env`. A shorthand for the rest of this guide:

```bash
alias pc='docker compose --env-file backend/.env -f infra/docker-compose.prod.yml'
```

Add that line to `~/.bashrc` to keep it for later sessions. Run `pc` from `/home/deploy/phaemos`.

> [!WARNING]
> Do not run `docker compose config` on the droplet. It prints every resolved value including the secrets.

### Signed releases

A release maintainer signs each tag with an SSH key: `git config gpg.format ssh`, `git config user.signingkey ~/.ssh/release_key.pub` and `git tag -s vX.Y.Z -m "vX.Y.Z"`, then pushes the tag. The droplet's `~/.config/phaemos/allowed_signers` has one line per release key, in the form `maintainer@phaemos.com namespaces="git" ssh-ed25519 AAAA...` (the public key). That file came from your own computer (Section 2), not from the repository. Keep its keys few and review them when a maintainer leaves.

To deploy, **verify first, with a command that is not in the checkout and only then check out and run**:

```bash
cd /home/deploy/phaemos
git fetch --tags
git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile=$HOME/.config/phaemos/allowed_signers verify-tag vX.Y.Z
git checkout vX.Y.Z
bash infra/scripts/deploy.sh
```

Why both. The first command runs git's own code against your keys and nothing from the tag, so a tag that someone with write access published without a release key's signature is refused before one line of it runs. `deploy.sh` runs a second time from the tag itself, which is the weaker line: it is part of the thing it checks, so a malicious tag can change it. What it still catches is a checkout that drifted (a changed, untracked or stray file, a tag with the wrong inner name, a PGP signature, an old tag filed under a new name). Neither line stops a release maintainer's own key being stolen: protect that key.

### The containers

Every container drops all Linux capabilities, cannot gain any (`no-new-privileges`), has a read-only root file system with small memory-only `tmpfs` folders for what must be written (`/tmp` and Postgres's socket folder) and has a process, memory and CPU ceiling. The images for the database and Redis are pinned by digest as well as tag. No capability had to be given back. The database and Redis images start as root and change user in their entrypoint, which needs the capabilities we drop, so the compose file starts them as their own users from the beginning (`user: 999:999` and `user: 999:1000`). We proved that on the throwaway stack: with all capabilities dropped and the image's default user, Postgres stops with `chmod: changing permissions of '/var/lib/postgresql/data': Operation not permitted` and Redis with `setpriv: setresuid failed: Operation not permitted`. An existing droplet's volumes are already owned by those users, so nothing needs to move.

### Refresh the pinned images

The digest makes sure the droplet runs the image we tested and not whatever the tag points at today. To move to a newer build of the same tag, on a machine that can run Docker:

```bash
docker pull postgres:15
docker image inspect postgres:15 --format '{{index .RepoDigests 0}}'
docker pull redis:7-alpine
docker image inspect redis:7-alpine --format '{{index .RepoDigests 0}}'
```

Put each printed `name@sha256:...` after the tag in `infra/docker-compose.prod.yml` (for example `postgres:15@sha256:...`), try it on a copy of the stack, then release it as a signed tag. `docker buildx imagetools inspect postgres:15` prints the current digest without pulling. Do this every month or after a security notice, because a pinned image no longer picks up fixes by itself.

### How the schema is created and changed

The API has no Alembic setup in use. It does two things:

- It creates any table the models define that is missing (`Base.metadata.create_all`, through `create_tables()` in `app/db.py`). Importing the app does **not** do this any more: the API calls it at start only in development and in production the one-shot `schema` job runs it as the database owner (the API's own login may not create tables). The job imports `app.main` so every model is registered and then calls `create_all` itself, so it does not depend on the app doing it. It does not alter an existing table and it does not create everything: the audit log table and some indexes come only from the SQL files.
- The SQL files in `backend/migrations/` add those and the columns an older database lacks. `deploy.sh` and `make migrate` both run `infra/scripts/migrate.sh`. It applies each file **once**, in order and records it in the table `schema_migrations` (file name, a hash of the file, when). Some files change data (020 resolves open alerts, 028 and 029 collapse duplicates), so running every file on every deploy was not safe. A file that fails is not recorded and stops the deploy. A file that was applied and has since been **edited** stops the deploy with a clear message: an applied migration must not be edited, so the change goes in a new numbered file. If you have read the difference and the edit is harmless, `bash infra/scripts/migrate.sh --rehash FILE` records the new hash without running the file. A database that has tables and no record (only a developer's database can) has every file run once and recorded. The API's own login cannot read or change the record.

A new column on an existing table therefore needs a new numbered file in `backend/migrations/` together with the model change. A file that adds a column must be safe while the old code runs, which means a nullable column or one with a default. Migrations 012 and 015 set `lock_timeout` to three seconds, so one that cannot get its lock fails the deploy instead of queueing behind a long read and running `deploy.sh` again retries it. Migration 014 builds an index with `CONCURRENTLY` and is applied outside a transaction.

### Migration 033 stops on duplicate addresses

Migration 033 lowers every email address and adds a unique index on the lower-case address. If two accounts already differ only in case (`Jane@example.com` and `jane@example.com`) it stops on purpose and the whole file rolls back. The deploy stops with the message `migration 033 stopped`, which lists the ids of each group of clashing accounts. Nothing was changed.

To carry on:

1. Look at each group: `SELECT id, email, role, created_at, last_login FROM users WHERE lower(email) IN (SELECT lower(email) FROM users GROUP BY 1 HAVING count(*) > 1) ORDER BY lower(email), created_at;`
2. Decide which account keeps each address. Delete the other one in the admin page or give it an address that cannot clash with `UPDATE users SET email = 'jane+old@example.invalid' WHERE id = '<id>';`
3. Run `bash infra/scripts/deploy.sh` again. Migration 033 then lowers the addresses and builds the index.

### Ports and the proxy address

The API is published on `127.0.0.1:8000` only. The database and Redis publish nothing. Docker's published ports bypass `ufw`, so a wider binding would put the API on the internet without TLS.

Nginx runs on the host and reaches the API through that published port. The API then sees the connection coming from the gateway address of the `edge` Docker network, not from `127.0.0.1`. The compose file pins that network to `172.29.0.0/24` with the gateway `172.29.0.1` (the database, Redis and the schema job are on a second network, `data`, that has no route out) and sets `TRUSTED_PROXIES` to that one address, so the API believes the `X-Real-IP` header Nginx sets and rate limits each visitor separately. Without it every visitor would share one limit. If `172.29.0.0/24` clashes with another network on the droplet, change the subnet, the gateway and `TRUSTED_PROXIES` together in the compose file.

### Persistence

| Volume | Holds | Why it is kept |
| --- | --- | --- |
| `postgres_data` | The database | The data |
| `redis_data` | The repeat windows and daily alert caps | Without it a deploy resets them and a stuck rule could send a second text inside the hour |
| `firmware_data` | The uploaded firmware file | It survives a rebuild |
| `model_data` | The trained anomaly model | The model is written here when an admin retrains it. Without the volume every deploy that recreates the container would return anomaly scoring to zero |

Rate limit counters live in the API's memory and restart from zero on a deploy. That is acceptable for per-minute and per-hour limits.

---

## Section 7: Check the API on the droplet

The API image starts uvicorn with `--no-access-log`, `--ws-max-size 8192`, `--ws-per-message-deflate false` and `--limit-concurrency 150` (see the comment above `CMD` in `backend/Dockerfile`). The size cap and the missing compression stop a stranger exhausting the 384 MB container with one large socket frame. The concurrency limit answers 503 beyond 150 open connections and requests, which fits about 100 idle sockets plus the 15 database connections. The Dockerfile also refuses to build on Python older than 3.12.4, because the webhook address check depends on the standard library's address tables from that release.

Check the API before Nginx is involved:

```bash
curl http://localhost:8000/
```

Expected: `{"status":"ok","service":"PHAEMOS API","version":"1.0.0"}`. The root does not name the environment, on purpose: it tells a stranger which controls are relaxed.

```bash
curl http://localhost:8000/status
```

Expected: `"status":"operational"` with `"database":"ok"` and `"redis":"ok"`. This endpoint reports health only.

To see the environment, ask the container (this is what `deploy.sh` does):

```bash
pc exec -T backend python -c 'from app.config import settings; print(settings.environment, settings.is_development)'
```

Expected: `production False`. If it says anything else, fix `ENVIRONMENT` in `backend/.env` and run `deploy.sh` again.

---

## Section 8: DNS records

Add these records in your DNS provider (Cloudflare or DigitalOcean DNS):

| Name | Type | Value | Notes |
| --- | --- | --- | --- |
| `@` | A | Vercel's address | Root domain: Vercel handles this via its own records |
| `api` | A | `YOUR_DROPLET_IP` | Points to the droplet |
| `dashboard` | CNAME | `cname.vercel-dns.com` | The dashboard: the same Vercel project as the site (Section 11) |
| `docs` | CNAME | `cname.vercel-dns.com` | Vercel docs project |
| `status` | CNAME | `<from Instatus dashboard>` | Instatus status page |

If the DNS provider is Cloudflare, keep the `api` record on **DNS only** (grey cloud) permanently. A proxied record would make every visitor reach the API from a Cloudflare address, so all visitors would share one address for rate limits.

`app.phaemos.com` is deliberately left unused and should not be pointed anywhere, so it stays free for a real app later. A record left pointing at a service nobody uses is a takeover risk.

For `phaemos.com` itself (the Next.js app), follow the custom domain steps in Section 11: Vercel provides its own records.

---

## Section 9: Nginx and TLS

The site file `infra/nginx/api.phaemos.com.conf` is complete: the TLS listener, the certificate paths, the redirect, HSTS, the limits and the refusal of unknown host names are all written in it. Certbot is used only to **issue and renew the certificate**, with its webroot method, so it never edits the file and its work and ours cannot fight. Do this from the root session of Section 3 (every command here runs as root, so none has `sudo` in front), with the DNS record from Section 8 in place. The deploy user cannot do these steps afterwards: its sudo rule does not allow them.

### Issue the certificate first

Nginx refuses to load a site whose certificate is missing, so the certificate comes before the site file. The stock Nginx site that `install.sh` leaves in place answers the challenge:

```bash
certbot certonly --webroot -w /var/www/html -d api.phaemos.com
systemctl list-timers | grep certbot
certbot renew --dry-run
```

`install.sh` also placed a renewal hook that reloads Nginx after each renewal. The site file serves the same challenge folder, so renewals keep working once the stock site is gone.

### Keep the web server logs for 14 days

`install.sh` copies `infra/logrotate/phaemos-nginx` to `/etc/logrotate.d/nginx`, so a new droplet already does this. On a droplet that was set up earlier, run this once from the root session, then check the rule parses:

```bash
install -m 644 infra/logrotate/phaemos-nginx /etc/logrotate.d/nginx
logrotate --debug /etc/logrotate.d/nginx
```

Expect no error. The privacy notice promises that access and error logs are kept for 14 days and this file is what enforces it. Check from time to time that `ls /var/log/nginx` holds nothing older than 14 days.

### Install the Nginx site

First write the origins file that the site includes. It is generated from `ALLOWED_ORIGINS` and `CREDENTIALED_ORIGINS` in `backend/.env`, the settings the API's CORS reads, so an origin is changed in one place. It refuses a wildcard. Nginx will not load the site without it. Run it again as root whenever either setting changes (`check-nginx.sh` fails a deploy that finds the installed file out of date):

```bash
cd /home/deploy/phaemos
bash infra/scripts/render-cors.sh > /etc/nginx/phaemos-cors-origins.conf
```

Then the site:

```bash
cp infra/nginx/api.phaemos.com.conf /etc/nginx/sites-available/api.phaemos.com.conf
ln -sf /etc/nginx/sites-available/api.phaemos.com.conf /etc/nginx/sites-enabled/api.phaemos.com.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

The site file does the following:

- Answers `301` from plain HTTP to HTTPS and serves nothing else there but the certificate challenge.
- Answers HTTPS for `api.phaemos.com` only. A request or a TLS handshake for any other name gets no answer (`444` on port 80 and `ssl_reject_handshake` on port 443). The certificate is not even shown to a scanner.
- Sends `Strict-Transport-Security: max-age=31536000`, `X-Content-Type-Options: nosniff` and `Cache-Control: no-store` on every answer, hides the upstream's `Server` header and sets `server_tokens off`. HSTS makes browsers use HTTPS only for the name for a year, so check HTTPS works before you rely on it.
- Limits requests per client address with `limit_req` and answers `429`, in three classes. The **tight** class (30 a minute with a burst of 10) is exactly the routes a stranger can use to guess or flood: `/api/v1/auth/` login, register, refresh, `2fa/verify`, `accept-invite`, `invite/check`, `reset-password`, the provider starts and callbacks (`google`, `github`, `microsoft`, `apple`) and `/api/v1/contact`. Signed-in administration (`/api/v1/users`, `/invitations`, `/service-accounts`, `/tokens` and their deprecated `/api/v1/auth/...` aliases) is **general** (20 a second, burst 40), so a page of the dashboard is not throttled. The **ingest** class (the single reading and `/api/v1/telemetry/batch`) is 30 a second with a burst of 60. The arithmetic for ingest: fifty nodes behind one address, each posting every 3 to 5 seconds, is 50 / 3 = 17 a second at the worst and 10 a second normally, so 30 a second is a little under twice the worst case and a burst of 60 lets every node post at once after an outage. A batch is one request however many readings it holds and the API allows 1,200 readings a minute for a device and 6,000 for the site, which is at most 12 batches a minute from a device and 60 from the site, so the zone never throttles a gateway draining a backlog: the API's own allowance does. `nodelay` serves a request inside the burst at once and refuses the rest. Raise the rates if a site has far more nodes behind a single address. The zones count requests, so a node that opens a new TLS connection for every post is not penalised for it.
- Limits every request body to 64 kB, except two exact routes: the batch ingest route (`/api/v1/telemetry/batch`) at 600,000 bytes (the API's own limit for 100 readings of about 550 kB at the worst, with a 30 second body timer) and the firmware upload (`/api/v1/firmware/upload`) at 3 MB. The single reading route keeps 64 kB. A larger body is answered `413` before the API reads it.
- Drops slow clients: 10 seconds for a header or a body that stalls, 15 seconds for a client that stops reading and 30 seconds for an idle kept-alive connection. The firmware upload gets 60 seconds for its body.
- Keeps TLS sessions in a shared cache and issues session tickets, so a hub that opens a new connection for every post resumes the last session and skips the costly key exchange. A ticket lives 10 minutes and the weekly reload from `install.sh` renews the ticket key.
- Proxies everything to `127.0.0.1:8000` and sets `X-Real-IP`, `X-Forwarded-For` and `X-Forwarded-Proto`.
- Upgrades WebSocket connections on `/ws/` (the live feed is `/ws/telemetry/{device_id}`) with a one hour read timeout, because a socket can be quiet between readings. It keeps `/ws/` out of the access log, because an older dashboard sends the access token in the socket address.
- Limits live sockets: 10 an address and 60 in all (so a handful of addresses cannot fill the API's 150 slots with sockets that say nothing) and opening sockets is itself limited to 5 a second an address. Everything else is limited to 100 connections an address. `429` beyond any of these. Slow clients are contained, not stopped: a body that trickles one byte at a time keeps its connection for as long as it likes, up to the 100 an address.
- Answers 404 for `/metrics` and adds no CORS headers (the API answers for the dashboard origin).
- Rewrites any redirect that names `http://api.phaemos.com/` into `https://`. The API now answers 404 for a path with a trailing slash instead of redirecting, so this is a second guard: a redirect built from a request that reached the API over plain HTTP would otherwise send a client's key in clear on port 80.
- Answers its own errors (429, 413, 502 and 504) in the API's one JSON shape, `{"code", "detail", "request_id"}`, with the stable codes `rate_limited`, `payload_too_large`, `upstream_unavailable` and `upstream_timeout`, `Content-Type: application/json`, the security headers and the CORS headers a browser needs to read an error. A 429 carries `Retry-After: 2`: the slowest class (sign-in) gets a token back every 2 seconds, so 2 seconds is the earliest a retry can succeed in any class. An error the API sends itself passes through untouched. The allowed origins come from the same two settings as the API's (`ALLOWED_ORIGINS` and `CREDENTIALED_ORIGINS` in `backend/.env`) through a generated file, never a wildcard (below).
- Offers TLS 1.2 and 1.3 only and for TLS 1.2 only forward-secret AES-GCM and ChaCha20 suites (no CBC and no SHA-1). The hub's TLS library has the AES-GCM suites with ECDHE compiled in.
- Opens no IPv6 listener. Nginx would count a visitor by the whole IPv6 address while the API counts it by /64, so one /64 would get a limit per address. Add no AAAA record until IPv6 is wanted and the zones are keyed on the /64.
- Returns nothing (444) for a request that named the right host in the TLS handshake and a wrong one in the request.

Check the whole thing from the droplet:

```bash
nginx -t
curl -i https://api.phaemos.com/status
curl -i http://api.phaemos.com/status
```

Expected: `HTTP/1.1 200` with the three headers above and `"status":"operational"`, then a `301` to the HTTPS address. Then run `bash infra/scripts/check-nginx.sh` as the deploy user. It must print that the installed site is the repository's file, byte for byte and the one running. `deploy.sh` runs the same check on every deploy and fails on any difference, for example after someone copies an older site file over this one. That also means a site file edited on the droplet is refused: change the file in the repository and release it.

### Why Certbot does not edit the file

`certbot --nginx` rewrites the site file, adds its own TLS lines and a second port 80 block and would conflict with the 443 block we ship. If you ever run it, it can leave two `listen 443` blocks for the same name and `nginx -t` will say so. Use `certonly --webroot` as above and copy the repository file over the installed one whenever it changes: nothing of Certbot's is in it, so nothing is lost.

### Finish the first set-up

From the root session, once the site works over TLS, run the hardening script again without `DEPLOY_SUDO=full`, so the deploy user keeps only the narrow sudo rule. It asks you to confirm a second sign-in again before it touches sshd:

```bash
bash /home/deploy/phaemos/infra/scripts/harden.sh
```

Then, as the deploy user, deploy from a signed tag as in Section 6. That run checks Nginx too.

---

## Section 10: Create the first admin and register a machine

The dashboard has no sign-up page and no page for adding a machine. The first admin comes from a command on the droplet and a machine is registered through the API. Passwords need at least eight characters with an uppercase letter and a digit.

Registration is closed in production. `POST /api/v1/auth/register` answers `403` and a first sign-in with Google, GitHub or Microsoft is refused for an address with no account, because a self-made account is a viewer and a viewer reads every machine. People join through an invitation from an admin. To open registration on purpose, set `REGISTRATION_OPEN=true` in `backend/.env`.

1. Create the first admin on the droplet. The command asks for an email and a password, which is typed without echo and never shown or taken from an argument:

   ```bash
   cd /home/deploy/phaemos
   pc exec backend python -m app.scripts.create_admin
   ```

   Expect `Created admin <email>.`. It refuses an email that already has an account and writes an audit entry.
2. Set the password in your shell for the next step. It is typed without echo and stays on your computer:

   ```bash
   read -rsp 'Password: ' PW; echo
   ```

3. Log in with the email you gave in step 1 to get a token, then register a machine. The response carries the device `id` and its `api_key`, which is shown once:

   ```bash
   TOKEN=$(curl -s -X POST https://api.phaemos.com/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d "{\"email\": \"admin@example.com\", \"password\": \"$PW\"}" | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
   curl -s -X POST https://api.phaemos.com/api/v1/devices \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"name": "Test machine", "location": "Lab", "type": "esp32"}'
   ```

   Store the `api_key` where the device needs it. It cannot be shown again.

Registration stays closed. To add people, an admin invites them with `POST /api/v1/auth/invite`. The invitation sets their role.

---

## Section 11: Vercel - frontend (phaemos.com)

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub.
2. Click **Add New Project** and import the `phaemos/phaemos` repo.
3. Set **Root Directory** to `frontend/`.
4. Set **Framework Preset** to **Next.js** (auto-detected).
5. Under **Environment Variables**, add every variable from `frontend/.env.example`. At minimum:
   - `NEXT_PUBLIC_API_URL` = `https://api.phaemos.com`
   - `NEXT_PUBLIC_TURNSTILE_SITE_KEY` = the site key from the Cloudflare Turnstile dashboard. The secret key goes only in `backend/.env`.
   - `NEXT_PUBLIC_SITE_URL` = `https://phaemos.com` and `NEXT_PUBLIC_APP_URL` = `https://dashboard.phaemos.com`. Different values turn on split mode: one deployment answers on both addresses and the proxy sends each request to the address that owns the page (see `frontend/README.md`). Leave both unset for one address. **Scope both to the Production environment only** in Vercel (untick Preview and Development). With them set on a preview deployment every "Dashboard" button and legal link jumps to the live site. With them unset a preview runs as one address.
   - `NEXT_PUBLIC_GA_ID` = from Google Analytics (optional). Leave it unset for no analytics and no cookie banner. The tag and the banner run on the public site only, never on the dashboard, sign-in or invitation pages. The tag keeps its cookies on the site's own address. Both `NEXT_PUBLIC_` values are read at build time, so redeploy after changing them.
6. Click **Deploy**.
7. Under **Project Settings** -> **Domains**, add `phaemos.com`, `www.phaemos.com` and `dashboard.phaemos.com` to this one project. Make the apex `phaemos.com` the primary domain and set `www.phaemos.com` to redirect to it. Add the `dashboard` CNAME record from Section 8 (or the record Vercel shows) for the dashboard address. Do not create a second project: both addresses are served by this deployment.
8. On the API (`backend/.env`) set `ALLOWED_ORIGINS=https://dashboard.phaemos.com,https://phaemos.com` and `DASHBOARD_URL=https://dashboard.phaemos.com`, then restart the API. The OAuth return address is the first entry of `ALLOWED_ORIGINS`, so it is the dashboard. The redirect addresses registered with Google, GitHub and Microsoft stay on `https://api.phaemos.com/api/v1/auth/<provider>/callback` and do not change.
**Use two addresses in production.** With one address the public site and the dashboard share an origin, so any script that runs on a site page (the Turnstile widget on the contact page, Google Analytics when it is on) runs beside the access token in `localStorage` and could read it. With two addresses the token exists only on the dashboard's origin, where the content security policy allows no inline script and loads neither analytics nor Turnstile. One address is for local development and small installations. In that mode the Google tag is never loaded while a token is held in the browser, but the Turnstile widget still is, so treat it as the weaker layout.

**The invitation link carries its token in the address fragment only** (`/accept-invite#token=...`), which a browser never sends to a server. A link with the token in the query string (`?token=...`, the form of early versions) is no longer accepted: the page tells the person to ask for a new invitation.

**A production build needs an `https` API address.** `NEXT_PUBLIC_API_URL` is baked into the browser bundle and has no default. `next build` and the frontend Dockerfile stop when it is unset or not `https://`, so a build can never ship a bundle that points visitors at `http://localhost:8000`. Pass `--build-arg NEXT_PUBLIC_API_URL=https://api.phaemos.com` to `docker build`. A local test build that really is http must say so with `ALLOW_INSECURE_API_URL=1` (`--build-arg ALLOW_INSECURE_API_URL=1` for Docker).

9. The sign-in cookie is set for the dashboard address only (never a parent domain). The site cannot read it, so the site's main button reads "Dashboard" and links to `https://dashboard.phaemos.com`.

---

## Section 12: Vercel - documentation site (docs.phaemos.com)

1. In the same Vercel account, click **Add New Project** and import `phaemos/phaemos` again (a second project).
2. Set **Root Directory** to `.` (the repo root, not `frontend/`).
3. Set **Framework Preset** to **Other**.
4. Set **Build Command** to:

   ```bash
   pip install -r requirements-docs.txt && mkdocs build
   ```

5. Set **Output Directory** to `site`.
6. Click **Deploy**.
7. Under **Project Settings** -> **Domains**, add `docs.phaemos.com`.

---

## Section 13: Instatus - status page (status.phaemos.com)

1. Create a free account at [instatus.com](https://instatus.com).
2. Create a new status page named **Phaemos Status**.
3. Add two components:
   - **Platform** - monitors `https://phaemos.com` (HTTP, 60s interval)
   - **API** - monitors `https://api.phaemos.com/status`, keyword match `operational` (HTTP, 60s interval)
4. Under **Settings** -> **Domain**, add `status.phaemos.com` as the custom domain.
5. Instatus provides a CNAME target. Add it to your DNS as a `status CNAME <instatus-target>` record.
6. Enable email and/or Slack notifications for incidents.

---

## Section 14: Backups and restore

`infra/scripts/backup.sh` writes a compressed `pg_dump`, **encrypted with `age` to the public key in `BACKUP_AGE_RECIPIENT`**, named `phaemos-YYYY-MM-DD_HHMMSS.sql.gz.age` in `~/backups` and keeps the newest seven (`KEEP` in the script, so seven days on the server). The dump is encrypted as it streams, so no plain copy touches the disk. The files are readable by the deploy user only. It refuses to write an unencrypted backup: with no recipient set it stops and there is no override. It exits non-zero if the dump fails or comes out empty and it never leaves a half-written file behind.

```bash
bash /home/deploy/phaemos/infra/scripts/backup.sh
```

Run it daily from the deploy user's crontab (`crontab -e`). The script writes its own log to `~/backups/backup.log` and creates the folder itself:

```cron
15 3 * * * bash /home/deploy/phaemos/infra/scripts/backup.sh
```

The private key is never on the droplet. A thief with the droplet, a snapshot or a copy of `~/backups` has files they cannot read. The price is that **if you lose the private key, every backup is lost with it**: keep two copies in two places.

A failed backup under cron writes to a log nobody reads. `backup.sh` leaves a file named `BACKUP_FAILED` in the backup folder on any failure (and removes it on the next success) and it refuses to run when the database looks empty (no `users` table) and refuses a new file less than half the size of the newest one kept, so a broken day cannot push the good backups out. It also accepts `BACKUP_PING_URL` in `backend/.env`: a monitor that expects that address to be called every day (a dead-man's-switch service) and alerts you when it is not. That is the only thing that notices a backup that stopped running at all. The address is a secret in the sense that anyone who has it can fake a success.

An older version of this script wrote plain `.sql.gz` files. `backup.sh` names any it finds in a warning on every run. They hold every email, password hash, two-step secret and device key in clear. Delete them once an encrypted backup exists.

### Copy the backups off the server (do not skip this)

A backup on the droplet's own disk goes with the droplet. If the droplet is lost, wiped or taken over, so are the backups and a thief who owns the droplet can delete them. **Set up an off-server copy before you rely on the backups.** The script supports one through `rclone`:

1. Create a bucket in any object storage that rclone supports. Turn on a retention (object lock) period of 30 days, so a copy cannot be deleted or overwritten early, even with the right credential. Add a lifecycle rule that deletes objects 30 days after they were written. Together they mean an off-server copy is kept for 30 days and then goes, which is the period the privacy notice gives. The credential cannot delete, so this bucket rule is the only thing that removes old copies: set both before the first copy is made.
2. Create a credential for the bucket that can **only write new objects**: no list, no read, no delete, no overwrite. The droplet then holds a key that a thief cannot use to harm or read the copies. (The files are encrypted anyway.)
3. On the droplet install `rclone` (`apt-get install rclone` from the root session) and run `rclone config` as the deploy user to add the remote. The credential is stored in rclone's config file, which rclone makes private to that user. It is never in this repository and never in `backend/.env`.
4. Add `BACKUP_RCLONE_REMOTE=remote-name:bucket-name` to `backend/.env`.

`backup.sh` then copies each new file there (it uses `rclone copyto --no-check-dest`, which needs no listing right) and exits non-zero with `OFFSITE COPY FAILED` if the copy fails. With no remote set it prints a warning on every run saying the backup is on the server only.

### What the dump does not hold

The dump is the database only. Copy these separately and keep them somewhere other than the droplet:

- `backend/.env`: `scp deploy@YOUR_DROPLET_IP:/home/deploy/phaemos/backend/.env .` and store it in a password manager or encrypted storage.
- The firmware volume: `docker run --rm -v phaemos-prod_firmware_data:/data -v "$PWD":/out alpine tar czf /out/firmware.tgz -C /data .` Encrypt the file with `age` as well before it leaves your computer.
- The model volume is **not worth backing up**. The model file is a Python pickle and loading a pickle runs whatever code it contains. A model file that was tampered with or that came from a backup you cannot vouch for, runs that code inside the API with the API's keys. If the volume is lost, **retrain** with `POST /api/v1/ml/retrain` and do not restore the file. If you do restore one, do it only from a copy you made yourself and encrypted and say so in your notes.

> [!NOTE]
> Retrain once after the release that stopped filling missing readings with zero. A model file saved before it still scores the readings it can and a reading that nothing in it can score passes through as 0.0, so anomaly detection for that node stays off until an admin runs `POST /api/v1/ml/retrain`. The API logs a warning when it loads such a file. Retraining needs at least 50 complete readings and refuses with a clear message when there are fewer, keeping the old model.

- Redis holds only repeat windows and daily caps. It needs no backup.

### Restore

`infra/scripts/restore.sh` does the same thing on the live droplet and on a new one. **Run it inside `tmux`** (or `screen`): a dropped terminal ends the script part-way. The script handles that safely (see below) but then the restore has to be started again and a restore in `tmux` simply carries on.

On a new droplet do Sections 2 to 6 first, so the stack exists, but with one change: **put the saved `backend/.env` back first**, from the safe copy you made in Section 5 and do not generate a new one. A new `SECRET_KEY` leaves every machine's key and every two-step secret unreadable, because both are derived from it. The `.env` file is as much a part of the backup as the database. (If the old key is lost it cannot be recovered: each person sets up two-step again and each machine is given a new key.)

Copy the backup file over. Copy your private key file over **for the restore only**, into memory (`/dev/shm`) and delete it straight after. Memory can be swapped to the droplet's disk under pressure, so treat the key as exposed once a restore has been done on the server: make a new key pair afterwards and put the new public key in `BACKUP_AGE_RECIPIENT`. Then:

```bash
scp phaemos-backup.key deploy@YOUR_DROPLET_IP:/dev/shm/restore.key
ssh deploy@YOUR_DROPLET_IP
chmod 600 /dev/shm/restore.key
bash /home/deploy/phaemos/infra/scripts/restore.sh ~/backups/phaemos-DATE.sql.gz.age /dev/shm/restore.key
shred -u /dev/shm/restore.key
```

It decrypts the file and checks it ends in a complete dump before it touches anything (a wrong key, a damaged file and a file cut short are all refused, with nothing changed). It names the database and the file and asks you to type the database name before it destroys anything. It then stops the API and runs the whole load in **one transaction**: `BEGIN`, empty the schema, remove any large object (one left over would make the dump fail on a duplicate key), load the dump and `COMMIT` only after the whole dump has been read and its closing line seen. A stream that ends early (a cut file, a dropped connection, a killed client) ends in `ROLLBACK` and a non-zero exit and the old data stays. A hang-up or a kill ends any leftover session, rolls it back and starts the API again. After a successful load it gives the API's database login its rights back and starts the API. It never restores a model file and says so. Run `deploy.sh` afterwards to apply any migration newer than the backup.

**What a backup does not prove.** A backup is encrypted to a public key and anyone who holds the public key (it is in `backend/.env` on the droplet) can make a file that `restore.sh` will accept and load as the database owner. Encryption says nobody else can read your backups. It does not say who wrote a file. So restore only from files you took from your own off-server store and let that store's object lock (Section 14, above) be the thing that says a copy is the one the server wrote and nobody has since replaced. We do not sign backups.

### Test a restore every month

A backup that has never been restored is a hope. Once a month, on your own computer or a spare droplet and **not on production**, bring up a copy of the stack, fetch the newest backup (from the off-server copy, which tests that too), restore it with your private key and check that you can sign in, that the machines and their latest readings are there and that `/status` is `operational`. Write the date and the result in the checklist's monthly line. Take the copy down afterwards and delete the decrypted data.

---

## Section 15: Updating after a PR merges to main

### Backend (droplet)

```bash
cd /home/deploy/phaemos
git fetch --tags
git checkout vX.Y.Z
bash infra/scripts/deploy.sh
```

Deploy a signed release tag only (Section 6). `deploy.sh` refuses anything else. It makes sure the API's database login exists, runs the schema job and applies any new file in `backend/migrations/` first, then rebuilds the image, restarts what changed and checks `/status`, the environment and the running Nginx configuration. Take a backup first when the release carries a migration. A kernel update is applied by unattended upgrades but only takes effect after a reboot: when `/var/run/reboot-required` exists, run `sudo reboot` at a quiet time. The stack comes back on its own because every container restarts unless stopped.

### Run the API as an unprivileged user (once, on an existing droplet)

The API image now runs as the user `phaemos` (uid 10001) and not as root and the production image installs only what production needs (no test or plotting packages). A new deployment needs nothing more: the image creates the two folders the API writes to with the right owner and a new named volume copies that owner. An **existing** deployment has volumes created by the old root-run container, which the new user cannot write to. Until they are handed over, a firmware upload and a model retrain answer an error (the API still starts and serves readings). Do this once, before the first deploy of the new image, with the old container still in place:

```bash
cd /home/deploy/phaemos
pc run --rm --no-deps --user root --cap-add CHOWN backend chown -R 10001:10001 /var/lib/phaemos/firmware /var/lib/phaemos/model
```

The `--cap-add CHOWN` is needed: every service in the compose file drops all capabilities and root without the `CHOWN` capability cannot change an owner (`chown ... Operation not permitted`). It adds that one capability to this one throwaway container and nothing else.

Expect no output. Check it took effect after the deploy with `pc exec backend id` (expect `uid=10001(phaemos)`) and `pc exec backend sh -c 'touch /var/lib/phaemos/firmware/.w && rm /var/lib/phaemos/firmware/.w && touch /var/lib/phaemos/model/.w && rm /var/lib/phaemos/model/.w && echo writable'`. The development compose file keeps running as root, because the source is bind mounted and written to by your own user. It builds with `requirements-dev.txt`, which adds the test packages that `make test` needs.

If the Nginx file changed, copy it again as in Section 9 and run `nginx -t && systemctl reload nginx`, from the Droplet Console, because the deploy user cannot copy a file into `/etc/nginx` (Section 3). Nothing of Certbot's is in the file, so copying it over loses nothing.

### Move an existing droplet to the limited database login and the hardened containers (once)

A droplet that was set up before these changes runs the API as the database owner and its containers have no hardening options. Do this once, in this order and keep a backup first:

1. Run `bash infra/scripts/backup.sh` after you have put `BACKUP_AGE_RECIPIENT` in `backend/.env` (it refuses without it) and keep that file. Delete the old unencrypted backups once you have an encrypted one.
2. Add `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD` and `REDIS_PASSWORD` to `backend/.env` (Section 5).
3. Check out the release tag and run `bash infra/scripts/deploy.sh`. The database container is recreated with the new options and its data volume is untouched. `deploy.sh` makes the role, grants it the tables that already exist and sets default rights for the tables made later. Running it again changes nothing.
4. Confirm that `rolsuper` is `f` for the API's login: `pc exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select rolname, rolsuper from pg_roles where rolname = '"'"'$POSTGRES_APP_USER'"'"'"'` (the `sh -c` makes the container's own variables apply, not your shell's).
5. Rotate `SECRET_KEY` (see "Rotating `SECRET_KEY`" below, which keeps the stored secrets readable) and the database owner's password if the API has been running as the owner with them in its environment for long. The API had both.
6. The compose file now has two networks, `data` (internal, no route out) and `edge`. An old droplet still has the single `internal` network with the same address range, so run `pc down` once (it keeps the volumes) before the first deploy of this version or the new `edge` network will clash with it.

### Rotating `SECRET_KEY`

Everything the API signs or encrypts is keyed from `SECRET_KEY`, with a separate derived key for each purpose. To rotate it without signing everyone out at once and without losing the two-step secrets or the machine keys:

1. Copy the current `SECRET_KEY` value into a new line `SECRET_KEY_PREVIOUS=` in `backend/.env` (it is shown, commented, in `backend/.env.example`). The API accepts that old key to **verify** tokens and **decrypt** stored values and never to make new ones.
2. Empty the `SECRET_KEY=` line and run `bash infra/scripts/set-secret.sh SECRET_KEY 32`.
3. Deploy. People stay signed in and the stored secrets are re-read with the old key and written with the new one as they are used.
4. Remove the `SECRET_KEY_PREVIOUS` line once the old tokens have expired (30 days) and every machine has posted since the deploy. Then deploy again.

If `SECRET_KEY` is simply replaced with no previous key, every machine key and every two-step secret stops working. The same is true of a restore on a new droplet with a new `SECRET_KEY`, which is why the saved `backend/.env` goes back first.

### Frontend (Vercel)

Vercel deploys automatically on every push to `main`. No manual step needed. Monitor the deploy in the Vercel dashboard.

### Docs (Vercel)

The docs Vercel project also deploys automatically on every push to `main`. No manual step needed.

---

## Section 16: Rollback

### Backend

Migrations only add columns, so older code runs on a newer schema. Go back by code:

```bash
cd /home/deploy/phaemos
git tag --list 'v*' --sort=-creatordate | head   # find the last known good tag
git checkout <tag>
bash infra/scripts/deploy.sh
```

Use a signed tag as the target (`git checkout vX.Y.Z`): `deploy.sh` refuses an unsigned commit. Return to the branch afterwards with `git checkout main`. If the data itself is damaged, restore the latest backup as in Section 14 with `restore.sh`.

### Frontend / docs

Use the Vercel dashboard -> **Deployments** -> select the previous deployment -> **Promote to Production**.

---

## Section 17: Reading logs

```bash
pc ps                          # state and health of the three containers
pc logs --tail 100 backend     # the API
pc logs -f backend             # follow the API live
pc logs --tail 100 db redis
tail -n 100 /var/log/nginx/error.log
tail -n 100 /var/log/nginx/access.log
sudo fail2ban-client status sshd
```

The API logs warnings and above in production. A failed email or text and a reached daily cap each leave a warning. Container logs rotate at 10 MB with 3 copies each.

Once the stack is live, walk [the deployment checklist](deployment-checklist.md) against production.
