# Releases

> [!IMPORTANT]
> Make the repository settings in [the workflows README](https://github.com/phaemos/phaemos/blob/main/.github/workflows/README.md#settings-a-maintainer-must-make-before-the-first-tag) before the first tag: a tag ruleset on `v*`, a main ruleset with code owner review, the `pypi` environment and the rest. The checks in the release workflow run from the workflow file at the tagged commit, so only those settings stop someone with write access from tagging a commit with the checks removed.

PHAEMOS uses tag-based releases. Every change lands in `CHANGELOG.md` under `[Unreleased]` as part of its own pull request, so a release only has to name the version. A signed tag starts the `Release` workflow, which builds everything and creates a **draft** GitHub release. A person checks the draft and publishes it.

## What a release contains

| File | What it is |
| --- | --- |
| `phaemosctl_X.Y.Z_{linux,darwin,windows}_{amd64,arm64}` | The command line tool (`.tar.gz` for Linux and macOS, `.zip` for Windows) |
| `phaemos-edge_X.Y.Z_linux_{amd64,arm64}.tar.gz` | The edge gateway |
| `phaemos_client-X.Y.Z.tar.gz` and `phaemos_client-X.Y.Z-py3-none-any.whl` | The Python client |
| `SHA256SUMS` | The SHA-256 of every file above |

Every file has build provenance attached by GitHub. The backend and the dashboard are deployed and not attached: see [deploying a release](#deploying-a-release).

## Cutting a release

1. **Bump the version** to the new `X.Y.Z` in every file that holds one. The workflow refuses the tag if any of them disagrees:
    - `client/python/pyproject.toml` (`version`)
    - `client/python/phaemos_client/__init__.py` (`__version__`)
    - `edge/Cargo.toml` (`version`) and `edge/Cargo.lock` (the `phaemos-edge` entry, which `cargo build` updates)
    - `frontend/package.json` and `frontend/package-lock.json` (the `version` lines at the top, which `npm version X.Y.Z --no-git-tag-version` sets)

    `phaemosctl` has no version in a file: the workflow writes the tag's version into the binary. The backend's version comes from the deployment's `RELEASE_VERSION` setting.
2. **Write the changelog.** Move the `[Unreleased]` entries in `CHANGELOG.md` under a new heading `## [X.Y.Z] - YYYY-MM-DD`. The text of that section becomes the release notes word for word, so read it as the notes.
3. **Merge both through one pull request.** The tag goes on the merge commit on `main`.
4. **Check locally before tagging.** From the merge commit:

    ```bash
    bash infra/scripts/check-release-version.sh X.Y.Z
    bash infra/scripts/changelog-section.sh X.Y.Z
    ```

    The first fails on any version that disagrees. The second prints the notes.
5. **Create a signed, annotated tag and push it:**

    ```bash
    git tag -s vX.Y.Z -m "phaemos vX.Y.Z"
    git push origin vX.Y.Z
    ```

    The tag must be on the commit that was merged to `main` and it must not move afterwards: the workflow refuses a tag whose commit changed after the push. GitHub must be able to verify the signature, so sign with a key that is registered as a signing key on your GitHub account. "Verified" only means that a key registered on some account signed it. The tag ruleset is what limits who may create the tag. Only final versions are released (`vX.Y.Z`). A tag with a suffix such as `-rc.1` is refused.
6. **Watch the `Release` workflow.** It refuses to continue when the tag is lightweight, not signed, not on `main` or not the same version as the packages. If it refuses, nothing is built: fix the cause and use a new tag (see [rolling back](#rolling-back)).
7. **Check the draft** (next section).
8. **Publish it.** Open the draft under Releases, read the notes and the file list and press Publish. Publishing posts the release to the community channel.

> [!IMPORTANT]
> The `Release` workflow never publishes. A tag creates a draft and a person decides. The automatic steps after publishing are the backend image on GitHub Container Registry and the optional PyPI upload, which checks the files again first.

## Checking the draft

Download the files to a new, empty folder and check them there.

1. **Checksums.** On a Mac use `shasum -a 256 -c SHA256SUMS`. On Linux use `sha256sum -c SHA256SUMS`. Every line must say `OK`. A missing file is an error and not a pass.
2. **Provenance.** For each file you mean to use (and at least one of each kind), with the commit that was merged to `main` and tagged:

    ```bash
    gh attestation verify phaemosctl_X.Y.Z_linux_amd64.tar.gz \
      --repo phaemos/phaemos \
      --signer-workflow phaemos/phaemos/.github/workflows/release.yml \
      --source-ref refs/tags/vX.Y.Z \
      --source-digest MERGE_COMMIT_SHA
    ```

    Take `MERGE_COMMIT_SHA` from the merged pull request on `main` and not from the release page. A pass means that `release.yml` built the file from that tag and that commit. Without `--source-digest` a pass would also accept a tag on a commit nobody reviewed. A failure or a different workflow, ref or commit means do not publish.
3. **Run it.** Unpack `phaemosctl` for your system and run `phaemosctl version`. It must print `X.Y.Z`. Run `phaemos-edge --version` on Linux.
4. **Notes.** They must match the `X.Y.Z` section of `CHANGELOG.md`.

The same tag built twice gives the same `phaemosctl` binary and the same Python files. A person can rebuild with `infra/scripts/build-release-go.sh` and `infra/scripts/build-release-python.sh` and compare checksums.

## Publishing the Python client to PyPI

Off by default and separate from the release workflow. `publish-pypi.yml` runs when you publish the draft and only when the repository variable `PUBLISH_PYPI` is `true`. It downloads the release's own `phaemos_client` files, checks them against `SHA256SUMS` and against their build provenance for that tag and commit and then waits for a reviewer to approve the `pypi` environment before it uploads through trusted publishing. No token is stored. The one-off set-up is in [the workflows README](https://github.com/phaemos/phaemos/blob/main/.github/workflows/README.md#publishing-to-pypi).

## The backend image

Publishing the draft also starts `publish-image.yml`. It builds the backend at the release's commit for amd64 and arm64 and pushes `ghcr.io/phaemos/phaemos-backend:X.Y.Z` (plus `X.Y` and `latest`) with an SBOM and a signed build provenance attestation. Before running a pulled image, check it:

```bash
gh attestation verify oci://ghcr.io/phaemos/phaemos-backend:X.Y.Z \
  --repo phaemos/phaemos \
  --signer-workflow phaemos/phaemos/.github/workflows/publish-image.yml \
  --source-ref refs/tags/vX.Y.Z
```

The deployment guide still builds the image on the server from a verified signed tag. The published image is an optional shortcut for anyone who prefers to pull.

## Rolling back

Work from the least permanent step to the most.

- **The workflow failed or the draft is wrong and nothing is public.** Delete the draft release. The tag stays. The workflow refuses to create a second release for a tag that already has one, so delete the draft before a rerun. Fix the cause on `main` and release the next patch version. Do not move a tag that has been pushed: people and caches may already hold it.
- **The release is published and a file is wrong.** Switch the release back to a draft (Edit then Save draft) so it stops being offered. Release the next patch version with the fix and say so in its notes.
- **The release is published and unsafe.** Switch it to a draft and release a fixed patch version as soon as it is ready. If a secret was in a file, rotate the secret first.
- **The backend image is wrong.** Delete that version under the repository's Packages, move `latest` back by publishing the fixed patch version and say so in its notes.
- **The Python client reached PyPI.** A PyPI version cannot be replaced. Yank it on PyPI (it stays installable for people who pinned it and is no longer chosen) and publish the next version.
- **A deploy of the release went wrong.** Releasing and deploying are separate, so this is a deploy rollback and not a release rollback. Follow [deployment.md](deployment.md).

Removing a tag or a published release changes what other people see. Ask the other maintainers first.

## Versioning

PHAEMOS follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html): a breaking API or schema change raises the major version, a new feature the minor version and a fix the patch version.

## Deploying a release

Releasing and deploying are separate steps. See [deployment.md](deployment.md) for the server, Vercel and DNS setup.
