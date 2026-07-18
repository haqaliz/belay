# Releasing Belay

Releases are cut by **pushing a version tag**. The release workflow runs in the
**haqaliz/belay** repo with the repo's `GITHUB_TOKEN`, so the GitHub Release is owned by the
repository, not by whatever account the local `gh` CLI happens to be logged into. **Do not run
`gh release create` by hand** — let the workflow do it.

The PyPI distribution is **`belay-harness`** (the name `belay` is already taken on PyPI); the
import package and the `belay` command are unchanged.

> **No container channel yet.** Belay's sandbox and snapshot are macOS-only, so a Linux container
> cannot run the core (`verify`/`corpus run`/the sandbox). A GHCR image is deliberately deferred
> until the Linux sandbox slice lands, rather than shipping an image that can't do the main thing.
> When it lands, add a `ghcr` job here and to `release.yml`.

## Versioning

`0.x.0` minor bumps, one per shipped capability/milestone (C7 → `v0.2.0`, and so on). Patch
releases (`0.x.y`) batch fixes. Belay is pre-1.0: a `0.x` bump may include changes that would be
breaking under strict semver. The tag **must** match the `version` in `pyproject.toml`.

## Cut a release

1. Bump `version` in `pyproject.toml` and move the `[Unreleased]` notes into a dated version
   section in `CHANGELOG.md`.
2. Commit to `master` and make sure CI is green (`.github/workflows/ci.yml`).
3. Tag and push the tag — a plain `git push`, using the repo's git identity:

   ```bash
   git tag -a v0.1.0 -m "belay 0.1.0"
   git push origin v0.1.0
   ```

4. The `release` workflow (`.github/workflows/release.yml`) then, in parallel jobs:
   - builds the wheel and sdist and **publishes to PyPI** (via trusted publishing — see below),
   - **creates the GitHub Release** from the matching `CHANGELOG.md` section and attaches the
     wheel + sdist.

   Each channel is an independent job, so one failing does not block the others. Watch it with
   `gh run watch` or the Actions tab.

## One-time setup per channel

### GitHub Release

Nothing to set up — it uses the repo `GITHUB_TOKEN`.

### PyPI (trusted publishing, no stored token)

Belay publishes with [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/), so no
API token is stored in the repo. One time:

1. Create the project **`belay-harness`** on PyPI (or reserve it by uploading the first build
   manually once), owned by the account that should own the package.
2. In the project's **Publishing** settings on PyPI, add a GitHub Actions trusted publisher:
   - Owner: `haqaliz`
   - Repository: `belay`
   - Workflow: `release.yml`
   - Environment: `pypi`
3. The `pypi` job runs in the `pypi` GitHub environment and requests the `id-token: write`
   permission the workflow already declares. No secrets needed.

If trusted publishing is not yet configured, the PyPI job fails (harmlessly — the other channels
still publish); configure it and re-run just that job, or cut a patch release.

## Release identity

The release belongs to the **haqaliz** account and the **haqaliz/belay** repository. Any manual
asset handling must run with `gh` active as `haqaliz` (`gh auth switch --user haqaliz`). Commit
as `aliz@foresightanalytics.ca` (maps to haqaliz), never `support@manifold.autos`.
