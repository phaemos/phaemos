#!/usr/bin/env bash
# checks that the Nginx site that is INSTALLED and RUNNING is the one in this repository. It
# exits non-zero on the first thing wrong. deploy.sh runs it.
#
#   bash infra/scripts/check-nginx.sh
#
# the main test is exact: the installed file, the file Nginx actually loaded (read from
# `nginx -T`, which includes whatever else was changed) and infra/nginx/api.phaemos.com.conf
# must be the same bytes. Any edit, even one that looks harmless, fails it and so does a
# site file that was copied over by an older version. A grep for the limits cannot say what a
# changed value or a moved line means, which is why it is only the second test below.
#
# the dump needs root. The deploy user has a sudo rule for exactly `nginx -T` (see harden.sh).
# NGINX_DUMP_FILE, NGINX_SITE_AVAILABLE and NGINX_SITE_ENABLED name other files, which is how
# the script is tested.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_SITE="${NGINX_REPO_FILE:-${REPO_DIR}/infra/nginx/api.phaemos.com.conf}"
SITE_AVAILABLE="${NGINX_SITE_AVAILABLE:-/etc/nginx/sites-available/api.phaemos.com.conf}"
SITE_ENABLED="${NGINX_SITE_ENABLED:-/etc/nginx/sites-enabled/api.phaemos.com.conf}"
CORS_FILE="${NGINX_CORS_FILE:-/etc/nginx/phaemos-cors-origins.conf}"

problems=0
problem() {
    echo "WRONG in the Nginx set-up: $1" >&2
    problems=$((problems + 1))
}

# 1. the installed file is the repository's file, byte for byte and it is the one that is enabled
if [ ! -f "${SITE_AVAILABLE}" ]; then
    problem "no site file at ${SITE_AVAILABLE}"
elif ! cmp -s "${REPO_SITE}" "${SITE_AVAILABLE}"; then
    problem "${SITE_AVAILABLE} differs from infra/nginx/api.phaemos.com.conf"
fi
if [ ! -e "${SITE_ENABLED}" ]; then
    problem "the site is not enabled (no ${SITE_ENABLED})"
elif ! cmp -s "${REPO_SITE}" "${SITE_ENABLED}"; then
    problem "${SITE_ENABLED} is not the repository's site file"
fi

# the origins file is rendered from backend/.env (the API's own CORS settings). The installed
# copy must be what the current settings render, so a changed origin that was never carried to
# the proxy is found here
if [ ! -f "${CORS_FILE}" ]; then
    problem "no origins file at ${CORS_FILE}: render it with infra/scripts/render-cors.sh (Section 9)"
else
    rendered_cors="$(bash "$(dirname "${BASH_SOURCE[0]}")/render-cors.sh")" || problem "the origins in backend/.env are not valid"
    if [ "${rendered_cors}" != "$(cat "${CORS_FILE}")" ]; then
        problem "${CORS_FILE} differs from what backend/.env renders (ALLOWED_ORIGINS or CREDENTIALED_ORIGINS changed): render it again as root"
    fi
fi

# the configuration Nginx has loaded
if [ -n "${NGINX_DUMP_FILE:-}" ]; then
    dump="$(cat "${NGINX_DUMP_FILE}")"
elif [ "$(id -u)" -eq 0 ]; then
    dump="$(nginx -T 2>&1)"
else
    dump="$(sudo -n nginx -T 2>&1)" || {
        echo "cannot read the Nginx configuration: is Nginx installed and may this user run sudo nginx -T?" >&2
        exit 1
    }
fi

# 2. the loaded text of the site equals the repository file. `nginx -T` prints each file under
# a "# configuration file <path>:" line. Trailing blank lines are not compared
strip_trailing_blank() {
    awk '{ line[NR] = $0 } END { n = NR; while (n > 0 && line[n] == "") n--; for (i = 1; i <= n; i++) print line[i] }'
}
loaded="$(printf '%s\n' "${dump}" | awk -v header="# configuration file ${SITE_ENABLED}:" '
    $0 == header { on = 1; next }
    /^# configuration file / { on = 0 }
    on { print }' | strip_trailing_blank)"
expected="$(strip_trailing_blank < "${REPO_SITE}")"
if [ -z "${loaded}" ]; then
    problem "Nginx has not loaded ${SITE_ENABLED} (it is not in the running configuration)"
elif [ "${loaded}" != "${expected}" ]; then
    problem "the running configuration of the site differs from infra/nginx/api.phaemos.com.conf"
fi

# the loaded text of the origins file must be the installed one too
loaded_cors="$(printf '%s\n' "${dump}" | awk -v header="# configuration file ${CORS_FILE}:" '
    $0 == header { on = 1; next }
    /^# configuration file / { on = 0 }
    on { print }' | strip_trailing_blank)"
if [ -f "${CORS_FILE}" ] && [ "${loaded_cors}" != "$(strip_trailing_blank < "${CORS_FILE}")" ]; then
    problem "Nginx has not loaded the origins file ${CORS_FILE} as installed"
fi

# 3. the second test: the things that must hold anywhere in the running configuration, in
# case another file adds to it. Each pattern must be present once comments are stripped
# the comment-free text is made once and searched with here-strings. A `grep -q` at the end of a
# pipe quits at its first match and, under pipefail, the writer then dies of SIGPIPE and fails
# the pipeline, which reported things as missing that were there
code="$(printf '%s\n' "${dump}" | sed 's/#.*//')"
need() {
    if ! grep -Eq "$1" <<< "${code}"; then
        problem "missing from the running configuration: $2"
    fi
}
forbid() {
    if grep -Eq "$1" <<< "${code}"; then
        problem "present in the running configuration: $2"
    fi
}
need '^[[:space:]]*limit_req_zone[[:space:]].*zone=phaemos_auth:' "the tight request zone for /api/v1/auth/"
need '^[[:space:]]*limit_req_zone[[:space:]].*zone=phaemos_ingest:' "the request zone for telemetry ingest"
need '^[[:space:]]*limit_req_zone[[:space:]].*zone=phaemos_api:' "the general request zone"
need '^[[:space:]]*limit_req[[:space:]]+zone=phaemos_auth' "a limit_req that uses the auth zone"
need '^[[:space:]]*limit_req[[:space:]]+zone=phaemos_ingest' "a limit_req that uses the ingest zone"
need '^[[:space:]]*limit_req[[:space:]]+zone=phaemos_api' "a limit_req that uses the general zone"
need '^[[:space:]]*limit_req[[:space:]]+zone=phaemos_ws' "a limit_req on the live sockets"
need '^[[:space:]]*limit_conn[[:space:]]+ws_total' "the cap on all live sockets"
need '^[[:space:]]*limit_req_status[[:space:]]+429;' "429 as the answer to a limited request"
need '^[[:space:]]*client_max_body_size[[:space:]]+64k;' "the 64 kB body limit"
need 'Strict-Transport-Security.*max-age=[0-9]{7,}' "the HSTS header with a long max-age"
need '^[[:space:]]*ssl_reject_handshake[[:space:]]+on;' "the refusal of a TLS handshake for an unknown host name"
need '^[[:space:]]*server_tokens[[:space:]]+off;' "server_tokens off"
need '^[[:space:]]*proxy_hide_header[[:space:]]+Server;' "the upstream Server header being hidden"
need '^[[:space:]]*proxy_redirect[[:space:]]+http://api\.phaemos\.com/[[:space:]]+https://' "the redirect to http being rewritten to https"
need '^[[:space:]]*client_max_body_size[[:space:]]+600000;' "the 600000 byte limit of the batch ingest route"
need '^[[:space:]]*location[[:space:]]+=[[:space:]]+/api/v1/telemetry/batch' "the batch ingest location"
need '^[[:space:]]*error_page[[:space:]]+429[[:space:]]+@rate_limited;' "the JSON answer for 429"
need '^[[:space:]]*error_page[[:space:]]+413[[:space:]]+@payload_too_large;' "the JSON answer for 413"
need '^[[:space:]]*error_page[[:space:]]+502[[:space:]]+@upstream_unavailable;' "the JSON answer for 502"
need '^[[:space:]]*error_page[[:space:]]+504[[:space:]]+@upstream_timeout;' "the JSON answer for 504"
need 'Retry-After' "Retry-After on a 429"
# shellcheck disable=SC2016
need 'Access-Control-Allow-Origin[[:space:]]+\$phaemos_cors_origin' "the CORS origin taken from the generated map"
forbid 'Access-Control-Allow-Origin[[:space:]]+"?\*' "a wildcard CORS origin"
need 'X-Content-Type-Options.*nosniff' "X-Content-Type-Options: nosniff"
need 'Cache-Control.*no-store' "Cache-Control: no-store"
need '^[[:space:]]*client_body_timeout[[:space:]]' "a body timeout for slow clients"
need '^[[:space:]]*client_header_timeout[[:space:]]' "a header timeout for slow clients"
forbid '^[[:space:]]*ssl_protocols[^;]*TLSv1(\.1)?[[:space:];]' "TLS 1.0 or 1.1 enabled"
forbid '^[[:space:]]*client_max_body_size[[:space:]]+0[a-z]?;' "an unlimited body size"

if [ "${problems}" -gt 0 ]; then
    echo "the installed Nginx site is not the one in infra/nginx/api.phaemos.com.conf (${problems} problems)." >&2
    echo "install the site file again as in the deployment guide, Section 9, then reload Nginx." >&2
    exit 1
fi
echo "nginx: the installed site is the repository's file, byte for byte and it is the one running"
