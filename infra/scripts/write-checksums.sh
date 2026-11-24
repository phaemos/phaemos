#!/usr/bin/env bash
# writes SHA256SUMS for every file in a folder, in the format `sha256sum -c` reads, sorted by
# name and checks the result.
#
#   bash infra/scripts/write-checksums.sh /path/to/folder
#
# the list is written outside the folder and moved in afterwards. Writing it straight into the
# folder races: the shell can create the output file before the file list is expanded, so the
# list would name itself as an empty file and the check would fail on some runs and not others.
set -euo pipefail

dir="${1:?folder}"
[ -d "${dir}" ] || { echo "not a folder: ${dir}" >&2; exit 1; }

tool=(sha256sum)
command -v sha256sum > /dev/null || tool=(shasum -a 256)

tmp="$(mktemp)"
trap 'rm -f "${tmp}"' EXIT
(
    cd "${dir}"
    rm -f SHA256SUMS
    files=(*)
    [ -e "${files[0]}" ] || { echo "no files in ${dir}" >&2; exit 1; }
    "${tool[@]}" -- "${files[@]}" | LC_ALL=C sort -k2 > "${tmp}"
)
mv "${tmp}" "${dir}/SHA256SUMS"
(cd "${dir}" && "${tool[@]}" -c SHA256SUMS > /dev/null)
