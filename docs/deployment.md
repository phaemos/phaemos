# Deployment Guide

This guide covers the full production deployment of Phaemos:

- Backend (FastAPI + PostgreSQL + Redis) on a DigitalOcean VPS via Docker Compose
- Frontend (Next.js) on Vercel
- Documentation site (MkDocs) on Vercel
- Status page on Instatus

---

## Prerequisites

### DigitalOcean credit (GitHub Student Pack)

The GitHub Student Developer Pack provides $200 of DigitalOcean credit, covering approximately 33 months at the $6/month Basic Droplet price. Apply at [education.github.com/pack](https://education.github.com/pack) with a verified `.edu` email. Credit is applied automatically once approved.

---

## Section 1: DigitalOcean VPS setup

### Create the droplet

1. Sign in to [cloud.digitalocean.com](https://cloud.digitalocean.com).
2. Click **Create** -> **Droplets**.
3. Choose the following:
   - **Region:** closest to your expected users (e.g. London or Amsterdam for EU)
   - **Image:** Ubuntu 24.04 LTS
   - **Size:** Basic, 1 vCPU / 1 GB RAM / 25 GB SSD (~$6/month, covered by Student Pack)
   - **Authentication:** SSH key (paste your public key from `~/.ssh/id_rsa.pub`)
4. Click **Create Droplet**. Note the assigned IP address.

### First SSH login and hardening

```bash
ssh root@YOUR_DROPLET_IP
```

```bash
# Update packages
apt update && apt upgrade -y

# Create a non-root user
adduser phaemos
usermod -aG sudo phaemos

# Copy SSH key to the new user
rsync --archive --chown=phaemos:phaemos ~/.ssh /home/phaemos

# Disable root SSH login
sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload sshd
```

Reconnect as the `phaemos` user for all subsequent steps.

### Install Docker and Docker Compose

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker phaemos
# Log out and back in for the group change to take effect
```

### Install Nginx and Certbot

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

---

## Section 2: Deploy the backend

### Clone the repo

```bash
cd /home/phaemos
git clone https://github.com/zaccesss/phaemos.git
cd phaemos
```

### Create the backend environment file

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

At minimum, set:

```env
DATABASE_URL=postgresql://phaemos:CHANGE_ME@postgres:5432/phaemos
REDIS_URL=redis://redis:6379/0
SECRET_KEY=<generate with: openssl rand -hex 32>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
ALLOWED_ORIGINS=https://phaemos.com
ENVIRONMENT=production
```

All other variables (SMTP, Resend, Brevo, Turnstile, etc.) are optional - the app starts without them and the relevant features degrade gracefully.

### Start the stack

```bash
docker compose up -d
```

This starts four containers: `backend` (port 8000), `postgres` (port 5432), `redis` (port 6379), and `frontend` (port 3000). In production, only Nginx faces the internet - the container ports are not exposed publicly.

### Run database migrations

```bash
docker compose exec backend bash -c "
  for f in /app/migrations/*.sql; do psql \$DATABASE_URL < \$f; done
"
```

### Verify the backend is running

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","service":"PHAEMOS API","environment":"production",...}
```

---

## Section 3: Nginx reverse proxy and SSL

### Create the Nginx config for api.phaemos.com

```nginx
# /etc/nginx/sites-available/phaemos
server {
    listen 80;
    server_name api.phaemos.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/phaemos /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### Issue SSL certificate

```bash
sudo certbot --nginx -d api.phaemos.com
```

Certbot patches the Nginx config automatically to redirect HTTP to HTTPS and renew the certificate. Auto-renewal is enabled by default via a systemd timer - verify with `systemctl list-timers | grep certbot`.

---

## Section 4: DNS records

Add these records in your DNS provider (Cloudflare or DigitalOcean DNS):

| Name | Type | Value | Notes |
| --- | --- | --- | --- |
| `@` | A | `YOUR_DROPLET_IP` | Root domain - Vercel handles this via its own A records |
| `api` | A | `YOUR_DROPLET_IP` | Points to the VPS |
| `docs` | CNAME | `cname.vercel-dns.com` | Vercel docs project |
| `status` | CNAME | `<from Instatus dashboard>` | Instatus status page |

For `phaemos.com` itself (the Next.js app), follow the custom domain steps in Section 5 below - Vercel provides its own A and CNAME records.

---

## Section 5: Vercel - frontend (phaemos.com)

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub.
2. Click **Add New Project** and import the `zaccesss/phaemos` repo.
3. Set **Root Directory** to `frontend/`.
4. Set **Framework Preset** to **Next.js** (auto-detected).
5. Under **Environment Variables**, add every variable from `frontend/.env.example`. At minimum:
   - `NEXT_PUBLIC_API_URL` = `https://api.phaemos.com`
   - `NEXT_PUBLIC_TURNSTILE_SITE_KEY` = from Cloudflare Turnstile dashboard
   - `TURNSTILE_SECRET_KEY` = from Cloudflare Turnstile dashboard
   - `CONTACT_EMAIL_TO` = `contact@phaemos.com`
   - `NEXT_PUBLIC_GA_ID` = from Google Analytics (optional)
6. Click **Deploy**.
7. Under **Project Settings** -> **Domains**, add `phaemos.com` and `www.phaemos.com`. Follow Vercel's DNS instructions.

---

## Section 6: Vercel - documentation site (docs.phaemos.com)

1. In the same Vercel account, click **Add New Project** and import `zaccesss/phaemos` again (a second project).
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

## Section 7: Instatus - status page (status.phaemos.com)

1. Create a free account at [instatus.com](https://instatus.com).
2. Create a new status page named **Phaemos Status**.
3. Add two components:
   - **Platform** - monitors `https://phaemos.com` (HTTP, 60s interval)
   - **API** - monitors `https://api.phaemos.com/health`, keyword match `ok` (HTTP, 60s interval)
4. Under **Settings** -> **Domain**, add `status.phaemos.com` as the custom domain.
5. Instatus provides a CNAME target - add it to your DNS as a `status CNAME <instatus-target>` record.
6. Enable email and/or Slack notifications for incidents.

---

## Section 8: Updating after a PR merges to main

### Backend (VPS)

```bash
cd /home/phaemos/phaemos
git pull origin main
docker compose up -d --build backend
```

If the PR includes a new migration file, run it after pulling:

```bash
docker compose exec backend psql $DATABASE_URL < migrations/NNN_description.sql
```

### Frontend (Vercel)

Vercel deploys automatically on every push to `main`. No manual step needed. Monitor the deploy in the Vercel dashboard.

### Docs (Vercel)

The docs Vercel project also deploys automatically on every push to `main`. No manual step needed.

---

## Section 9: Rollback

### Backend

```bash
cd /home/phaemos/phaemos
git log --oneline -10   # find the last known good commit hash
git checkout <commit>
docker compose up -d --build backend
```

### Frontend / docs

Use the Vercel dashboard -> **Deployments** -> select the previous deployment -> **Promote to Production**.
