#!/usr/bin/env bash
# builds the edge gateway for the architecture of the machine it runs on and writes one
# archive to the output folder. The release workflow runs it on a Linux amd64 runner and on a
# Linux arm64 runner: it does not cross-compile, because the HTTP client's TLS library has C
# code that needs the C toolchain of its own target.
#
#   bash infra/scripts/build-release-edge.sh 1.2.3 amd64 /path/to/output
#
# --locked builds exactly what Cargo.lock says. --remap-path-prefix removes the build
# machine's paths from the binary and the symbols are stripped. SOURCE_DATE_EPOCH (seconds)
# fixes the times inside the archive and defaults to the time of the last commit.
set -euo pipefail

version="${1:?version, for example 1.2.3}"
arch="${2:?architecture label for the file name: amd64 or arm64}"
out="${3:?output folder}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
epoch="${SOURCE_DATE_EPOCH:-$(git -C "${REPO_DIR}" log -1 --format=%ct)}"
os="$(uname -s | tr '[:upper:]' '[:lower:]')"
name="phaemos-edge_${version}_${os}_${arch}"

stage="$(mktemp -d)"
trap 'rm -rf "${stage}"' EXIT
mkdir -p "${stage}/${name}" "${out}"

(
    cd "${REPO_DIR}/edge"
    export CARGO_PROFILE_RELEASE_STRIP=symbols
    export RUSTFLAGS="--remap-path-prefix=${REPO_DIR}=/src --remap-path-prefix=${CARGO_HOME:-${HOME}/.cargo}=/cargo"
    cargo build --release --locked --target-dir "${stage}/target"
)
cp "${stage}/target/release/phaemos-edge" "${stage}/${name}/phaemos-edge"
cp "${REPO_DIR}/edge/LICENSE" "${stage}/${name}/LICENSE"

tar_flags=(--sort=name --owner=0 --group=0 --numeric-owner --mtime="@${epoch}")
if ! tar --version 2> /dev/null | grep -q 'GNU tar'; then
    tar_flags=()
    echo "note: not GNU tar, so this archive is not byte-for-byte reproducible" >&2
fi
(cd "${stage}" && tar "${tar_flags[@]}" -cf - "${name}" | gzip -n -9 > "${out}/${name}.tar.gz")
echo "wrote ${out}/${name}.tar.gz"
