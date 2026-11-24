#!/usr/bin/env bash
# builds phaemosctl for one operating system and architecture and writes one archive to the
# output folder. The release workflow runs it once for each of the six targets.
#
#   bash infra/scripts/build-release-go.sh 1.2.3 linux arm64 /path/to/output
#
# the build is meant to give the same bytes every time for the same source and version:
#   -trimpath        removes the build machine's file paths from the binary
#   -buildvcs=false  leaves out the git state, which differs between a checkout and an export
#   -buildid=        leaves out the build id, which is a hash of the build inputs and paths
#   -s -w            leaves out the symbol table and the debug information
#   CGO_ENABLED=0    no C library, so the binary is static and one runner can build every target
# the version is written into the binary with -X, the way internal/cli/app.go documents.
# SOURCE_DATE_EPOCH (seconds) fixes the times inside the archive. It defaults to the time of
# the last commit.
set -euo pipefail

version="${1:?version, for example 1.2.3}"
goos="${2:?operating system: linux, darwin or windows}"
goarch="${3:?architecture: amd64 or arm64}"
out="${4:?output folder}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
epoch="${SOURCE_DATE_EPOCH:-$(git -C "${REPO_DIR}" log -1 --format=%ct)}"
name="phaemosctl_${version}_${goos}_${goarch}"
binary="phaemosctl"
[ "${goos}" = "windows" ] && binary="phaemosctl.exe"

stage="$(mktemp -d)"
trap 'rm -rf "${stage}"' EXIT
mkdir -p "${stage}/${name}" "${out}"

(
    cd "${REPO_DIR}/client/go"
    CGO_ENABLED=0 GOOS="${goos}" GOARCH="${goarch}" go build \
        -trimpath -buildvcs=false \
        -ldflags "-s -w -buildid= -X github.com/phaemos/client/go/internal/cli.Version=${version}" \
        -o "${stage}/${name}/${binary}" ./cmd/phaemosctl
)
cp "${REPO_DIR}/LICENSE" "${stage}/${name}/LICENSE"

# fixed order, owner and times and no file name or time in the gzip header. The archive
# is the same bytes on every run
if [ "${goos}" = "windows" ]; then
    archive="${out}/${name}.zip"
    rm -f "${archive}"
    # GNU date takes -d and BSD date takes -r, so a developer machine can try the script too
    stamp="$(date -u -d "@${epoch}" +%Y%m%d%H%M.%S 2> /dev/null || date -u -r "${epoch}" +%Y%m%d%H%M.%S)"
    (cd "${stage}" && find "${name}" -exec touch -t "${stamp}" {} + && find "${name}" -type f | LC_ALL=C sort | zip -q -X -@ "${archive}")
else
    tar_flags=(--sort=name --owner=0 --group=0 --numeric-owner --mtime="@${epoch}")
    # BSD tar (macOS) has no --sort: a developer machine uses it only to try the script
    if ! tar --version 2> /dev/null | grep -q 'GNU tar'; then
        tar_flags=()
        echo "note: not GNU tar, so this archive is not byte-for-byte reproducible" >&2
    fi
    archive="${out}/${name}.tar.gz"
    (cd "${stage}" && tar "${tar_flags[@]}" -cf - "${name}" | gzip -n -9 > "${archive}")
fi
echo "wrote ${archive}"
