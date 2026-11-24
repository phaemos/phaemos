#!/usr/bin/env bash
# tests changed-areas.sh against a throwaway git repository with crafted commits: a rename out
# of an area, a non-ASCII path, a path with a space, the root compose file, the deploy scripts, an
# unknown file and files that must run nothing. It exits 1 when any answer is wrong.
#
#   bash infra/scripts/test-changed-areas.sh
set -euo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/changed-areas.sh"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
cd "${work}"
git init -q -b scratch .
git config core.hooksPath /dev/null
git config user.email test@example.invalid
git config user.name test
git config commit.gpgsign false
mkdir -p backend/app docs infra/scripts
echo a > backend/app/util.py
echo a > docs/index.md
echo a > README.md
git add -A
git commit -q -m base
base="$(git rev-parse HEAD)"

failures=0
# check NAME "area area": the commit to test is HEAD, made by the caller. The expected list is
# the areas that must be true. The word "nothing" stands for an empty list
check() {
    local name="$1" expected="$2" out actual
    out="$(EVENT_NAME=pull_request BASE_SHA="${base}" HEAD_SHA="$(git rev-parse HEAD)" bash "${SCRIPT}")"
    actual="$({ grep '=true' <<< "${out}" || true; } | cut -d= -f1 | sort | xargs)"
    actual="${actual:-nothing}"
    expected="$(tr ' ' '\n' <<< "${expected}" | sort | xargs)"
    if [ "${actual}" = "${expected}" ]; then
        echo "ok    ${name}: ${actual}"
    else
        echo "WRONG ${name}: wanted [${expected}] got [${actual}]" >&2
        failures=$((failures + 1))
    fi
    git reset -q --hard "${base}"
}
all_areas="backend client_go client_python discord docs edge firmware frontend infra scripts"

git mv backend/app/util.py docs/util.py && git commit -q -m rename
check "rename out of backend" "backend docs"

mkdir -p "frontend/café"
echo a > "frontend/café/page.tsx"
git add -A && git commit -q -m nonascii
check "non-ASCII path" "frontend"

mkdir -p "firmware/with space"
echo a > "firmware/with space/x.ino"
git add -A && git commit -q -m space
check "path with a space" "firmware"

echo a > docker-compose.yml
git add -A && git commit -q -m compose
check "root docker-compose.yml" "backend"

echo a > infra/scripts/deploy.sh
git add -A && git commit -q -m deploy
check "infra/scripts/deploy.sh" "backend infra scripts"

echo a > something-new.cfg
git add -A && git commit -q -m unknown
check "unknown file runs everything" "${all_areas}"

echo b >> README.md
git add -A && git commit -q -m readme
check "root markdown runs nothing" "nothing"

echo b >> docs/index.md
git add -A && git commit -q -m docs
check "docs page" "docs"

mkdir -p .github/workflows
echo a > .github/workflows/x.yml
git add -A && git commit -q -m workflow
check "workflow change runs everything" "${all_areas}"

count="$(EVENT_NAME=push BASE_SHA=x HEAD_SHA=y bash "${SCRIPT}" | grep -c '=true')"
if [ "${count}" = "10" ]; then echo "ok    push runs everything"; else echo "WRONG push" >&2; failures=$((failures + 1)); fi
count="$(EVENT_NAME=pull_request BASE_SHA=deadbeef HEAD_SHA=HEAD bash "${SCRIPT}" | grep -c '=true')"
if [ "${count}" = "10" ]; then echo "ok    unreadable range runs everything"; else echo "WRONG range" >&2; failures=$((failures + 1)); fi

[ "${failures}" -eq 0 ] || { echo "${failures} wrong" >&2; exit 1; }
echo "changed-areas.sh answers every crafted case correctly"
