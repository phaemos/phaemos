#!/usr/bin/env bash
# first-run hardening for a fresh Ubuntu 24.04 droplet. Run it as root once. It is safe to
# run again: every step checks what is already in place.
#
#   sudo DEPLOY_SUDO=full DEPLOY_USER=deploy DEPLOY_PUBKEY_FILE=/root/.ssh/authorized_keys bash harden.sh
#
# DEPLOY_USER is the non-root account to create (default deploy). The account gets the
# public keys in DEPLOY_PUBKEY_FILE (default: root's authorized_keys from droplet creation).
#
# DEPLOY_SUDO decides what the deploy user may do as root:
#   limited  (the default) a short list of exact commands: look at Nginx and test and reload
#            it, read the firewall and fail2ban, check certificates and reboot. Nothing else.
#            deploy.sh, backup.sh and restore.sh need no sudo at all: they use the docker
#            group, which is why the user is root-equivalent anyway (see the deployment guide,
#            "What can be narrowed"). The list stops the easy mistakes and the easy path and
#            it does not make the account safe against someone who holds its key.
#   full     the old passwordless rule for every command. Use it for the first run, so that
#            install.sh and the one-off root steps in the guide work. Then run this script
#            again without it as the last step of the first set-up.
# SSH_ALLOW_USERS is the list of accounts sshd lets in (default: the deploy user only).
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_SUDO="${DEPLOY_SUDO:-limited}"
SSH_ALLOW_USERS="${SSH_ALLOW_USERS:-${DEPLOY_USER}}"
DEPLOY_PUBKEY_FILE="${DEPLOY_PUBKEY_FILE:-/root/.ssh/authorized_keys}"
# 2 GB of swap for a 1 GB machine: enough to ride out a Docker build or a memory spike
SWAP_FILE=/swapfile
SWAP_SIZE=2G

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo bash harden.sh)" >&2
    exit 1
fi

case "${DEPLOY_SUDO}" in
    limited | full) ;;
    *)
        echo "DEPLOY_SUDO must be limited or full" >&2
        exit 1
        ;;
esac
# a bad name here would be written into sshd's config, so only plain account names pass
for account in ${SSH_ALLOW_USERS}; do
    if ! [[ "${account}" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
        echo "SSH_ALLOW_USERS holds a name that is not a plain account name: ${account}" >&2
        exit 1
    fi
done
# the deploy user must be on the list. A list without it would let sshd in nobody who can
# deploy and, with root login off, nobody who can administer
deploy_listed=""
for account in ${SSH_ALLOW_USERS}; do
    [ "${account}" = "${DEPLOY_USER}" ] && deploy_listed=1
done
if [ -z "${deploy_listed}" ]; then
    echo "SSH_ALLOW_USERS must include the deploy user (${DEPLOY_USER}): otherwise nobody who can deploy could sign in" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
# a fresh droplet often runs its own first-boot upgrade: wait for the apt lock instead of failing
APT=(apt-get -o DPkg::Lock::Timeout=300 -y)

echo "== packages"
"${APT[@]}" update
"${APT[@]}" upgrade
"${APT[@]}" install ufw fail2ban unattended-upgrades

echo "== deploy user: ${DEPLOY_USER}"
if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
    # no password is set: the account logs in with keys and uses sudo through the
    # passwordless rule below
    adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
# the adm group can read the Nginx logs, so the guide's log commands need no sudo
usermod -aG adm "${DEPLOY_USER}"
# a fixed file name with no dot: sudo skips names containing a dot, so a user name such as
# "j.smith" would otherwise leave this rule silently ignored
SUDOERS_FILE=/etc/sudoers.d/90-phaemos-deploy
SUDOERS_TMP="$(mktemp)"
# the narrow rule takes the account out of the sudo group. Without the docker group it would
# then be able to do neither and the deployment would be stuck, so the narrow rule is refused
# until install.sh has put the account in the docker group
deploy_groups="$(id -nG "${DEPLOY_USER}")"
if [ "${DEPLOY_SUDO}" = "limited" ] && ! grep -qw docker <<< "${deploy_groups}"; then
    rm -f "${SUDOERS_TMP}"
    echo "${DEPLOY_USER} is not in the docker group, so the narrow sudo rule would leave it unable to deploy." >&2
    echo "run install.sh first (as root, with DEPLOY_USER=${DEPLOY_USER}) or use DEPLOY_SUDO=full for now" >&2
    exit 1
fi
if [ "${DEPLOY_SUDO}" = "full" ]; then
    usermod -aG sudo "${DEPLOY_USER}"
    echo "${DEPLOY_USER} ALL=(ALL) NOPASSWD:ALL" > "${SUDOERS_TMP}"
else
    # the sudo group would give the account every command, so it leaves it. The commands
    # below are written out whole: a rule with a wildcard in an argument lets the argument
    # name any file or option, which is the same as no rule.
    gpasswd -d "${DEPLOY_USER}" sudo > /dev/null 2>&1 || true
    cat > "${SUDOERS_TMP}" <<SUDO
Cmnd_Alias PHAEMOS_NGINX = /usr/sbin/nginx -t, /usr/sbin/nginx -T, /usr/bin/systemctl reload nginx, /usr/bin/systemctl status nginx
Cmnd_Alias PHAEMOS_STATUS = /usr/sbin/ufw status, /usr/bin/fail2ban-client status sshd, /usr/bin/certbot certificates, /usr/bin/certbot renew --dry-run
Cmnd_Alias PHAEMOS_REBOOT = /usr/bin/systemctl reboot
${DEPLOY_USER} ALL=(root) NOPASSWD: PHAEMOS_NGINX, PHAEMOS_STATUS, PHAEMOS_REBOOT
SUDO
fi
# the rule is checked before it goes live, so a mistake cannot leave sudo broken
if ! visudo -cf "${SUDOERS_TMP}" >/dev/null; then
    rm -f "${SUDOERS_TMP}"
    echo "the sudoers rule is invalid and was not installed" >&2
    exit 1
fi
install -m 440 -o root -g root "${SUDOERS_TMP}" "${SUDOERS_FILE}"
rm -f "${SUDOERS_TMP}"

home_dir="$(getent passwd "${DEPLOY_USER}" | cut -d: -f6)"
if [ ! -s "${DEPLOY_PUBKEY_FILE}" ]; then
    echo "no public keys found in ${DEPLOY_PUBKEY_FILE}: refusing to turn passwords off" >&2
    exit 1
fi
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${home_dir}/.ssh"
touch "${home_dir}/.ssh/authorized_keys"
# add only the keys that are not there yet
# "|| [ -n "$key" ]" keeps a last line that has no newline at the end
while IFS= read -r key || [ -n "${key}" ]; do
    [ -n "${key}" ] || continue
    grep -qxF "${key}" "${home_dir}/.ssh/authorized_keys" || echo "${key}" >> "${home_dir}/.ssh/authorized_keys"
done < "${DEPLOY_PUBKEY_FILE}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${home_dir}/.ssh/authorized_keys"
chmod 600 "${home_dir}/.ssh/authorized_keys"

echo "== ssh: keys only, no root login, named users only"
# never switch passwords off or restrict logins unless EVERY listed account exists and holds
# at least one key that ssh-keygen accepts. Otherwise this step would lock that account out.
for account in ${SSH_ALLOW_USERS}; do
    if ! id "${account}" > /dev/null 2>&1; then
        echo "${account} is in SSH_ALLOW_USERS and does not exist: leaving sshd unchanged" >&2
        exit 1
    fi
    account_home="$(getent passwd "${account}" | cut -d: -f6)"
    valid_keys=0
    if [ -f "${account_home}/.ssh/authorized_keys" ]; then
        while IFS= read -r key || [ -n "${key}" ]; do
            [ -n "${key}" ] || continue
            if printf '%s\n' "${key}" | ssh-keygen -l -f /dev/stdin >/dev/null 2>&1; then
                valid_keys=$((valid_keys + 1))
            fi
        done < "${account_home}/.ssh/authorized_keys"
    fi
    if [ "${valid_keys}" -lt 1 ]; then
        echo "${account_home}/.ssh/authorized_keys holds no valid key for ${account}: leaving sshd unchanged" >&2
        exit 1
    fi
done
# a drop-in file sorts before cloud-init's own and wins, so the main config is untouched
SSHD_DROPIN=/etc/ssh/sshd_config.d/00-phaemos-hardening.conf
cat > "${SSHD_DROPIN}" <<'SSHD'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
SSHD
# only the named accounts may sign in, whatever other users the system gets later. The file
# is written in two steps because the list comes from a variable
printf 'AllowUsers %s\n' "${SSH_ALLOW_USERS}" >> "${SSHD_DROPIN}"
# a configuration sshd rejects is removed again so the running service is never left with it
if ! sshd -t; then
    rm -f "${SSHD_DROPIN}"
    echo "sshd rejected the hardening file and it was removed" >&2
    exit 1
fi
# nothing is reloaded until the operator has a way back in. A reload does not end the session
# that is open now, so the session running this script is the way back: keep it open
echo
echo "Before sshd is reloaded: open a SECOND terminal and sign in as ${DEPLOY_USER} (ssh ${DEPLOY_USER}@<droplet address>)."
echo "That proves the key works. Keep THIS session open until the last step below has passed."
if [ "${HARDEN_CONFIRMED:-}" = "yes" ]; then
    echo "HARDEN_CONFIRMED=yes: continuing without asking."
else
    if [ ! -t 0 ]; then
        rm -f "${SSHD_DROPIN}"
        echo "there is no terminal to ask on: set HARDEN_CONFIRMED=yes once you have a second session open. The sshd file was removed." >&2
        exit 1
    fi
    printf "Type yes once the second terminal is signed in: "
    answer=""
    read -r answer || answer=""
    if [ "${answer}" != "yes" ]; then
        rm -f "${SSHD_DROPIN}"
        echo "not confirmed: the sshd file was removed and sshd is unchanged" >&2
        exit 1
    fi
fi
# on Ubuntu 24.04 sshd may be socket activated and not running. A new connection then starts
# it and it reads the file at start, so there is nothing to reload
if systemctl is-active --quiet ssh; then
    systemctl reload ssh
else
    echo "the ssh service is not running (socket activation): the next connection reads the new file"
fi
echo "sshd now applies the new rules. Sign in once more from a THIRD terminal to prove it. If that fails, undo from THIS session:"
echo "  rm ${SSHD_DROPIN} && systemctl reload ssh"

echo "== firewall: 22, 80 and 443 only"
# this is the host firewall. Also add a DigitalOcean cloud firewall that allows port 22 from
# your own addresses only (deployment guide, Section 3): it sits outside the droplet, so a
# mistake here or a break-in cannot switch it off
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "== fail2ban"
cat > /etc/fail2ban/jail.d/phaemos.local <<'JAIL'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
JAIL
systemctl enable --now fail2ban
systemctl restart fail2ban

echo "== unattended security upgrades"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT
systemctl enable --now unattended-upgrades

echo "== swap: ${SWAP_SIZE}"
swap_active="$(swapon --show=NAME --noheadings)"
if ! grep -qx "${SWAP_FILE}" <<< "${swap_active}"; then
    if [ ! -f "${SWAP_FILE}" ]; then
        # built under another name and moved into place, so an interruption between the steps
        # cannot leave a file at the real name that is not a swap area (swapon would then fail
        # on every rerun)
        rm -f "${SWAP_FILE}.new"
        fallocate -l "${SWAP_SIZE}" "${SWAP_FILE}.new"
        chmod 600 "${SWAP_FILE}.new"
        mkswap "${SWAP_FILE}.new" >/dev/null
        mv "${SWAP_FILE}.new" "${SWAP_FILE}"
    fi
    swapon "${SWAP_FILE}"
fi
grep -q "^${SWAP_FILE} " /etc/fstab || echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
# prefer RAM and use swap only under pressure
echo "vm.swappiness=10" > /etc/sysctl.d/99-phaemos-swap.conf
sysctl -p /etc/sysctl.d/99-phaemos-swap.conf >/dev/null

echo
echo "done. Do not close this session until a fresh terminal can sign in as ${DEPLOY_USER}:"
echo "  ssh ${DEPLOY_USER}@<droplet address>"
