#!/usr/bin/env bash
# loads a backup made by backup.sh into the production database. It destroys the data that
# is there now, so it asks you to type the database name first.
#
#   bash infra/scripts/restore.sh ~/backups/phaemos-DATE.sql.gz.age /dev/shm/restore.key
#
# RUN IT INSIDE tmux (or screen). A dropped terminal ends the script part-way. The script
# handles that safely (see below), but then the restore has to be started again.
#
# the second argument is the age PRIVATE key file. It is never kept on the server: copy it
# here for the restore (into /dev/shm, which is memory), run this script and delete it
# straight after. Memory can be swapped to the disk under pressure, so treat the key as
# exposed once a restore has been done on the server: make a new key pair afterwards and put
# the new public key in BACKUP_AGE_RECIPIENT. The key can also be named in
# RESTORE_AGE_KEY_FILE. A plain .sql.gz file from an older version of backup.sh needs no key.
#
# it works the same on the live droplet and on a new one. On a new droplet put the saved
# backend/.env back FIRST (a new SECRET_KEY would make every device key and two-step secret
# unreadable) and run deploy.sh so the stack exists, then this script. It does this: checks the
# file decrypts and ends in a complete dump, stops the API, then in ONE transaction empties the
# public schema and loads the dump, gives the API's database login its rights back and starts
# the API again.
#
# the transaction is opened with BEGIN and committed with COMMIT and the COMMIT is sent only
# after the whole dump has been read and its closing line seen. psql would otherwise treat
# the end of its input as the end of the script and commit whatever had arrived, so a stream
# that stopped early (a cut file, a dropped connection, a killed client) would replace the
# data with a part of it. Here a stream that ends early ends in ROLLBACK, a failing statement
# and a non-zero exit and the old data stays.
#
# the dump holds the database only. Redis (the repeat windows and daily caps), the firmware
# volume, the model volume and backend/.env are not in it and this script restores none of
# them. In particular it never restores a model file: the model is a pickle and loading one
# runs whatever code it holds. See the deployment guide, Section 14.
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

fail() {
    echo "$*" >&2
    exit 1
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ] || [ ! -f "$1" ]; then
    echo "usage: bash infra/scripts/restore.sh <backup file> [age private key file]" >&2
    exit 1
fi
dump="$1"
key_file="${2:-${RESTORE_AGE_KEY_FILE:-}}"
refuse_shell_overrides
if [ ! -f "${ENV_FILE}" ]; then
    echo "missing ${ENV_FILE}" >&2
    exit 1
fi

# print the dump as plain SQL on stdout, whichever way it was written
dump_stream() {
    case "${dump}" in
        *.age) age -d -i "${key_file}" "${dump}" | gunzip -c ;;
        *.gz) gunzip -c "${dump}" ;;
        *)
            echo "the file name must end in .sql.gz.age or .sql.gz" >&2
            return 1
            ;;
    esac
}

case "${dump}" in
    *.age)
        command -v age > /dev/null || fail "age is not installed: sudo apt-get install age"
        if [ -z "${key_file}" ] || [ ! -f "${key_file}" ]; then
            fail "this backup is encrypted: give the age private key file as the second argument"
        fi
        # a private key that other users can read is a key that has leaked
        if others_can_access "${key_file}"; then
            fail "${key_file} is readable by other users: run chmod 600 on it"
        fi
        ;;
    *.gz)
        echo "NOTE: ${dump} is not encrypted. It came from an older version of backup.sh." >&2
        ;;
esac

# the stream that goes to psql: the end of the dump decides between COMMIT and ROLLBACK. The
# dump's last real line is "-- PostgreSQL database dump complete", followed by nothing but
# comment lines, blank lines and (in recent pg_dump) a \unrestrict line. Any other line after
# it or no such line, means the stream is not whole.
with_commit_decision() {
    awk '
        { print }
        $0 == "-- PostgreSQL database dump complete" { complete = 1; next }
        $0 !~ /^(--.*|\\unrestrict .*)?$/ { complete = 0 }
        END {
            if (complete) { print "COMMIT;" }
            else {
                print "ROLLBACK;"
                print "DO $$ BEGIN RAISE EXCEPTION \047the dump ended before its closing line: nothing was committed\047; END $$;"
            }
        }'
}

# a failure at any stage has to say what is true at that stage
stage="checking"
api_stopped=""
restart_api() {
    echo "starting the API again" >&2
    "${COMPOSE[@]}" up -d --wait backend < /dev/null || echo "the API did not start: run  docker compose --env-file backend/.env -f infra/docker-compose.prod.yml up -d  and read its logs" >&2
}
# a signal fires no ERR trap, so it has its own. The load runs in one transaction that is
# committed only after the closing line, so a signal during it leaves the old data in place
# once the open session is gone. Any leftover owner session (the exec'd psql can outlive its
# client) is ended here, which rolls it back, before the API is started again.
on_signal() {
    trap - ERR INT TERM HUP
    echo >&2
    echo "interrupted while ${stage}." >&2
    if [ "${stage}" = "loading" ]; then
        db_psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND usename = current_user AND pid <> pg_backend_pid()" < /dev/null > /dev/null 2>&1 || true
        echo "the load had not been committed, so the old data is in place. Run restore.sh again, inside tmux." >&2
    fi
    if [ "${stage}" = "after the load" ]; then
        echo "the data WAS replaced. Run:  bash infra/scripts/db-role.sh  and then  docker compose --env-file backend/.env -f infra/docker-compose.prod.yml up -d backend" >&2
    elif [ -n "${api_stopped}" ]; then
        restart_api
    fi
    exit 130
}
on_error() {
    local status=$?
    trap - ERR INT TERM HUP
    case "${stage}" in
        checking) echo "restore failed while checking: nothing was changed." >&2 ;;
        "stopping the API") echo "restore failed before the load: nothing was changed." >&2 ;;
        loading)
            echo "restore failed during the load. The load runs in one transaction that is committed only after the whole dump was read, so the old data is in place." >&2
            ;;
        "after the load")
            echo "the data WAS replaced, but a step after it failed. Run:  bash infra/scripts/db-role.sh  and then  docker compose --env-file backend/.env -f infra/docker-compose.prod.yml up -d backend" >&2
            exit "${status}"
            ;;
    esac
    [ -n "${api_stopped}" ] && restart_api
    exit "${status}"
}
trap on_signal INT TERM HUP
trap on_error ERR

# a damaged or wrong-key file is found now, before anything is stopped. age checks every
# chunk, gunzip checks the archive and a complete pg_dump ends with a marker line, so a file
# cut short is refused too. Nothing is written to disk.
echo "== checking the backup"
# the end of the stream is captured first and searched afterwards: `grep -q` quits at its first
# match and under pipefail a producer that is still writing then dies of SIGPIPE and fails the
# whole pipeline, which refused good files now and then
dump_end="$(dump_stream | tail -n 5)" || fail "the backup could not be decrypted and unpacked: nothing changed"
if ! printf '%s\n' "${dump_end}" | grep -q 'PostgreSQL database dump complete'; then
    fail "the backup did not decrypt to a complete dump: nothing changed"
fi

# the database has to be running to be asked its name. Both calls read from /dev/null:
# docker compose would otherwise swallow the answer to the question below when it is
# piped in or typed ahead.
"${COMPOSE[@]}" up -d --wait db < /dev/null
# shellcheck disable=SC2016
db_name="$("${COMPOSE[@]}" exec -T db sh -c 'printf %s "$POSTGRES_DB"' < /dev/null)"

echo "This replaces EVERYTHING in the database '${db_name}' with the contents of:"
echo "  ${dump}"
printf "Type the database name to continue: "
answer=""
read -r answer || fail "no answer was given: nothing changed"
if [ "${answer}" != "${db_name}" ]; then
    fail "not confirmed: nothing changed"
fi

echo "== stopping the API"
stage="stopping the API"
api_stopped=1
"${COMPOSE[@]}" stop backend < /dev/null

echo "== loading the dump"
stage="loading"
# one transaction. BEGIN first, then the schema is dropped and made again and any large
# object is unlinked (a leftover one would make the dump fail on a duplicate key), then the
# dump, then COMMIT only when the stream was whole. pipefail makes a failed age or gunzip
# fail the pipe too. psql stops at the first error and then exits non-zero without committing.
{
    printf 'BEGIN;\nDROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\nSELECT lo_unlink(oid) FROM pg_largeobject_metadata;\n'
    dump_stream
} | with_commit_decision | db_psql > /dev/null

# the data is replaced now, so a failure from here on must not claim the old data is intact
stage="after the load"

echo "== the API's database login"
# dropping the schema dropped the rights with it. The tables are now owned by the owner
bash "${REPO_DIR}/infra/scripts/db-role.sh"

echo "== starting the API"
trap - ERR
"${COMPOSE[@]}" up -d --wait backend < /dev/null
api_stopped=""

echo "restored. Run deploy.sh to apply any migration newer than the backup and check /status."
echo "The model file was NOT restored. If the model volume was lost, retrain with POST /api/v1/ml/retrain."
echo "Delete the key file now and make a new backup key pair soon: this key was on the server."
