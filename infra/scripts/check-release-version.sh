#!/usr/bin/env bash
# checks that every file that holds a version says the version being released and that
# CHANGELOG.md has a section for it. The release workflow runs it before anything is built.
#
#   bash infra/scripts/check-release-version.sh 1.2.3
#
# the version is given without the leading v. Only a final release (X.Y.Z) is accepted: a
# pre-release suffix is written differently by Python and by Cargo, so one tag cannot match
# both without a rule that nobody has chosen yet. The files that hold a version are:
#   client/python/pyproject.toml           version = "X.Y.Z"
#   client/python/phaemos_client/__init__.py   __version__ = "X.Y.Z"
#   edge/Cargo.toml                        version = "X.Y.Z" (the [package] table)
#   edge/Cargo.lock                        the phaemos-edge entry
#   frontend/package.json                  "version": "X.Y.Z"
#   frontend/package-lock.json             "version" at the top and for the "" package
# phaemosctl has no version in a file: the release workflow stamps it from the tag at build time.
# the backend's version is set by the deployment (RELEASE_VERSION) and is not in a file.
set -euo pipefail

version="${1:-}"
if ! [[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "not a release version (want X.Y.Z, no leading v and no suffix): ${version:-none}" >&2
    exit 1
fi

REPO_DIR="${RELEASE_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
problems=0

expect() {
    local label="$1" found="$2"
    if [ "${found}" != "${version}" ]; then
        echo "WRONG ${label}: found '${found:-nothing}', the tag says ${version}" >&2
        problems=$((problems + 1))
    else
        echo "ok    ${label}: ${found}"
    fi
}

# the first matching line of a file, cut to its quoted value
quoted() {
    sed -n -E "$1" "${REPO_DIR}/$2" | head -n 1
}

expect "client/python/pyproject.toml" "$(quoted 's/^version = "([^"]*)".*/\1/p' client/python/pyproject.toml)"
expect "client/python/phaemos_client/__init__.py" "$(quoted 's/^__version__ = "([^"]*)".*/\1/p' client/python/phaemos_client/__init__.py)"
expect "edge/Cargo.toml" "$(quoted 's/^version = "([^"]*)".*/\1/p' edge/Cargo.toml)"
expect "edge/Cargo.lock (phaemos-edge)" "$(awk '$0 == "name = \"phaemos-edge\"" { getline; gsub(/version = |"/, ""); print; exit }' "${REPO_DIR}/edge/Cargo.lock")"
expect "frontend/package.json" "$(quoted 's/^  "version": "([^"]*)".*/\1/p' frontend/package.json)"
expect "frontend/package-lock.json (top)" "$(quoted 's/^  "version": "([^"]*)".*/\1/p' frontend/package-lock.json)"
expect "frontend/package-lock.json (root package)" "$(awk '$0 ~ /^    "": \{/ { on = 1 } on && /"version":/ { gsub(/.*"version": "|".*/, ""); print; exit }' "${REPO_DIR}/frontend/package-lock.json")"

if ! grep -Eq "^## \[${version//./\\.}\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$" "${REPO_DIR}/CHANGELOG.md"; then
    echo "WRONG CHANGELOG.md: no heading '## [${version}] - YYYY-MM-DD'" >&2
    problems=$((problems + 1))
else
    echo "ok    CHANGELOG.md: has a section for ${version}"
fi

if [ "${problems}" -gt 0 ]; then
    echo "${problems} problem(s) against ${version} (lines starting WRONG above): the release is refused. Bump them to ${version} or tag the version they hold." >&2
    exit 1
fi
echo "every version agrees with ${version}"
