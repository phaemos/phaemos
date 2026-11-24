#!/usr/bin/env bash
# checks that the numbered SQL files apply to a database that has the application's tables and
# that applying them a second time changes nothing. It is the CI proof of what deploy.sh relies
# on at a first install: tables first (the schema job's create_all), then the migrations.
#
#   MIGRATE_DEV_CONTAINER=postgres MIGRATE_DEV_DB=phaemos_test bash infra/scripts/check-migrations.sh
#
# the caller creates the tables first and names the database container and database as
# migrate.sh's dev mode does. Both variables are required here so the script can never run
# against the default development database by accident.
#
# "changes nothing" is two tests: the second run reports no file applied and a dump of the
# schema is the same before and after it.
set -euo pipefail

: "${MIGRATE_DEV_CONTAINER:?name the database container}"
: "${MIGRATE_DEV_DB:?name the database}"
export MIGRATE_DEV_CONTAINER MIGRATE_DEV_DB

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_USER="${MIGRATE_DEV_USER:-postgres}"

schema_dump() {
    # newer pg_dump versions write a random \restrict token on two lines of every dump, so those lines are left out
    docker exec "${MIGRATE_DEV_CONTAINER}" pg_dump -U "${DEV_USER}" -d "${MIGRATE_DEV_DB}" --schema-only --no-owner | grep -vE '^\\(un)?restrict '
}

echo "== first run: every file is applied"
first="$(bash "${HERE}/migrate.sh" dev)"
printf '%s\n' "${first}" | tail -n 3
if ! grep -Eq '^migrations: [1-9][0-9]* applied, ' <<< "${first}"; then
    echo "the first run applied no file: the database was not empty of migrations" >&2
    exit 1
fi
before="$(schema_dump | cksum)"

echo "== second run: nothing may be applied"
second="$(bash "${HERE}/migrate.sh" dev)"
printf '%s\n' "${second}"
if ! grep -Eq '^migrations: 0 applied, [1-9][0-9]* already applied$' <<< "${second}"; then
    echo "the second run applied a file or did not skip them all" >&2
    exit 1
fi
after="$(schema_dump | cksum)"
if [ "${before}" != "${after}" ]; then
    echo "the schema changed during the second run" >&2
    exit 1
fi
echo "migrations apply once and a second run changes nothing"
