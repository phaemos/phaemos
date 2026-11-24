#!/usr/bin/env bash
# scans for committed secrets: the commits of the change (so a secret that was added and then
# removed in a later commit is still found) and then the working tree. It exits 1 on any finding.
#
#   EVENT_NAME=pull_request PR_BASE=<sha> PR_HEAD=<sha> bash infra/scripts/run-gitleaks.sh
#   EVENT_NAME=push PUSH_BEFORE=<sha> PUSH_AFTER=<sha> bash infra/scripts/run-gitleaks.sh
#
# any other event, a new branch or a missing value scans the whole history. The checkout must
# have the full history (fetch-depth 0). --redact keeps the secret out of the log.
#
# the scanner's configuration and ignore file are read from fixed paths, .github/gitleaks.toml
# and .github/gitleaksignore. For a pull request they are taken from the BASE commit. A change
# cannot therefore switch the scan off by adding or editing a config or an ignore file, in
# either of the root names the scanner would otherwise look for. Without a file at the base the
# scanner's default rules apply.
#
# an inline allow comment (the word gitleaks, a colon and the word allow) tells the scanner to skip
# its own line and no flag turns that off. So the script fails a pull request that ADDS one and a
# person decides whether the line really is safe and removes the comment or moves the entry into
# the ignore file at the base.
set -euo pipefail

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

range=""
config_from="HEAD"
case "${EVENT_NAME:-}" in
    pull_request)
        range="${PR_BASE:?}..${PR_HEAD:?}"
        config_from="${PR_BASE}"
        ;;
    push)
        before="${PUSH_BEFORE:-}"
        if [ -n "${before}" ] && ! [[ "${before}" =~ ^0+$ ]]; then
            range="${before}..${PUSH_AFTER:?}"
        fi
        ;;
esac

# the settings, from the base commit
config="${work}/gitleaks.toml"
ignore="${work}/gitleaksignore"
if ! git show "${config_from}:.github/gitleaks.toml" > "${config}" 2> /dev/null; then
    printf '[extend]\nuseDefault = true\n' > "${config}"
fi
if ! git show "${config_from}:.github/gitleaksignore" > "${ignore}" 2> /dev/null; then
    : > "${ignore}"
fi
flags=(--redact --exit-code 1 --config "${config}" --gitleaks-ignore-path "${ignore}")

if [ -n "${range}" ]; then
    marker="gitleaks"":allow"
    # added lines only and not in this script (which has to name the marker to look for it)
    if git diff --unified=0 "${range/../...}" -- . ':!infra/scripts/run-gitleaks.sh' | grep -E '^\+' | grep -v '^+++' | grep -qF "${marker}"; then
        echo "this change adds an inline allow comment for the secret scanner. Remove it and have a maintainer review the line" >&2
        exit 1
    fi
    echo "== commits ${range}"
    gitleaks git "${flags[@]}" --log-opts "${range}" .
else
    echo "== the whole history"
    gitleaks git "${flags[@]}" .
fi
echo "== working tree"
gitleaks dir "${flags[@]}" .
