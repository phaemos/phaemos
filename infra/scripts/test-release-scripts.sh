#!/usr/bin/env bash
# runs the release scripts against fixtures and real builds so that they do not first run on a
# real tag. CI runs it on every change to them.
#
#   bash infra/scripts/test-release-scripts.sh
#
# SKIP_EDGE=1 leaves out the edge gateway build, which needs Rust. SKIP_BUILDS=1 leaves out
# every build and runs only the fixture tests.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
fail() {
    echo "FAIL: $*" >&2
    exit 1
}

# 1. the checksum file. The old form raced, so it is run many times and checked every time
echo "== checksums: 200 runs"
mkdir "${work}/sums"
for n in 1 2 3 4 5 6; do head -c "$((n * 1000))" /dev/urandom > "${work}/sums/file-${n}.bin"; done
for run in $(seq 1 200); do
    bash "${HERE}/write-checksums.sh" "${work}/sums"
    lines="$(wc -l < "${work}/sums/SHA256SUMS" | tr -d ' ')"
    [ "${lines}" = "6" ] || fail "run ${run}: SHA256SUMS has ${lines} lines, wanted 6"
    ! grep -q ' SHA256SUMS$' "${work}/sums/SHA256SUMS" || fail "run ${run}: SHA256SUMS lists itself"
done
echo "ok    200 runs gave a correct list every time"

# 2. the version check, against a fixture that has the files in their real formats
echo "== check-release-version.sh"
fx="${work}/fixture"
mkdir -p "${fx}/client/python/phaemos_client" "${fx}/edge" "${fx}/frontend"
write_fixture() {
    printf '[project]\nname = "phaemos-client"\nversion = "%s"\n' "$1" > "${fx}/client/python/pyproject.toml"
    printf '__version__ = "%s"\n' "$1" > "${fx}/client/python/phaemos_client/__init__.py"
    printf '[package]\nname = "phaemos-edge"\nversion = "%s"\n' "$1" > "${fx}/edge/Cargo.toml"
    printf '[[package]]\nname = "phaemos-edge"\nversion = "%s"\n' "$1" > "${fx}/edge/Cargo.lock"
    printf '{\n  "name": "x",\n  "version": "%s"\n}\n' "$1" > "${fx}/frontend/package.json"
    printf '{\n  "name": "x",\n  "version": "%s",\n  "packages": {\n    "": {\n      "name": "x",\n      "version": "%s"\n    }\n  }\n}\n' "$1" "$1" > "${fx}/frontend/package-lock.json"
    printf '# Changelog\n\n## [Unreleased]\n\nnext\n\n## [%s] - 2026-01-02\n\nNotes for %s.\n\n### Added\n\n- a thing\n\n---\n\n## [0.0.1] - 2025-01-01\n\nold\n' "$1" "$1" > "${fx}/CHANGELOG.md"
}
write_fixture 1.2.3
RELEASE_REPO_DIR="${fx}" bash "${HERE}/check-release-version.sh" 1.2.3 > /dev/null || fail "a matching fixture was refused"
echo "ok    matching versions pass"
sed -i.bak 's/1.2.3/1.2.2/' "${fx}/edge/Cargo.lock" && rm "${fx}/edge/Cargo.lock.bak"
if out="$(RELEASE_REPO_DIR="${fx}" bash "${HERE}/check-release-version.sh" 1.2.3 2>&1)"; then fail "a mismatch was accepted"; fi
grep -q 'WRONG edge/Cargo.lock' <<< "${out}" || fail "the refusal does not name edge/Cargo.lock: ${out}"
echo "ok    a mismatch is refused and names the file"
if RELEASE_REPO_DIR="${fx}" bash "${HERE}/check-release-version.sh" 1.2.3-rc.1 > /dev/null 2>&1; then fail "a pre-release version was accepted"; fi
echo "ok    a pre-release version is refused"

# 3. the release notes
echo "== changelog-section.sh"
write_fixture 1.2.3
notes="$(bash "${HERE}/changelog-section.sh" 1.2.3 "${fx}/CHANGELOG.md")"
grep -q '^Notes for 1.2.3.$' <<< "${notes}" || fail "the notes lack the section text"
! grep -q 'old\|## \[' <<< "${notes}" || fail "the notes run into the next section"
if bash "${HERE}/changelog-section.sh" 9.9.9 "${fx}/CHANGELOG.md" > /dev/null 2>&1; then fail "a missing section was accepted"; fi
echo "ok    the section is cut out and a missing one is refused"

if [ "${SKIP_BUILDS:-}" = "1" ]; then
    echo "builds skipped"
    exit 0
fi

# 4. the builds, with a fixed time so two builds can be compared
export SOURCE_DATE_EPOCH=1763800000
echo "== build-release-go.sh"
bash "${HERE}/build-release-go.sh" 9.8.7 linux amd64 "${work}/out" > /dev/null
bash "${HERE}/build-release-go.sh" 9.8.7 windows arm64 "${work}/out" > /dev/null
[ -f "${work}/out/phaemosctl_9.8.7_linux_amd64.tar.gz" ] || fail "no linux archive"
[ -f "${work}/out/phaemosctl_9.8.7_windows_arm64.zip" ] || fail "no windows archive"
if [ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ]; then
    mkdir "${work}/unpack"
    tar -xzf "${work}/out/phaemosctl_9.8.7_linux_amd64.tar.gz" -C "${work}/unpack"
    "${work}/unpack/phaemosctl_9.8.7_linux_amd64/phaemosctl" version | grep -q '9.8.7' || fail "the binary does not carry the stamped version"
    bash "${HERE}/build-release-go.sh" 9.8.7 linux amd64 "${work}/out2" > /dev/null
    cmp "${work}/out/phaemosctl_9.8.7_linux_amd64.tar.gz" "${work}/out2/phaemosctl_9.8.7_linux_amd64.tar.gz" || fail "the linux archive is not reproducible"
    echo "ok    the linux archive is reproducible and prints the stamped version"
else
    echo "ok    both archives built (version and reproducibility are checked on a Linux amd64 host)"
fi

echo "== build-release-python.sh"
bash "${HERE}/build-release-python.sh" "${work}/py1" > /dev/null
bash "${HERE}/build-release-python.sh" "${work}/py2" > /dev/null
for f in "${work}"/py1/*; do
    cmp "${f}" "${work}/py2/$(basename "${f}")" || fail "$(basename "${f}") is not reproducible"
done
[ "$(find "${work}/py1" -type f | wc -l | tr -d ' ')" = "2" ] || fail "wanted an sdist and a wheel"
echo "ok    sdist and wheel built twice with identical bytes"

if [ "${SKIP_EDGE:-}" != "1" ]; then
    echo "== build-release-edge.sh"
    bash "${HERE}/build-release-edge.sh" 9.8.7 "$(uname -m)" "${work}/edge" > /dev/null
    [ -n "$(find "${work}/edge" -name 'phaemos-edge_9.8.7_*.tar.gz')" ] || fail "no edge archive"
    echo "ok    the edge gateway built"
fi
echo "release scripts passed"
