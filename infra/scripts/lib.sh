#!/usr/bin/env bash
# shared by deploy.sh, backup.sh, restore.sh and db-role.sh. It is sourced and never run on
# its own. It sets the paths and the compose command and defines the two helpers that every
# script needs: reading a value from backend/.env and running psql as the database owner.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${REPO_DIR}/backend/.env"
COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${REPO_DIR}/infra/docker-compose.prod.yml")

# succeeds when the group or anyone else has any access to the file. It reads the mode string
# from ls so it behaves the same on Linux and macOS: the find option for this differs there.
# shellcheck disable=SC2012
others_can_access() {
    [ "$(ls -ld -- "$1" | cut -c5-10)" != "------" ]
}

# compose lets a variable in the shell beat the same name in backend/.env, so a stray
# `export SECRET_KEY=...` in an operator's profile would quietly replace the file's value in
# the API. The scripts read the file and compose reads the shell: they would disagree. Refuse
# rather than guess which one the operator meant.
refuse_shell_overrides() {
    local name
    for name in SECRET_KEY POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_APP_USER POSTGRES_APP_PASSWORD REDIS_PASSWORD; do
        if [ -n "${!name+set}" ]; then
            echo "${name} is set in the shell and would override backend/.env: run unset ${name} and try again" >&2
            return 1
        fi
    done
}

# reads one value from backend/.env without printing anything else. A quoted value loses its
# quotes the way Compose reads it. A name that is missing gives an empty string.
env_value() {
    sed -n "s/^$1=//p" "${ENV_FILE}" | tail -n 1 | sed -e "s/^'\(.*\)'\$/\1/" -e 's/^"\(.*\)"$/\1/'
}

# psql is in the db container and not the API image. It signs in as the database owner with
# the login from the container's own environment, so nothing secret is on a command line.
# PGOPTIONS hides the "already exists, skipping" notices that the IF NOT EXISTS guards raise.
# stdin is passed through, so a caller can pipe a SQL file in.
# shellcheck disable=SC2119,SC2120
db_psql() {
    # shellcheck disable=SC2016
    "${COMPOSE[@]}" exec -T db sh -c 'PGOPTIONS="-c client_min_messages=warning" psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh "$@"
}
