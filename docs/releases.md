# Releases

PHAEMOS uses tag-based releases with changelog validation. Every change lands in `CHANGELOG.md` under
`[Unreleased]` as part of its own pull request, so a release only has to name the version.

## Cutting a release

1. Move the `[Unreleased]` entries in `CHANGELOG.md` under a new version heading: `## [X.Y.Z] - YYYY-MM-DD`.
2. Merge that change to `main` through a pull request.
3. A maintainer creates a signed tag on the merge commit, pushes it and creates the GitHub release with
   that version's changelog section as its notes:

    ```bash
    git tag -s vX.Y.Z -m "phaemos vX.Y.Z"
    git push origin vX.Y.Z
    gh release create vX.Y.Z --verify-tag --title vX.Y.Z --notes-file notes.md
    ```

4. The `Release` workflow checks that `CHANGELOG.md` has a heading for that exact version.

> [!IMPORTANT]
> The workflow fails if the tag and the changelog heading do not match, so a tag without its notes is
> caught straight away.

## Versioning

PHAEMOS follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html): a breaking API or schema change
raises the major version, a new feature the minor version and a fix the patch version.

## Deploying a release

Releasing and deploying are separate steps. See [deployment.md](deployment.md) for the server, Vercel and
DNS setup and [deployment-checklist.md](deployment-checklist.md) for the checks to run before a deploy.
