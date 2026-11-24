#!/usr/bin/env bash
# fails when a `uses:` line in .github/ is not pinned to a full 40 character commit that carries
# its version in a trailing comment. A tag such as v4 can be moved by whoever controls the
# action's repository, so a moved tag would run new code in our workflows with our token. A
# commit cannot be moved. Local actions (./path) and images pinned by sha256 digest are allowed.
#
#   bash infra/scripts/check-action-pins.sh [directory ...]     default: .github
#
# to update a pin see .github/workflows/README.md.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ "$#" -eq 0 ]; then
    set -- "${REPO_DIR}/.github"
fi

problems=0
checked=0
while IFS= read -r file; do
    # every `uses:` key, at the start of a line, after a list dash or inline in a flow mapping
    # such as `- {uses: owner/repo@tag}`. Whole-line comments are skipped
    while IFS= read -r hit; do
        line_no="${hit%%:*}"
        text="${hit#*:}"
        # the value after `uses:`, cut at a comma, a closing brace or a comment, quotes removed
        value="$(sed -E 's/.*(^|[^A-Za-z0-9_-])uses:[[:space:]]*//; s/[[:space:]]*(#.*|[,}].*)$//; s/^["'"'"']//; s/["'"'"']$//' <<< "${text}")"
        checked=$((checked + 1))
        case "${value}" in
            ./*) continue ;;
            docker://*@sha256:*) continue ;;
        esac
        if ! [[ "${value}" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+@[0-9a-f]{40}$ ]]; then
            echo "NOT PINNED to a full commit: ${file}:${line_no}: ${value}" >&2
            problems=$((problems + 1))
        elif ! [[ "${text}" =~ [[:space:]]#[[:space:]]*v?[0-9][0-9A-Za-z._-]*[[:space:]]*$ ]] && ! [[ "${text}" =~ \}[[:space:]]*$ ]]; then
            echo "NO VERSION COMMENT after the commit: ${file}:${line_no}: ${value}" >&2
            problems=$((problems + 1))
        fi
    done < <(grep -nE '(^|[^A-Za-z0-9_-])uses:' "${file}" | grep -vE '^[0-9]+:[[:space:]]*#' || true)
done < <(find "$@" -type f \( -name '*.yml' -o -name '*.yaml' \) | sort)

if [ "${problems}" -gt 0 ]; then
    echo "${problems} of ${checked} uses: lines are not pinned." >&2
    exit 1
fi
echo "all ${checked} uses: lines are pinned to a full commit with a version comment"
