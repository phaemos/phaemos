# Workflows

> [!WARNING]
> The jobs added in this revision have never run on a hosted runner. They were checked with
> `actionlint` and by running each command on a developer machine (see "What has not run yet"
> below). Expect to fix small things the first time they run and read the first runs with care.

## Every workflow

| Workflow | Runs on | What it does | Token rights | Secrets and variables it reads |
| --- | --- | --- | --- | --- |
| [`ci.yml`](ci.yml) | Push to `main`, every pull request to `main` | Lints, tests and builds every part of the repository. Parts a pull request does not touch are skipped. It also runs the secret scan, the release and gate script tests and the docs build. One job, `CI passed`, needs all the others. A last job, `CI alert`, runs only when a job failed on a push to `main` of this repository and tells the staff channel on Discord | `contents: read` on each job and nothing else | secret `DISCORD_WEBHOOK_CI_ALERTS` in the `community` environment, read by `CI alert` only |
| [`audit.yml`](audit.yml) | Called by `ci.yml`, weekly on Monday 06:00 UTC, manually | Dependency audits for Python, Node, Rust and Go | `contents: read` | none |
| [`codeql.yml`](codeql.yml) | Push to `main`, every pull request, weekly on Monday 08:00 UTC, manually | CodeQL static analysis of Python and JavaScript | `contents: read`, `actions: read` and `security-events: write` on the one job | none |
| [`gitleaks-scan.yml`](gitleaks-scan.yml) | Called by `ci.yml`, weekly on Monday 07:00 UTC, manually | Scans every commit of a change (the whole history on the weekly run) and then the working tree for committed secrets | `contents: read` | none |
| [`markdownlint.yml`](markdownlint.yml) | Push to `main`, every pull request, manually | Lints every markdown file against [`.markdownlint.json`](../../.markdownlint.json) | `contents: read` | none |
| [`release.yml`](release.yml) | A pushed tag matching `v*.*.*`, never a fork, never a pull request | Verifies the tag, builds `phaemosctl`, the edge gateway and the Python client, writes checksums, attaches build provenance and creates a **draft** GitHub release. It publishes nothing | `contents: read` by default. `contents: write` only on the draft job. `id-token: write` and `attestations: write` only on the checksums job | none |
| [`publish-pypi.yml`](publish-pypi.yml) | A release is **published** by a person | Downloads the release's Python files, verifies their checksums and build provenance and uploads them to PyPI through trusted publishing | `contents: read` and `attestations: read` on the verify job. `id-token: write` only on the upload job | variable `PUBLISH_PYPI` and the environment `pypi` (both new and both optional) |
| [`deploy.yml`](deploy.yml) | After a `CI` run completes | Triggers the backend deploy hook on Render when the run was a push to `main` in this repository and passed. A pull request from a fork never starts it, whatever its branch is called | none (`permissions: {}`) | secret `RENDER_DEPLOY_HOOK_URL` |
| [`split.yml`](split.yml) | Push to `main`, manually | Publishes `backend`, `frontend`, `firmware`, `hardware`, `infra`, `client`, `edge` and `discord` to their own read-only repositories | `contents: read` | secret `SPLIT_TOKEN` |
| [`discord-relay.yml`](discord-relay.yml) | Releases, issues, discussions, push to `main`, manually | Posts to the community Discord channels | `contents: read` and `actions: read` | secrets `DISCORD_WEBHOOK_ANNOUNCEMENTS`, `DISCORD_WEBHOOK_RELEASES`, `DISCORD_WEBHOOK_FEED`, `DISCORD_WEBHOOK_IDEAS`, `DISCORD_WEBHOOK_RESEARCH`, `DISCORD_TAG_IDEAS` and `DISCORD_TAG_RESEARCH` in the `community` environment |
| [`biweekly-security-issue.yml`](biweekly-security-issue.yml) | Weekly (acts every second week), manually | Audits the dashboard's production dependencies and opens or updates an issue | `contents: read` and `issues: write` | none (the built-in token) |

`split.yml` needs a `SPLIT_TOKEN` secret: a fine-grained token with contents write access to the eight component repositories. Without it the workflow succeeds and publishes nothing.

None of these workflows uses `pull_request_target`. A pull request from a fork runs `ci.yml` (which calls the secret scan and the audits), `codeql.yml` and `markdownlint.yml` with a read-only token and no secrets.

### Rules the workflows follow

`discord-relay.yml` is kept as its owner wrote it. Every other workflow follows all of these.

- `permissions` at the top is `{}` or `contents: read`. A job that needs more asks for it on the job.
- `concurrency` cancels a superseded run on a pull request. A run on `main` and a release run are never cancelled.
- Every job has a `timeout-minutes`.
- A title, branch name or body never appears inside a `run:` script. A value from the event reaches a script only through an environment variable and a tag name is checked against a pattern first.
- Checkout steps use `persist-credentials: false` unless the job pushes.
- `ci.yml` has no schedule and no manual trigger. `deploy.yml` starts after every completed `CI` run so a weekly run of `CI` would start a deploy. The weekly work is in `audit.yml` and `gitleaks-scan.yml`.
- A workflow file cannot defend itself against being edited by someone who can push to the repository. The settings in the next section are the defence.

## Settings a maintainer must make before the first tag

Nothing in a workflow file can stop someone with write access from pushing a commit with the checks removed and tagging it. The release would still run as `release.yml` at that tag. Its attestation would still say so. These repository settings are the defence and none of them is in a file. Make them before the first tag and check them again after any change of maintainers.

1. **Tag ruleset.** Settings, Rules, Rulesets, New tag ruleset. Target `refs/tags/v*`. Enforcement active. Add the named maintainers (a team or a list of people) as the only bypass actors. Switch on "Restrict creations", "Restrict updates" and "Restrict deletions". Nobody else can then create, move or delete a release tag.
2. **Main ruleset.** New branch ruleset targeting the default branch. Switch on: require a pull request before merging, require review from code owners, require status checks to pass with `CI passed`, `Analyse (python)`, `Analyse (javascript)` and `Lint markdown files` added (the secret scan is already inside `CI passed`), require branches to be up to date, block force pushes and block deletions. Do not add bypass actors for a day to day account.
3. **Code owners.** `.github/CODEOWNERS` lists `.github/`, `infra/scripts/`, `.gitleaks.toml` and `.gitleaksignore` on their own lines with the same owner as the `*` line. GitHub applies the last matching line, so every line must name an owner that resolves: a team that does not exist would leave the path with no owner. A team can replace the owner later once it exists and has write access to the repository. A pull request can edit `ci.yml` or `changed-areas.sh` to report green, so review of those paths by a person is the only check on them.
4. **The `pypi` environment** (only when `PUBLISH_PYPI` is going to be switched on). Settings, Environments, New environment `pypi`. Required reviewers: the named maintainers. Switch on "Prevent self-review". Deployment branches and tags: "Selected branches and tags" with the tag rule `v*` and nothing else. Create it before the variable: if the variable is set first GitHub creates the environment with no protection.
5. **Default token.** Settings, Actions, General, Workflow permissions: "Read repository contents and packages permissions". Leave "Allow GitHub Actions to create and approve pull requests" off.
6. **Allowed actions.** Settings, Actions, General: the option that allows the owner's actions plus selected ones, with the actions in the pin table below added to the list (`actions/*`, `github/codeql-action/*`, `DavidAnson/markdownlint-cli2-action@*` and `pypa/gh-action-pypi-publish@*`). Tick "Require actions to be pinned to a full-length commit SHA".
7. **Outside contributors.** Settings, Actions, General, "Fork pull request workflows from outside collaborators": "Require approval for all outside collaborators". A first run from a stranger then waits for a maintainer.
8. **The `community` environment** (used by `discord-relay.yml`). No required reviewers, because every comment from a stranger would queue for approval. Do not limit deployment branches to `main`, because release events run on the tag. Keep its webhook and tag secrets there and nowhere else.
9. **Required checks.** The one that carries the gate is `CI passed`. Add it as a required check from the **GitHub Actions** app (the "source" of the check), so another app cannot report a status with the same name. Also mark `Analyse (python)`, `Analyse (javascript)` and `Lint markdown files` required. They are separate workflows and are not inside `CI passed`. If branch protection still lists the old per-job names (`Backend lint (ruff)` and so on) remove them.
10. **Immutable releases.** Settings, General, Releases: switch on immutable releases. A published release then keeps its files and its tag, so a published release cannot be edited or have its tag moved.

Notes on these settings:

- Some of them (the default token, the actions allow-list, the outside contributor approval and rulesets) can be set at organisation level. In the repository they then show as greyed out or inherited. Check the organisation's settings and make sure the values above are the ones in force.
- "Require review from code owners" with a single owner blocks that owner's own pull requests, because an author cannot approve their own pull request. Until a second maintainer exists do one of these: add a second maintainer to the owner line. Or limit the code owner rule to the protected paths (`.github/`, `infra/scripts/` and the scanner files) in a separate ruleset and give the one maintainer a bypass on that ruleset. A bypass is logged in the audit log, so use it only for those paths and read the log.
- The checks named in the main ruleset must have run at least once before GitHub lets you pick them from the list.

### What "verified" on a tag does and does not mean

GitHub shows a tag as verified when its signature matches a signing key registered on some GitHub account. It does not say that the account belongs to a maintainer. `release.yml` cannot tell the difference. The tag ruleset is what limits who can create a tag. Verified plus the ruleset is the check. Verified alone is not.

## What `ci.yml` checks

| Job | Runs when | What it checks |
| --- | --- | --- |
| `workflows` | always | `actionlint` on every workflow (with shellcheck on the `run:` blocks) and [`check-action-pins.sh`](../../infra/scripts/check-action-pins.sh) |
| `backend-lint` and `backend-test` | `backend/`, `docs/openapi.json` or `docs/api-routes.md` changed | `ruff` and `pytest` against a throwaway PostgreSQL |
| `backend-lock` | same | `infra/scripts/lock-requirements.sh --check`: `backend/requirements.lock` still matches `requirements.txt` |
| `backend-extras` | same | `make openapi` gives the committed `docs/openapi.json` and `docs/api-routes.md`. A first install (tables then migrations) works. A second run of the migrations applies nothing and leaves the schema unchanged. The route class table test passes |
| `frontend-check` | `frontend/` changed | ESLint, unit tests and a production build |
| `client-python`, `client-go`, `edge` and `discord` | their folder changed | as before |
| `firmware` | `firmware/` changed | `make firmware-check` (every PlatformIO environment plus the host tests of the hub and the Black Pill) and the MicroPython node's tests |
| `infra` | `infra/` changed | shellcheck on `infra/scripts`, `bash -n` on each script and the deploy guard tests |
| `secret-scan` | always | gitleaks over every commit of the change and then the working tree, so a secret added in one commit and removed in the next is still found |
| `scripts` | `infra/`, `CHANGELOG.md`, `client/` or `edge/` changed | the gate's tests with crafted commits and the release scripts: the checksum step 200 times, the version check and release notes against fixtures and real builds of `phaemosctl`, the Python client and the edge gateway |
| `docs` | `docs/`, `mkdocs.yml` or the backend changed | `make openapi` and then `mkdocs build --strict`. The browser check `docs/overrides/check_site.py` is not run here because it needs a Chromium that nothing in the repository pins. Run it locally as `docs/README.md` says |
| `audit` | the language's folder changed | see the next section |
| `ci-alert` | a job failed on a push to `main` of `phaemos/phaemos` | runs `discord/relay/post.py --ci-failure`. The alert holds the run number and a link and nothing from a log. It never runs for a pull request or a fork |
| `CI passed` | always | the single required check |

`go.mod` says `go 1.24` and the workflows build with Go 1.27.4. The two differ on purpose: the `go` line is the oldest language version the module may be built with and a build with a newer toolchain is allowed. The release and the audit use a patched toolchain because the standard library is compiled into the binary and the 1.24 line has known vulnerabilities. The module does not need 1.27 to compile.

The gitleaks binary in `gitleaks-scan.yml` is pinned to a version and to the SHA-256 from that release's own checksums file. A download that does not match stops the job. Change the two together.

[`changed-areas.sh`](../../infra/scripts/changed-areas.sh) decides which parts run on a pull request. It reads null-separated paths with renames split into a delete and an add. The backend jobs start for `backend/`, all of `infra/` and the root `docker-compose.yml` because the backend tests read them. A path that matches no rule runs everything. A change under `.github/`, to the `Makefile` or to the gate itself runs everything. A push to `main` runs everything. [`test-changed-areas.sh`](../../infra/scripts/test-changed-areas.sh) checks these rules with crafted commits (a rename out of an area, a non-ASCII path, the root compose file and the deploy scripts).

Nginx: `infra/scripts/check-nginx.sh` compares the installed site with the repository's file and needs the real server, so CI cannot run it as it is. The deploy guard tests run it against a throwaway site and a throwaway dump of the configuration. Shellcheck reads it too.

### What the secret scan can and cannot do

The scanner's settings are read from fixed paths, `.github/gitleaks.toml` and `.github/gitleaksignore`. For a pull request they come from the base branch and not from the change. Adding or editing `.gitleaks.toml` or `.gitleaksignore` in a pull request does not change the scan (the CODEOWNERS lines for them are a second guard). Without a file at the base the scanner's default rules apply. To allow a known harmless finding a maintainer adds it to `.github/gitleaksignore` in its own reviewed pull request.

A comment in the source that tells the scanner to skip its own line (the word gitleaks, a colon and the word allow) works on that line and no option turns it off. [`run-gitleaks.sh`](../../infra/scripts/run-gitleaks.sh) therefore fails a pull request that adds one. A reviewer should still search the change for it, in files of every kind. The check covers added lines of the pull request. It cannot see one that is already in the history.

The scan reads only what is committed. It does not find a secret that is split across lines, encoded or held outside the repository.

## Dependency audits and what fails the build

| Language | Tool (pinned) | What it reads | What fails the build |
| --- | --- | --- | --- |
| Python | `pip-audit` 2.10.1 | `backend/requirements.lock`, which is what the production image installs | Any known vulnerability. `pip-audit` has no severity filter. The lock holds only what ships so each finding is one to read the same day |
| Node | `npm audit` (the npm that ships with Node 24) | `frontend/package-lock.json` and `discord/worker/package-lock.json`, production packages only | High and critical. Packages that only build or test the code are not in the gate. Moderate and low findings reach the issue that `biweekly-security-issue.yml` opens |
| Rust | `cargo-audit` 0.23.0 | `edge/Cargo.lock` | Any advisory that names a vulnerability. Warnings (unmaintained or yanked crates) are printed and do not fail |
| Go | `govulncheck` 1.10.0 | `client/go` | Only a vulnerable function the code can actually reach, which is what `govulncheck` reports. The audit and the release build use Go 1.27.4 and not the 1.24 that `go.mod` names. The standard library is compiled into the binary and the 1.24 line has known vulnerabilities |

The reasoning: a gate that fails on every low finding gets ignored or switched off. A gate that fails on nothing is decoration. We fail on what is exploitable (Go), on what ships (Python and Rust) and on high and critical (Node). The weekly run in `audit.yml` finds new advisories in code nobody has touched. A finding in a package the code cannot reach can be set aside in the tool's own ignore list with a comment that says why and when to look again.

## Releases

[`docs/releases.md`](../../docs/releases.md) says how a person cuts one. In short: a signed annotated tag `vX.Y.Z` on `main` starts `release.yml` which creates a draft. A person checks it and publishes it.

What `verify` refuses:

- a tag that now points at a different commit from the one the run was started for (a moved tag). Every job builds that one commit

- a tag that is not `vX.Y.Z` (pre-release suffixes are not released yet because Python and Cargo write them differently)
- a lightweight tag or a tag whose signature GitHub does not verify (the signing key must be registered as a signing key on the tagger's GitHub account)
- a tag on a commit that is not on `main`
- a version that differs between the tag and any of these files (the job lists each file that disagrees and what it holds): `client/python/pyproject.toml`, `client/python/phaemos_client/__init__.py`, `edge/Cargo.toml`, `edge/Cargo.lock` (the `phaemos-edge` entry), `frontend/package.json` and `frontend/package-lock.json`
- a `CHANGELOG.md` with no `## [X.Y.Z] - YYYY-MM-DD` section

What it builds:

| File | Notes |
| --- | --- |
| `phaemosctl_X.Y.Z_{linux,darwin,windows}_{amd64,arm64}` (`.tar.gz`, `.zip` for Windows) | One runner cross-compiles all six. `CGO_ENABLED=0`, `-trimpath`, `-buildvcs=false`, `-ldflags "-s -w -buildid= -X .../cli.Version=X.Y.Z"` and a Go toolchain pinned to 1.27.4 |
| `phaemos-edge_X.Y.Z_linux_{amd64,arm64}.tar.gz` | Built natively on an amd64 and an arm64 runner and not cross-compiled, because the HTTP client's TLS library has C code that needs the matching toolchain. The amd64 runner is Ubuntu 22.04 to keep the glibc requirement low |
| `phaemos_client-X.Y.Z.tar.gz` and `phaemos_client-X.Y.Z-py3-none-any.whl` | Built with pinned `build` and `setuptools` |
| `SHA256SUMS` | One line for every file above, sorted by name. It is written outside the folder and moved in, because writing it in place races |

The edge gateway is not built for macOS or Windows. It builds natively on macOS arm64 on a developer machine. The spool uses Unix file modes and nobody has run the gateway on either system. A cross-compile for Windows was not possible on the machine that wrote the workflow. Add them when someone has run the gateway there.

Every archive is written with a fixed order, owner and time so the same tag gives the same files. The macOS `phaemosctl` binary and both Python files were built twice on a developer machine and came out identical. The Linux and Windows archives were not compared because they need GNU tar and zip on the runner.

### Provenance

`actions/attest-build-provenance` signs a statement for every file named in `SHA256SUMS` through GitHub's own Sigstore instance. Check a file with the strict command in `docs/releases.md`: `gh attestation verify FILE --repo phaemos/phaemos --signer-workflow phaemos/phaemos/.github/workflows/release.yml --source-ref refs/tags/vX.Y.Z --source-digest COMMIT`. Without `--source-digest` a pass only says that some `release.yml` built it. It does not say that the commit is the one that was reviewed.

### Publishing to PyPI

`release.yml` publishes nothing. [`publish-pypi.yml`](publish-pypi.yml) runs when a person publishes the draft release. It downloads the release's own Python files, checks them against `SHA256SUMS`, checks their build provenance against the tag and commit and then uploads them in the protected `pypi` environment through trusted publishing. No token is stored anywhere. It does nothing unless the repository variable `PUBLISH_PYPI` is `true`. Before turning it on a person must:

1. Create the project `phaemos-client` on PyPI (or add a pending publisher for it).
2. On PyPI add a trusted publisher: the owner and repository of this repository, the workflow `publish-pypi.yml` and the environment `pypi`.
3. Create the `pypi` environment with the protection in step 4 of "Settings a maintainer must make before the first tag".
4. Set the repository variable `PUBLISH_PYPI` to `true`.

A package version can be uploaded to PyPI once only. A bad release is yanked and the next version fixed. It is never replaced.

## Secrets, variables and environments

No secret, token, key or webhook address is written in any file here. Workflows name them only.

| Name | Kind | Used by | What it is for | New in this revision |
| --- | --- | --- | --- | --- |
| `RENDER_DEPLOY_HOOK_URL` | secret | `deploy.yml` | Address that starts a Render deploy | no |
| `SPLIT_TOKEN` | secret | `split.yml` | Fine-grained token that may write to the eight component repositories | no |
| `DISCORD_WEBHOOK_ANNOUNCEMENTS`, `DISCORD_WEBHOOK_RELEASES`, `DISCORD_WEBHOOK_FEED`, `DISCORD_WEBHOOK_IDEAS` and `DISCORD_WEBHOOK_RESEARCH` | secrets in the `community` environment | `discord-relay.yml` | Where each kind of post goes | no |
| `DISCORD_TAG_IDEAS` and `DISCORD_TAG_RESEARCH` | secrets in the `community` environment | `discord-relay.yml` | The id of the From GitHub tag in each forum, which refuses a post without one | yes |
| `DISCORD_WEBHOOK_CI_ALERTS` | secret in the `community` environment | `ci.yml` (`ci-alert`) | Where the alert for a failed run on `main` goes | yes |
| `PUBLISH_PYPI` | repository variable | `publish-pypi.yml` | Switches the PyPI upload on when it is `true` | yes |
| `pypi` | environment | `publish-pypi.yml` | Holds the trusted publisher's identity and an optional required reviewer | yes |

`release.yml`, `publish-pypi.yml` and `ci.yml` use only the built-in `GITHUB_TOKEN` (and PyPI's trusted publishing for the upload).

## Pinning actions

Every `uses:` line points at a full 40 character commit with the version in a trailing comment:

```yaml
uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

A tag such as `v4` can be moved by whoever controls the action's repository so a moved tag would run new code with our token. A commit cannot be moved. [`infra/scripts/check-action-pins.sh`](../../infra/scripts/check-action-pins.sh) fails the `workflows` job when a line is not pinned or has no version comment. Local actions (`./path`) and images pinned by digest are allowed.

| Action | Version | Commit |
| --- | --- | --- |
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-python` | v7.1.0 | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` |
| `actions/setup-node` | v7.1.0 | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| `actions/setup-go` | v7.0.0 | `b7ad1dad31e06c5925ef5d2fc7ad053ef454303e` |
| `actions/cache` | v6.1.0 | `55cc8345863c7cc4c66a329aec7e433d2d1c52a9` |
| `actions/upload-artifact` | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| `actions/download-artifact` | v8.0.2 | `9000827ccba6bdab643e8b6fd33ac0654aef8333` |
| `actions/attest-build-provenance` | v4.2.2 | `4d101475d8b20a2381f78447822ac1eab6504dd8` |
| `github/codeql-action` (`init`, `autobuild` and `analyze`) | v4.39.4 | `1bd86f2fdb4b86187fa4059f16f31a3202acc9ea` |
| `DavidAnson/markdownlint-cli2-action` | v25.0.0 | `696eb3f2509270d7b882d2aa68347bc676e7af34` |
| `pypa/gh-action-pypi-publish` | v1.14.3 | `7245906fb61fa33a13554f9d5fb856fe61758086` |

### Updating a pin

1. Find the tag you want on the action's releases page.
2. Look up the commit it points to. An annotated tag points at a tag object so follow it to the commit:

    ```bash
    gh api repos/OWNER/REPO/git/ref/tags/TAG --jq '.object.type + " " + .object.sha'
    # if the type is "tag", follow it:
    gh api repos/OWNER/REPO/git/tags/SHA --jq .object.sha
    ```

3. Replace the 40 character commit and the version comment everywhere the action is used (`grep -rn "OWNER/REPO@" .github`) and update the table above.
4. Run `bash infra/scripts/check-action-pins.sh` and `actionlint`.

### What else is pinned and how

| What | How it is pinned |
| --- | --- |
| Actions | Full commit and a version comment (above) |
| Python build tools in the release (`build`, `setuptools`, `packaging`, `pyproject-hooks`) | A hashed file, `infra/scripts/release-build-requirements.txt`, installed with `--require-hashes` |
| Rust compiler for the edge gateway | `edge/rust-toolchain.toml` (1.99.1) for the release, CI and local builds |
| Go toolchain for the release, audit and script tests | Exact version 1.27.4 in the workflow |
| `cargo-audit`, `govulncheck`, `pip-audit`, `ruff`, `pytest`, `platformio`, `actionlint-py`, `shellcheck-py`, `pip-tools` | Exact version, no hashes. `go install` is checked by `go.sum` and the Go checksum database and `cargo install --locked` uses the crate's lock file |
| gitleaks | Version and SHA-256 of the archive, checked before it runs |
| PostgreSQL in CI | Image tag and digest |
| Backend runtime | `backend/requirements.lock` with hashes |
| Docs tools | Exact versions in `requirements-docs.txt`, no hashes |
| Not pinned | `client/python` dependency ranges (`.[dev]` and `setuptools>=80`) in the client's own CI job, the Python and Node minor versions the setup actions pick and the runner images. Nothing in the release path depends on them except the Python minor version, which only changes the file times and metadata the build tool writes |

Update a tool the same way in one pull request that says why.

## What has not run yet

- Every job in `ci.yml` that did not exist before: `changes`, `workflows`, `backend-lock`, `backend-extras`, `firmware`, `infra`, `secret-scan`, `scripts`, `docs` and `CI passed`.
- The whole of `audit.yml`, `release.yml` and `publish-pypi.yml`, including the attestation, the draft release and the PyPI upload.
- The edge gateway build on the Linux arm64 runner.

On a developer machine each command in them was run and the results are in the infrastructure journal. A developer machine cannot show how the jobs behave on the hosted runner image, how long the first PlatformIO download takes (the cache is cold the first time) or how long `cargo install cargo-audit` takes (a few minutes the first time and cached after).

Known failures the first runs will show because the code they check is not ready:

- `backend-extras` fails until `docs/openapi.json` and `docs/api-routes.md` are generated and committed. It also fails until the two routes under `/api/v1/ml` that the route class test names are classified in its table.

## First push checklist

- [ ] The settings above exist before the first tag: the tag ruleset, the main ruleset, the code owner team, the `pypi` environment, the read-only default token, the actions allow-list, approval for outside contributors and the `community` environment rules.
- [ ] `backend-extras` is red as expected (the OpenAPI files are not committed and two `/ml` routes are unclassified). Fix it or nothing can merge.
- [ ] Every PlatformIO, `cargo-audit` and PostgreSQL pull finishes inside its timeout. Record the run times in the cost section.
- [ ] `ubuntu-22.04-arm` has cargo and the edge build works there.
- [ ] The Linux archives build twice to the same bytes (the `scripts` job checks the `phaemosctl` one on a Linux amd64 runner).
- [ ] The checksum step passes on the runner.
- [ ] `subject-checksums` gives one attestation per file and `gh attestation verify` passes with `--signer-workflow`, `--source-ref` and `--source-digest`.
- [ ] A rerun of a failed release behaves: the artifact name clashes of upload-artifact v7 and the refusal to create a second draft for the same tag.
- [ ] The relay's collaborator-permission and run-log API calls work with this token (contents and actions read). Try it with a test issue labelled by a maintainer.
- [ ] A pull request from a fork on a branch named `main` does not start Deploy.
- [ ] CODEOWNERS shows no errors in the GitHub file view and a pull request that touches `.github/` requests the named owner.
- [ ] `CI passed` can be picked as a required check and is accepted from the GitHub Actions app. The reusable `secret-scan` job appears under its own name and a pull request with a failing scan blocks the merge.
- [ ] The secret scan reads its settings from the base branch: a test pull request that adds a root `.gitleaks.toml` allowing everything, with a fake token beside it, still fails.
- [ ] A release marked as a pre-release does not start `publish-pypi.yml`. A normal one does only when `PUBLISH_PYPI` is `true`.
- [ ] The secret scan fails on a test branch that adds a fake token in one commit and removes it in the next (use a throwaway value that is not a real credential).
- [ ] The weekly scan of the whole history is not red on old commits. If it is, look at each finding before allowing anything.
- [ ] The tag ruleset also blocks a version tag made through the release page or `gh release create --target`, by someone who is not a named maintainer.
- [ ] `rustup` on `ubuntu-22.04-arm` fetches the compiler named in `edge/rust-toolchain.toml`.
- [ ] `gh attestation verify` with `--source-digest` works with the `gh` version on the runner.

## Cost

The repository is public so GitHub-hosted minutes are free, including the arm64 Linux runner. Nothing here is billed today.

If the repository became private, minutes would count against the plan's allowance (2,000 a month on the Free plan) with Linux at one minute for each minute. What would change:

- the firmware job (the PlatformIO toolchains) and `cargo install cargo-audit` are the heaviest so the caches matter and the gate that runs `firmware` only when `firmware/` changes matters
- a release builds on seven runners and would cost around twenty minutes
- the weekly audit would use about five minutes
- the arm64 runner is billed on a private repository
- CodeQL and secret scanning are paid features on a private repository so `codeql.yml` would need turning off or a licence

We have not measured a full run on a hosted runner so we give no minute count for a pull request. After the first runs read the run times from the Actions tab and put the numbers here.
