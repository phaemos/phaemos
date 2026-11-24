#!/usr/bin/env bash
# says which parts of the repository a change touches, so CI can skip the jobs of the parts it
# did not touch. It prints one `name=true` or `name=false` line per area, which is the format
# the runner reads from $GITHUB_OUTPUT.
#
#   BASE_SHA=<commit> HEAD_SHA=<commit> EVENT_NAME=pull_request bash infra/scripts/changed-areas.sh
#
# a skipped job reports as skipped and not as failed, so a wrong guess here hides a failure. The
# script therefore decides to run too much and not too little:
#   - anything that is not a pull request (a push to main or a manual run) runs every area
#   - a path that matches no rule below runs every area. Only the paths listed as harmless run
#     nothing
#   - if the commits cannot be compared every area runs
#   - renames are listed as a delete plus an add, so the old path counts too
#   - paths are read null-separated, so a name with spaces or non-ASCII characters is not quoted
#     into something that matches nothing
# the map follows what the tests read: backend/tests read backend/ and infra/ (the deploy
# scripts and the compose files) and the root docker-compose.yml. They also read the generated
# API documents.
# infra/scripts/test-changed-areas.sh checks these rules with crafted commits.
set -euo pipefail

areas=(backend frontend client_python client_go edge discord firmware infra docs scripts)
declare -A hit
for area in "${areas[@]}"; do hit[${area}]=false; done

all() {
    for area in "${areas[@]}"; do hit[${area}]=true; done
}

emit() {
    for area in "${areas[@]}"; do
        echo "${area}=${hit[${area}]}"
    done
}

if [ "${EVENT_NAME:-}" != "pull_request" ]; then
    all
    emit
    exit 0
fi

# bash cannot hold a null byte in a variable, so the list goes to a file
list="$(mktemp)"
trap 'rm -f "${list}"' EXIT
if ! git diff --name-only -z --no-renames "${BASE_SHA:?}" "${HEAD_SHA:?}" > "${list}" 2> /dev/null; then
    all
    emit
    exit 0
fi

while IFS= read -r -d '' file; do
    matched=false
    case "${file}" in
        .github/ISSUE_TEMPLATE/* | .github/DISCUSSION_TEMPLATE/* | .github/PULL_REQUEST_TEMPLATE.md | .github/FUNDING.yml | .github/dependabot.yml) matched=true ;;
        .github/* | Makefile | infra/scripts/changed-areas.sh | infra/scripts/test-changed-areas.sh)
            all
            matched=true
            ;;
    esac
    case "${file}" in
        backend/* | docker-compose.yml)
            hit[backend]=true
            matched=true
            ;;
        docs/openapi.json | docs/api-routes.md)
            hit[backend]=true
            hit[docs]=true
            matched=true
            ;;
        docs/* | mkdocs.yml | requirements-docs.txt | requirements-docs-check.txt)
            hit[docs]=true
            matched=true
            ;;
        frontend/*)
            hit[frontend]=true
            matched=true
            ;;
        client/python/*)
            hit[client_python]=true
            hit[scripts]=true
            matched=true
            ;;
        client/go/*)
            hit[client_go]=true
            hit[scripts]=true
            matched=true
            ;;
        edge/*)
            hit[edge]=true
            hit[scripts]=true
            matched=true
            ;;
        discord/*)
            hit[discord]=true
            matched=true
            ;;
        firmware/*)
            hit[firmware]=true
            matched=true
            ;;
        infra/*)
            # the backend tests read the deploy scripts and the compose files. The migration and
            # lock checks run the scripts. So the backend jobs start too
            hit[infra]=true
            hit[backend]=true
            hit[scripts]=true
            matched=true
            ;;
        CHANGELOG.md)
            hit[scripts]=true
            matched=true
            ;;
        # nothing reads these
        hardware/* | assets/* | *.md | LICENSE | .gitignore | .gitattributes | .editorconfig | .prettierrc | .env.example | .markdownlint.json)
            matched=true
            ;;
    esac
    if [ "${matched}" = false ]; then
        all
    fi
done < "${list}"

emit
