#!/usr/bin/env bash
# builds the Python client's source distribution and wheel into the output folder.
#
#   bash infra/scripts/build-release-python.sh /path/to/output
#
# the build tools are installed from a hashed list (release-build-requirements.txt) and the build does not make its own isolated
# environment, so the same tag builds with the same tools. SOURCE_DATE_EPOCH (seconds) is read
# by setuptools and fixes the file times in both files. It defaults to the time of the last
# commit. The tools go into a temporary virtual environment, never the system Python.
set -euo pipefail

out="${1:?output folder}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "${REPO_DIR}" log -1 --format=%ct)}"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
python3 -m venv "${work}/venv"
# every tool is installed from a file of hashes, so a changed or substituted release file is refused
"${work}/venv/bin/pip" install --quiet --require-hashes -r "${REPO_DIR}/infra/scripts/release-build-requirements.txt"

# built from a copy, so no build/ or egg-info folder is left in the source tree
cp -R "${REPO_DIR}/client/python" "${work}/src"
rm -rf "${work}/src/build" "${work}/src/dist" "${work}/src/phaemos_client.egg-info"
mkdir -p "${out}"
(cd "${work}/src" && "${work}/venv/bin/python" -m build --no-isolation --sdist --wheel --outdir "${out}")

# setuptools writes the build time into the sdist's gzip header and into the files it generates, so
# the sdist is rewritten with fixed times, owners and order. The wheel needs no such step
"${work}/venv/bin/python" - "${out}" "${SOURCE_DATE_EPOCH}" << 'PY'
import gzip, io, pathlib, sys, tarfile

out, epoch = pathlib.Path(sys.argv[1]), int(sys.argv[2])
for path in out.glob("*.tar.gz"):
    with tarfile.open(path, "r:gz") as src:
        members = sorted(src.getmembers(), key=lambda m: m.name)
        files = {m.name: (src.extractfile(m).read() if m.isfile() else None) for m in members}
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as dst:
        for m in members:
            m.mtime, m.uid, m.gid, m.uname, m.gname = epoch, 0, 0, "", ""
            m.mode = 0o755 if m.isdir() or m.mode & 0o111 else 0o644
            m.pax_headers = {}
            dst.addfile(m, io.BytesIO(files[m.name]) if files[m.name] is not None else None)
    with open(path, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0, compresslevel=9) as gz:
            gz.write(raw.getvalue())
PY
ls -1 "${out}"
