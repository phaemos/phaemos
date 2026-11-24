#!/usr/bin/env bash
# writes an encrypted, compressed pg_dump of the production database and keeps the newest
# seven. It exits non-zero on any failure so a log check shows it. Run it as the deploy user.
#
# the dump is encrypted with age to a PUBLIC key in BACKUP_AGE_RECIPIENT (backend/.env or the
# environment). The matching private key is never on the server, so a stolen backup file,
# snapshot or deploy account cannot be read. The script refuses to write an unencrypted backup:
# with no recipient set it stops. There is no override.
#
# cron line (daily at 03:15). The script writes its own log, so the folder never has to
# exist before cron starts:
#   15 3 * * * bash /home/deploy/phaemos/infra/scripts/backup.sh
#
# BACKUP_DIR defaults to ~/backups. The dump holds the database only. It does not hold
# backend/.env, the firmware volume or the model volume. Copy those too (see the
# deployment guide).
#
# a backup on the same disk does not survive losing the droplet. Set BACKUP_RCLONE_REMOTE to
# a remote and path configured in rclone (for example offsite:phaemos-backups) and every
# backup is also copied there. Use a bucket and a credential that can ONLY WRITE new objects,
# with a retention lock on the bucket, so that a thief with the server cannot delete or
# overwrite the copies. The credential lives in rclone's own config file (mode 600), never
# in this repository and never in backend/.env. The bucket keeps each copy for 30 days and then
# expires it (retention lock and lifecycle rule, deployment guide Section 14), because that
# credential cannot delete.
set -euo pipefail

# files and folders created here are private to the deploy user
umask 077

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/backups}"
KEEP=7

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

# started by cron there is no terminal, so everything goes to a log in the backup folder
if [ ! -t 1 ]; then
    exec >> "${BACKUP_DIR}/backup.log" 2>&1
    echo "--- $(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

refuse_shell_overrides
if [ ! -f "${ENV_FILE}" ]; then
    echo "missing ${ENV_FILE}" >&2
    exit 1
fi

# the public key. It is not secret, so it may sit in backend/.env beside the other settings
recipient="${BACKUP_AGE_RECIPIENT:-$(env_value BACKUP_AGE_RECIPIENT)}"
if [ -z "${recipient}" ]; then
    echo "BACKUP_AGE_RECIPIENT is not set: refusing to write an unencrypted backup." >&2
    echo "make a key pair on your own computer with age-keygen and put the PUBLIC key (age1...) in backend/.env" >&2
    exit 1
fi
if ! [[ "${recipient}" =~ ^age1[a-z0-9]{50,}$ ]]; then
    echo "BACKUP_AGE_RECIPIENT is not an age public key (it starts age1 and holds no spaces)" >&2
    exit 1
fi
if ! command -v age > /dev/null; then
    echo "age is not installed: sudo apt-get install age (install.sh does this)" >&2
    exit 1
fi

# a failure under cron goes to a log nobody reads. Leave a marker file that a monitor or a
# person can see and (optionally) a dead-man's-switch address that is told about every
# success, so a missed or failed run raises the alarm from outside the server
failed_marker="${BACKUP_DIR}/BACKUP_FAILED"
on_exit() {
    local status=$?
    rm -f "${partial:-}"
    if [ "${status}" -ne 0 ]; then
        date -u +"%Y-%m-%dT%H:%M:%SZ backup failed" > "${failed_marker}"
    fi
}

# an empty database must never replace a good backup. A dump of a database with no tables is
# small, valid and encrypts without complaint and seven daily runs later it would be all
# that was left
users_present="$(db_psql -tA -c "SELECT to_regclass('public.users') IS NOT NULL" | tr -d '[:space:]')"
if [ "${users_present}" != "t" ]; then
    echo "refusing to back up: public.users is missing, so the database looks empty. Nothing was written and nothing was rotated." >&2
    date -u +"%Y-%m-%dT%H:%M:%SZ backup refused: no users table" > "${failed_marker}"
    exit 1
fi

stamp="$(date -u +%Y-%m-%d_%H%M%S)"
target="${BACKUP_DIR}/phaemos-${stamp}.sql.gz.age"
partial="${target}.partial"

# whatever goes wrong, a half-written file is never left behind to be mistaken for a backup
trap on_exit EXIT

# the login comes from the container's own environment, so nothing secret is on the
# command line or in this script. pipefail makes a failed pg_dump, gzip or age fail the
# whole pipe. The dump is encrypted as it streams, so no plain copy ever reaches the disk.
# shellcheck disable=SC2016
if ! "${COMPOSE[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' | gzip -9 | age -r "${recipient}" > "${partial}"; then
    echo "backup failed" >&2
    exit 1
fi

# a file that does not start with the age header is not an encrypted backup. A file of only
# the header means pg_dump produced nothing
if [ "$(head -c 21 "${partial}")" != "age-encryption.org/v1" ]; then
    echo "backup is not an age file" >&2
    exit 1
fi
if [ "$(wc -c < "${partial}")" -lt 300 ]; then
    echo "backup is empty" >&2
    exit 1
fi

# a backup that is less than half the size of the newest one kept is a sign that something
# was lost (a table emptied, the wrong database). Refuse it before it can push a good file out
# shellcheck disable=SC2012
newest_kept="$(ls -1 "${BACKUP_DIR}"/phaemos-*.sql.gz.age 2> /dev/null | sort -r | head -n 1 || true)"
if [ -n "${newest_kept}" ]; then
    old_size="$(wc -c < "${newest_kept}")"
    new_size="$(wc -c < "${partial}")"
    if [ $((new_size * 2)) -lt "${old_size}" ]; then
        echo "refusing to keep this backup: it is ${new_size} bytes and the newest kept one is ${old_size}. Nothing was rotated. If the data really shrank, move the old files aside and run again." >&2
        exit 1
    fi
fi

mv "${partial}" "${target}"

# keep the newest seven including the one just written. The date in the name sorts the same
# as the age, but a file with a LATER date in its name (a clock that went backwards, a copied
# file) must never push the new one out, so the new file is left out of the list and always kept
others=()
for file in "${BACKUP_DIR}"/phaemos-*.sql.gz.age; do
    [ "${file}" = "${target}" ] || others+=("${file}")
done
if [ "${#others[@]}" -gt 0 ]; then
    printf '%s\n' "${others[@]}" | sort -r | tail -n +"${KEEP}" | while IFS= read -r old; do
        rm -f -- "${old}"
    done
fi
rm -f "${failed_marker}"

echo "backup written: ${target}"

# an older version of this script wrote plain .sql.gz files. They hold every email, password
# hash, two-step secret and device key in clear. Name them every run until they are gone.
plain="$(find "${BACKUP_DIR}" -maxdepth 1 -name 'phaemos-*.sql.gz' | wc -l | tr -d '[:space:]')"
if [ "${plain}" -gt 0 ]; then
    echo "WARNING: ${plain} unencrypted backup file(s) from an older version are still in ${BACKUP_DIR}. Copy the newest off the server encrypted if you need it, then delete them." >&2
fi

remote="${BACKUP_RCLONE_REMOTE:-$(env_value BACKUP_RCLONE_REMOTE)}"
if [ -n "${remote}" ]; then
    if ! command -v rclone > /dev/null; then
        echo "OFFSITE COPY FAILED: BACKUP_RCLONE_REMOTE is set and rclone is not installed" >&2
        exit 1
    fi
    # --no-check-dest lets a credential that can only write new objects do the copy. The
    # file is already encrypted, so the object store never sees the data
    if ! rclone copyto --no-check-dest "${target}" "${remote%/}/$(basename "${target}")"; then
        echo "OFFSITE COPY FAILED: the backup is on this server only" >&2
        exit 1
    fi
    echo "offsite copy written: ${remote%/}/$(basename "${target}")"
else
    echo "WARNING: no off-server copy. BACKUP_RCLONE_REMOTE is not set, so every backup is on this server's own disk and goes with it if the droplet is lost or taken. Set it up as in the deployment guide, Section 14." >&2
fi

# the dead-man's-switch: a monitor that expects this address to be called every day (and
# alerts when it is not) is the only thing that notices a backup that stopped running. The
# address is a secret in the sense that anyone who has it can fake a success, so it lives in
# backend/.env or the environment and nowhere else
ping_url="${BACKUP_PING_URL:-$(env_value BACKUP_PING_URL)}"
if [ -n "${ping_url}" ]; then
    curl -fsS --max-time 10 --retry 2 -o /dev/null "${ping_url}" || echo "WARNING: the monitor ping failed" >&2
fi
