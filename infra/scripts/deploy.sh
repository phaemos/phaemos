#!/usr/bin/env bash
# builds and starts the production stack from the checkout it lives in, makes the database
# login the API uses, applies the schema step, waits for /status, checks the API runs as
# production, checks Nginx hands the API each caller's real address and checks that the Nginx
# configuration that is running is the one in this repository. Run it as the deploy user. It
# is safe to run again.
#
# it deploys a signed release tag and nothing else. VERIFY THE TAG BEFORE YOU CHECK IT OUT,
# with a command that is not part of the checkout (docs/deployment.md, Section 6):
#
#   git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile=~/.config/phaemos/allowed_signers verify-tag vX.Y.Z
#   git checkout vX.Y.Z && bash infra/scripts/deploy.sh
#
# the check below is a SECOND line. The script that runs it comes from the tag, so whoever can
# publish a tag controls it: it can catch a mistake and a tampered working tree and it cannot
# catch a malicious tag. The command above can.
#
# the checkout must be exactly at a tag, with no changed, untracked or stray ignored file in
# what is built or run and the tag's SSH signature must verify against DEPLOY_ALLOWED_SIGNERS
# (a file in git's allowed signers format that lists the release keys, default
# ~/.config/phaemos/allowed_signers). The tag object must also carry the name of the ref, so
# an old signed tag cannot be filed under a new name.
#
# the first install has no signing key set up yet and no Nginx site, so it needs these two
# overrides, once. They are separate, so skipping the Nginx check never skips the signature:
#
#   DEPLOY_FIRST_INSTALL=yes        skips the signed tag. Refused once the database holds a schema.
#   DEPLOY_SKIP_NGINX_CHECK=yes     skips the Nginx check, until Nginx is set up (Section 9).
#
# the schema step follows what the code supports. The API creates its tables with
# SQLAlchemy's create_all, but its own database login may not create tables, so a one-shot
# job (the schema service) runs create_all as the database owner before the API starts. The
# files in backend/migrations add what create_all does not: columns on tables that already
# exist, indexes and the audit log table. infra/scripts/migrate.sh applies each file once and
# records it (some files change data, so they must not run on every deploy). They run as the
# owner too. There is no Alembic setup in use.
#
# order: database up, API login made, image built. Then on a database that already holds the
# schema the migrations are applied and the table job runs after them. On a first install the
# table job runs first and the migrations follow. Either way both are done before the API
# starts, because the new code selects columns that older databases lack. Each file is safe
# to run under the code that is still serving.
set -euo pipefail

# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
STATUS_URL="${STATUS_URL:-http://127.0.0.1:8000/status}"
ALLOWED_SIGNERS="${DEPLOY_ALLOWED_SIGNERS:-${HOME}/.config/phaemos/allowed_signers}"
first_install=""
[ "${DEPLOY_FIRST_INSTALL:-}" = "yes" ] && first_install=1
skip_nginx=""
[ "${DEPLOY_SKIP_NGINX_CHECK:-}" = "yes" ] && skip_nginx=1

fail() {
    echo "$*" >&2
    exit 1
}

refuse_shell_overrides
if [ ! -f "${ENV_FILE}" ]; then
    fail "missing ${ENV_FILE}: copy backend/.env.example to backend/.env and fill it in"
fi
# the file holds secrets, so refuse to run while other users can read it
if others_can_access "${ENV_FILE}"; then
    fail "${ENV_FILE} is readable by other users: run chmod 600 on it"
fi

git_in_repo() {
    git -C "${REPO_DIR}" "$@"
}

echo "== release"
release_tag=""
if [ -n "${first_install}" ]; then
    echo "WARNING: DEPLOY_FIRST_INSTALL=yes skips the signed-tag check." >&2
    echo "WARNING: use it for the first install only. Deploy from a signed tag after that." >&2
else
    command -v git > /dev/null || fail "git is not installed"
    [ -e "${REPO_DIR}/.git" ] || fail "${REPO_DIR} is not a git checkout, so no tag can be verified"
    [ -f "${ALLOWED_SIGNERS}" ] || fail "no allowed signers file at ${ALLOWED_SIGNERS}: set DEPLOY_ALLOWED_SIGNERS to the file that lists the release keys"
    # a checkout that has drifted from its tag would build something nobody signed
    if ! git_in_repo diff --quiet HEAD --; then
        fail "tracked files differ from the checked out commit: deploy only what was signed"
    fi
    # a file that is not in the tag still runs if it sits where the build or the migrations look:
    # an untracked backend/migrations/999_x.sql would run as the database owner
    untracked="$(git_in_repo ls-files --others --exclude-standard)"
    if [ -n "${untracked}" ]; then
        fail "untracked files are present, so the checkout is not what was signed: $(printf '%s' "${untracked}" | head -n 5 | tr '\n' ' ')"
    fi
    # ignored files are allowed where they hold no code: backend/.env and compiled caches. Anywhere
    # that is built or run, one is refused
    stray="$(git_in_repo ls-files --others --ignored --exclude-standard | grep -E '^(infra/|backend/(migrations|app|scripts)/|backend/(Dockerfile|requirements))' | grep -vE '(^|/)__pycache__/|\.py[co]$' || true)"
    if [ -n "${stray}" ]; then
        fail "ignored files sit where the build or the migrations look: $(printf '%s' "${stray}" | head -n 5 | tr '\n' ' ')"
    fi
    tags="$(git_in_repo tag --points-at HEAD)"
    [ -n "${tags}" ] || fail "HEAD is not at a tag: git checkout a release tag first"
    head_commit="$(git_in_repo rev-parse HEAD)"
    while IFS= read -r candidate; do
        ref="refs/tags/${candidate}"
        # a signed tag is an annotated tag object. A lightweight tag has no signature
        [ "$(git_in_repo cat-file -t "${ref}" 2> /dev/null)" = "tag" ] || continue
        # the tag object names itself. A genuine old signed tag copied under a new ref name
        # still says its old name inside and the signature covers that name
        tag_text="$(git_in_repo cat-file tag "${ref}")"
        inner_name="$(awk '/^tag /{print substr($0, 5); exit}' <<< "${tag_text}")"
        [ "${inner_name}" = "${candidate}" ] || continue
        [ "$(git_in_repo rev-parse "${ref}^{commit}")" = "${head_commit}" ] || continue
        # an SSH signature only. git picks the program from the signature's own header, so a
        # PGP signature would otherwise be checked against the deploy user's keyring and not
        # against the allowed signers file
        grep -q '^-----BEGIN SSH SIGNATURE-----$' <<< "${tag_text}" || continue
        if git_in_repo -c gpg.format=ssh -c "gpg.ssh.allowedSignersFile=${ALLOWED_SIGNERS}" verify-tag "${candidate}" > /dev/null 2>&1; then
            release_tag="${candidate}"
            break
        fi
    done <<< "${tags}"
    [ -n "${release_tag}" ] || fail "no tag at HEAD carries an SSH signature that verifies against ${ALLOWED_SIGNERS} and names itself"
fi
release_commit="$(git_in_repo rev-parse HEAD 2> /dev/null || echo unknown)"
echo "release: ${release_tag:-unsigned first install} at commit ${release_commit}"

echo "== pre-flight"
secret_key="$(env_value SECRET_KEY)"
if [ "${#secret_key}" -lt 32 ]; then
    fail "SECRET_KEY in backend/.env must be at least 32 characters (openssl rand -hex 32)"
fi
db_password="$(env_value POSTGRES_PASSWORD)"
if ! [[ "${db_password}" =~ ^[A-Za-z0-9]{24,}$ ]]; then
    fail "POSTGRES_PASSWORD in backend/.env must be 24 or more letters and digits (openssl rand -hex 24)"
fi
app_password="$(env_value POSTGRES_APP_PASSWORD)"
if ! [[ "${app_password}" =~ ^[A-Za-z0-9]{24,}$ ]]; then
    fail "POSTGRES_APP_PASSWORD in backend/.env must be 24 or more letters and digits (openssl rand -hex 24)"
fi
if [ "${app_password}" = "${db_password}" ]; then
    fail "POSTGRES_APP_PASSWORD must differ from POSTGRES_PASSWORD"
fi
redis_password="$(env_value REDIS_PASSWORD)"
if ! [[ "${redis_password}" =~ ^[A-Za-z0-9]{24,}$ ]]; then
    fail "REDIS_PASSWORD in backend/.env must be 24 or more letters and digits (openssl rand -hex 24)"
fi
for name in POSTGRES_DB POSTGRES_USER POSTGRES_APP_USER; do
    if [ -z "$(env_value "${name}")" ]; then
        fail "${name} is not set in backend/.env"
    fi
done
if [ "$(env_value POSTGRES_APP_USER)" = "$(env_value POSTGRES_USER)" ]; then
    fail "POSTGRES_APP_USER must differ from POSTGRES_USER: the API must not sign in as the owner"
fi
unset secret_key db_password app_password redis_password

apply_migrations() {
    bash "${REPO_DIR}/infra/scripts/migrate.sh"
}

echo "== database"
# only the database, so a running API keeps serving the old code while the schema changes
"${COMPOSE[@]}" up -d --wait --wait-timeout 120 db

# does the database already hold the application's schema? Read as the owner, so the answer
# does not depend on the API's own rights. A failed lookup stops the deploy: guessing "no"
# would take the first-install branch on a database that is in use.
schema_exists="$(db_psql -tA -c "SELECT to_regclass('public.devices') IS NOT NULL" | tr -d '[:space:]')" \
    || fail "could not ask the database whether the schema exists: nothing was changed"
case "${schema_exists}" in
    t | f) ;;
    *) fail "could not ask the database whether the schema exists (answer: '${schema_exists}'): nothing was changed" ;;
esac
if [ -n "${first_install}" ] && [ "${schema_exists}" = "t" ]; then
    fail "DEPLOY_FIRST_INSTALL=yes is refused: this database already holds the application's tables, so this is not a first install. Deploy a signed tag."
fi

echo "== the API's database login"
bash "${REPO_DIR}/infra/scripts/db-role.sh"

echo "== build"
"${COMPOSE[@]}" build

if [ "${schema_exists}" = "t" ]; then
    # an existing database: the new code selects columns that older databases lack, so the
    # migrations go in BEFORE anything new runs. Each file is safe under the code that is
    # still serving. Only after them does the schema job add any table the new models need.
    echo "== schema step (before the new code starts)"
    apply_migrations
    echo "== tables (as the database owner)"
    "${COMPOSE[@]}" run --rm --no-deps schema
else
    # a first install: there is no schema yet, so the owner's job creates the tables first
    # and the migrations then add what create_all does not (the audit log table, indexes);
    # the API is still not started, so it never serves a request before both have run.
    echo "== tables (as the database owner)"
    "${COMPOSE[@]}" run --rm --no-deps schema
    echo "== schema step"
    apply_migrations
fi

echo "== start"
# --wait returns once every container is healthy and fails if one is not
"${COMPOSE[@]}" up -d --wait --wait-timeout 240

echo "== the API's database login after the migrations"
# the default privileges cover every table the owner made, so this finds nothing wrong. It
# is the proof that a new table did not leave the API without rights.
bash "${REPO_DIR}/infra/scripts/db-role.sh" --check

echo "== waiting for ${STATUS_URL}"
ok=""
for _ in $(seq 1 30); do
    body="$(curl -fsS --max-time 5 "${STATUS_URL}" 2>/dev/null || true)"
    if printf '%s' "${body}" | grep -q '"status":"operational"'; then
        ok=1
        break
    fi
    sleep 2
done
if [ -z "${ok}" ]; then
    echo "/status did not report operational in time. Last answer: ${body:-none}" >&2
    echo "read the logs: docker compose --env-file backend/.env -f infra/docker-compose.prod.yml logs --tail 100 backend" >&2
    exit 1
fi
echo "${body}"
# a model file that will not load leaves every reading unscored and the API still reports operational
if printf '%s' "${body}" | grep -q '"model":"error"'; then
    fail "the anomaly model file cannot be loaded, so readings are stored without a score. Retrain it: POST /api/v1/ml/retrain"
fi

echo "== environment"
# the API no longer names its environment to a stranger, so ask the container. It reads the
# settings exactly as the API did when it started
if ! "${COMPOSE[@]}" exec -T backend python -c 'import sys; from app.config import settings; sys.exit(0 if settings.environment.strip().lower() == "production" and not settings.is_development else 1)'; then
    fail "the API does not run as production: set ENVIRONMENT=production in backend/.env and run again"
fi
echo "the API runs as production"

echo "== caller addresses"
# the API trusts X-Real-IP only from the proxy's own address (TRUSTED_PROXIES). If Nginx does
# not arrive from that address on this machine, every visitor shares one identity and no rate
# limit tells them apart. The /status route is limited to 120 a minute per caller: 125
# requests that each claim a different caller must all pass when the header is believed and
# are refused once the limit is used when it is not.
refused=0
for n in $(seq 1 125); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H "X-Real-IP: 198.51.$((n / 250)).$((n % 250 + 1))" "${STATUS_URL}" || true)"
    [ "${code}" = "429" ] && refused=$((refused + 1))
done
if [ "${refused}" -gt 0 ]; then
    fail "the API refused ${refused} of 125 requests that claimed different callers: it does not believe the proxy's X-Real-IP, so every visitor would share one limit. Check TRUSTED_PROXIES and the edge network's gateway in infra/docker-compose.prod.yml against the address Nginx arrives from."
fi
echo "each caller is told apart"

echo "== nginx"
if [ -n "${skip_nginx}" ]; then
    echo "WARNING: DEPLOY_SKIP_NGINX_CHECK=yes skips the Nginx check. After Nginx and the certificate are in place run: bash infra/scripts/check-nginx.sh" >&2
else
    bash "${REPO_DIR}/infra/scripts/check-nginx.sh"
fi

# old images pile up after every rebuild and a 25 GB disk is not large
docker image prune -f > /dev/null

echo "deployed: ${release_tag:-unsigned first install} at commit ${release_commit}"
