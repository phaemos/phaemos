#!/usr/bin/env bash
# writes a new random value into one NAME= line of backend/.env without the value appearing on
# any command line or in the shell's history.
#
#   bash infra/scripts/set-secret.sh SECRET_KEY 32
#   bash infra/scripts/set-secret.sh POSTGRES_APP_PASSWORD 24
#
# the second argument is the number of random bytes, written as hex (so 32 gives 64 characters);
# a command like `sed -i "s|^X=.*|X=$(openssl rand -hex 24)|"` puts the secret in the argument
# list of a process, where any user on the machine can read it for as long as it runs and
# in the shell's history. Here the value travels in the environment of one awk process and
# nowhere else. It refuses to change a line that is already filled in, so a second run cannot
# replace a database password that the database already knows. Delete the value by hand first
# if a replacement is really meant (and read "Rotating secrets" in docs/deployment.md).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${REPO_DIR}/backend/.env"

if [ "$#" -ne 2 ] || ! [[ "$1" =~ ^[A-Z][A-Z0-9_]*$ ]] || ! [[ "$2" =~ ^[0-9]+$ ]]; then
    echo "usage: bash infra/scripts/set-secret.sh NAME BYTES" >&2
    exit 1
fi
name="$1"
[ -f "${ENV_FILE}" ] || { echo "missing ${ENV_FILE}" >&2; exit 1; }
grep -q "^${name}=" "${ENV_FILE}" || { echo "${ENV_FILE} has no ${name}= line" >&2; exit 1; }
current="$(sed -n "s/^${name}=//p" "${ENV_FILE}" | tail -n 1)"
if [ -n "${current}" ]; then
    echo "${name} already has a value: not changed" >&2
    exit 1
fi

umask 077
tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
trap 'rm -f "${tmp}"' EXIT
NEW_SECRET_VALUE="$(openssl rand -hex "$2")" awk -v key="${name}" '
    BEGIN { FS = OFS = "=" }
    $1 == key { print key "=" ENVIRON["NEW_SECRET_VALUE"]; next }
    { print }' "${ENV_FILE}" > "${tmp}"
mv "${tmp}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"
trap - EXIT
echo "${name} written"
