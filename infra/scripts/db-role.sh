#!/usr/bin/env bash
# creates or refreshes the limited database login that the API uses and checks it.
#
#   bash infra/scripts/db-role.sh           create or refresh the role and its rights
#   bash infra/scripts/db-role.sh --check   read-only: fail if the role or its rights are wrong
#
# deploy.sh runs both on every deploy and restore.sh runs the first after a restore, because
# a restore drops the schema and the rights with it. It is safe to run again: the SQL sets
# the same state every time. The role's name and password come from POSTGRES_APP_USER and
# POSTGRES_APP_PASSWORD in backend/.env. The password goes into the database container's
# environment and is read by psql itself, so it is on no command line.
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

mode="apply"
case "${1:-}" in
    "") ;;
    --check) mode="check" ;;
    *)
        echo "usage: bash infra/scripts/db-role.sh [--check]" >&2
        exit 1
        ;;
esac

refuse_shell_overrides
if [ ! -f "${ENV_FILE}" ]; then
    echo "missing ${ENV_FILE}" >&2
    exit 1
fi

app_user="$(env_value POSTGRES_APP_USER)"
owner_user="$(env_value POSTGRES_USER)"
if ! [[ "${app_user}" =~ ^[a-z_][a-z0-9_]{0,40}$ ]]; then
    echo "POSTGRES_APP_USER in backend/.env must be set: lower-case letters, digits and underscores" >&2
    exit 1
fi
if [ "${app_user}" = "${owner_user}" ]; then
    echo "POSTGRES_APP_USER must not be the same as POSTGRES_USER: the API must not sign in as the owner" >&2
    exit 1
fi
app_password="$(env_value POSTGRES_APP_PASSWORD)"
if ! [[ "${app_password}" =~ ^[A-Za-z0-9]{24,}$ ]]; then
    echo "POSTGRES_APP_PASSWORD in backend/.env must be 24 or more letters and digits (openssl rand -hex 24)" >&2
    exit 1
fi
unset app_password

# the database has to be running. The role is made in it, so nothing else needs to be up.
"${COMPOSE[@]}" up -d --wait db < /dev/null

if [ "${mode}" = "check" ]; then
    db_psql < "${REPO_DIR}/infra/sql/roles/app-role-check.sql"
    echo "application database role: ok"
else
    db_psql < "${REPO_DIR}/infra/sql/roles/app-role.sql" > /dev/null
    echo "application database role: created or refreshed"
fi
