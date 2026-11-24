#!/usr/bin/env bash
# installs Docker Engine with the compose plugin from Docker's own apt repository, then
# Nginx, Certbot and age. Run it as root, from the same first session that ran harden.sh with
# DEPLOY_SUDO=full (the default sudo rule for the deploy user does not allow it). It is safe
# to run again: apt skips what is installed and the repository files are rewritten identically.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-deploy}}"
# run through `sudo bash` from a root shell, SUDO_USER is root and root must never be the one
# that gets the docker group. The deploy account is the default in that case
if [ "${DEPLOY_USER}" = "root" ]; then
    DEPLOY_USER=deploy
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo bash install.sh)" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
# wait for the apt lock instead of failing while another apt run holds it
APT=(apt-get -o DPkg::Lock::Timeout=300 -y)

echo "== prerequisites"
"${APT[@]}" update
"${APT[@]}" install ca-certificates curl gnupg

echo "== Docker apt repository"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
"${APT[@]}" update

echo "== Docker Engine and compose plugin"
"${APT[@]}" install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
# the docker group is root-equivalent, so it goes to the deploy user only and never to root
if [ "${DEPLOY_USER}" != "root" ] && id "${DEPLOY_USER}" >/dev/null 2>&1; then
    usermod -aG docker "${DEPLOY_USER}"
fi

echo "== Nginx and Certbot"
# the Certbot Nginx plugin is not needed: the site file carries its own TLS settings and
# Certbot only issues and renews the certificate (docs/deployment.md, Section 9)
"${APT[@]}" install nginx certbot
systemctl enable --now nginx
# the stock worker_connections is 768 and each proxied request holds two of them (the client
# and the API), so the site's connection limits could use them all. A larger pool is cheap
if grep -qE '^[[:space:]]*worker_connections[[:space:]]+768;' /etc/nginx/nginx.conf; then
    sed -i -E 's/^([[:space:]]*)worker_connections[[:space:]]+768;/\1worker_connections 4096;/' /etc/nginx/nginx.conf
    nginx -t
    systemctl reload nginx
fi
# a renewed certificate is only used once Nginx has reloaded
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/phaemos-reload-nginx.sh <<'HOOK'
#!/bin/sh
systemctl reload nginx
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/phaemos-reload-nginx.sh

# Nginx makes a new TLS session ticket key at every reload. A weekly reload keeps the life of
# one key short (see ssl_session_tickets in the site file)
cat > /etc/cron.weekly/phaemos-nginx-reload <<'CRON'
#!/bin/sh
systemctl reload nginx
CRON
chmod 755 /etc/cron.weekly/phaemos-nginx-reload

# the web server logs are kept for 14 days and no longer, as the privacy notice says. The rule
# replaces the package's own logrotate file, which keeps weeks of logs
install -m 644 "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/infra/logrotate/phaemos-nginx" /etc/logrotate.d/nginx

echo "== age (backup encryption)"
# backup.sh encrypts every backup with it. Only the public key is ever needed on this machine
"${APT[@]}" install age

docker --version
docker compose version
nginx -v
certbot --version
age --version

echo
echo "done. Log out and back in so the docker group applies to ${DEPLOY_USER}."
if [ -f /var/run/reboot-required ]; then
    echo "a kernel update is waiting: run sudo reboot, then deploy.sh again if the stack does not come back on its own."
fi
