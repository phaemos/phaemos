#!/usr/bin/env bash
# prints the body of one version's section of CHANGELOG.md: the lines between its
# `## [X.Y.Z] - date` heading and the next `## [` heading, without the heading itself and
# with blank lines at both ends removed. It is the release notes of that version. It fails
# when the section is missing or empty.
#
#   bash infra/scripts/changelog-section.sh 1.2.3 [path/to/CHANGELOG.md]
set -euo pipefail

version="${1:-}"
if ! [[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "not a release version (want X.Y.Z): ${version:-none}" >&2
    exit 1
fi
file="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/CHANGELOG.md}"

body="$(awk -v heading="## [${version}] - " '
    index($0, heading) == 1 { on = 1; next }
    on && /^## \[/ { exit }
    on && /^---[[:space:]]*$/ { next }
    on { print }
' "${file}")"

# trim blank lines at both ends
body="$(printf '%s\n' "${body}" | sed -e :a -e '/^[[:space:]]*$/{$d;N;ba' -e '}' | sed '/./,$!d')"
if [ -z "${body}" ]; then
    echo "CHANGELOG.md has no section for ${version} or the section is empty" >&2
    exit 1
fi
printf '%s\n' "${body}"
