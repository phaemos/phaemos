#!/usr/bin/env bash
# applies the numbered SQL files in backend/migrations once each, in order and records each
# one. deploy.sh and `make migrate` both run this script, so the two cannot drift apart.
#
#   bash infra/scripts/migrate.sh              production stack (docker compose, as the owner)
#   bash infra/scripts/migrate.sh dev          the development database container
#   bash infra/scripts/migrate.sh [dev] --rehash 020_open_alert_unique.sql
#
# why a record: the files are guarded with IF NOT EXISTS, but some of them also change data
# (020 resolves open alerts, 028 and 029 collapse duplicates), so running every file on every
# deploy once closed real open alerts. The record is the table public.schema_migrations
# (file name, SHA-256 of the file, when it was applied). The application's own login cannot
# read or write it.
#
# what it does for each file, in order:
#   - never applied: the file runs through psql (stopping at its first error, never in one
#     transaction, because some files build an index CONCURRENTLY) and the record is written
#     in the same psql session, after the last statement. A file that fails is not recorded
#     and the script stops, so the next run tries it again from the start. A crash in the
#     instant between the last statement and the record means the file runs once more, which
#     its IF NOT EXISTS guards allow.
#   - applied and unchanged: skipped.
#   - applied and the file has CHANGED since: the script refuses, loudly and applies
#     nothing further. An applied migration must not be edited: add a new numbered file. If
#     the edit is deliberate and harmless (a comment or a fix that only matters to databases
#     that have not run the file yet), the operator confirms that with --rehash FILE, which
#     records the new hash without running the file.
#
# a database that already has the application's tables but no record (a developer's database
# from before this script existed): every file runs once, as every deploy used to do and is
# recorded. That is the only database that can be in this state, because nothing is deployed
# with the old script. 020 was changed so that this first run cannot close a rule alert.
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

mode="prod"
rehash=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        prod | dev) mode="$1" ;;
        --rehash)
            shift
            rehash="${1:-}"
            [ -n "${rehash}" ] || { echo "--rehash needs a file name" >&2; exit 1; }
            ;;
        *)
            echo "usage: bash infra/scripts/migrate.sh [prod|dev] [--rehash FILE]" >&2
            exit 1
            ;;
    esac
    shift
done

# psql as the database owner, with the SQL on stdin. Production goes through the compose db
# service (lib.sh). Development goes to the container the Makefile has always used.
if [ "${mode}" = "dev" ]; then
    DEV_CONTAINER="${MIGRATE_DEV_CONTAINER:-phaemos-db-1}"
    DEV_USER="${MIGRATE_DEV_USER:-postgres}"
    DEV_DB="${MIGRATE_DEV_DB:-phaemos}"
    psql_owner() {
        docker exec -i -e PGOPTIONS="-c client_min_messages=warning" "${DEV_CONTAINER}" \
            psql -v ON_ERROR_STOP=1 -q -U "${DEV_USER}" -d "${DEV_DB}" "$@"
    }
else
    psql_owner() { db_psql "$@"; }
fi

sha256_of() {
    if command -v sha256sum > /dev/null; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

MIGRATIONS_DIR="${REPO_DIR}/backend/migrations"

# the record. IF NOT EXISTS, so the first run on any database makes it
psql_owner -c "CREATE TABLE IF NOT EXISTS public.schema_migrations (filename text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())" > /dev/null

recorded_hash() {
    psql_owner -tA -c "SELECT sha256 FROM public.schema_migrations WHERE filename = '$1'" | tr -d '[:space:]'
}

valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9_.-]+\.sql$ ]]
}

if [ -n "${rehash}" ]; then
    valid_name "${rehash}" || { echo "not a migration file name: ${rehash}" >&2; exit 1; }
    [ -f "${MIGRATIONS_DIR}/${rehash}" ] || { echo "no such file: ${MIGRATIONS_DIR}/${rehash}" >&2; exit 1; }
    [ -n "$(recorded_hash "${rehash}")" ] || { echo "${rehash} was never applied here: there is nothing to rehash" >&2; exit 1; }
    psql_owner -c "UPDATE public.schema_migrations SET sha256 = '$(sha256_of "${MIGRATIONS_DIR}/${rehash}")' WHERE filename = '${rehash}'" > /dev/null
    echo "recorded the new hash of ${rehash} without running it"
    exit 0
fi

# say so when this is the one-off first run on a database that has tables and no record
count_recorded="$(psql_owner -tA -c "SELECT count(*) FROM public.schema_migrations" | tr -d '[:space:]')"
has_schema="$(psql_owner -tA -c "SELECT to_regclass('public.devices') IS NOT NULL" | tr -d '[:space:]')"
if [ "${count_recorded}" = "0" ] && [ "${has_schema}" = "t" ]; then
    echo "NOTE: this database has tables and no record of applied migrations. Every file runs once now and is recorded."
fi

shopt -s nullglob
applied=0
skipped=0
for path in "${MIGRATIONS_DIR}"/*.sql; do
    file="$(basename "${path}")"
    valid_name "${file}" || { echo "refusing a migration file with an unexpected name: ${file}" >&2; exit 1; }
    hash="$(sha256_of "${path}")"
    old="$(recorded_hash "${file}")"
    if [ -n "${old}" ]; then
        if [ "${old}" != "${hash}" ]; then
            echo "REFUSED: ${file} was applied here and its content has changed since." >&2
            echo "  recorded ${old}" >&2
            echo "  now      ${hash}" >&2
            echo "An applied migration must not be edited: put the change in a new numbered file." >&2
            echo "If the edit is deliberate and you have read the difference, run:" >&2
            echo "  bash infra/scripts/migrate.sh${mode:+ ${mode}} --rehash ${file}" >&2
            exit 1
        fi
        skipped=$((skipped + 1))
        continue
    fi
    echo "applying ${file}"
    # the file, then the record, in one psql session. ON_ERROR_STOP ends the session at the
    # first error, so a failed file never reaches the INSERT
    {
        cat "${path}"
        printf '\nINSERT INTO public.schema_migrations (filename, sha256) VALUES ('"'"'%s'"'"', '"'"'%s'"'"');\n' "${file}" "${hash}"
    } | psql_owner > /dev/null
    applied=$((applied + 1))
done
echo "migrations: ${applied} applied, ${skipped} already applied"
