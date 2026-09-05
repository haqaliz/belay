# Releasing Belay

Releases are cut by **pushing a version tag**. The release workflow runs in the
**haqaliz/belay** repo with the repo's `GITHUB_TOKEN`, so the GitHub Release is owned by the
repository, not by whatever account the local `gh` CLI happens to be logged into. **Do not run
`gh release create` by hand** — let the workflow do it.

The PyPI distribution is **`belay-harness`** (the name `belay` is already taken on PyPI); the
import package and the `belay` command are unchanged.

> **The container channel now has a job; whether it is LIVE is a separate question.** L3
> shipped the `Dockerfile` and `docker-compose.yml`, and the `docker` CI job builds the image
> from every PR and re-runs the whole measurement inside it. Publishing was deferred by name
> and is now built: `release.yml`'s **`ghcr`** job builds the image from the tagged checkout,
> **measures that exact image** with the same in-image acceptance, proves the measured and
> pushed image IDs are equal, and only then pushes `ghcr.io/<owner>/belay:vX.Y.Z` and
> `:latest`. The pre-registered rule — *push the image that was validated, never a rebuild
> nobody measured* — is enforced by `tests/test_release_workflow.py`, which fails if the push
> ever moves ahead of the measurement or leaves its job.
>
> **Until a tag has actually run it and an anonymous `docker pull` has succeeded, the channel
> is UNVERIFIED, not live** — a first push can land the package private, which is an owner
> click to fix and must never be papered over. `linux/amd64` only: that is the substrate
> `ubuntu-24.04` measures, and an arm64 image would be one nothing ran on. Apple Silicon
> readers keep building locally, which works.

## Versioning

`0.x.0` minor bumps, one per shipped capability/milestone (the docker-selfhost slice → `v0.21.0`, and so on). Patch
releases (`0.x.y`) batch fixes. Belay is pre-1.0: a `0.x` bump may include changes that would be
breaking under strict semver. The tag **must** match the `version` in `pyproject.toml`.

## Cut a release

1. Bump `version` in `pyproject.toml` and move the `[Unreleased]` notes into a dated version
   section in `CHANGELOG.md`.
2. Commit to `master` and make sure CI is green (`.github/workflows/ci.yml`). "Green"
   covers the full suite on **both platforms** (`test` on macOS, `test-linux` on pinned
   ubuntu-24.04) **and** the `docker` job, which builds the release image from the same
   checkout and re-runs the measurement inside it — so the image a reader will build from
   the tag is validated before the tag is pushed, not after.
3. Tag and push the tag — a plain `git push`, using the repo's git identity:

   ```bash
   git tag -a v0.1.0 -m "belay 0.1.0"
   git push origin v0.1.0
   ```

4. The `release` workflow (`.github/workflows/release.yml`) then, in parallel jobs:
   - builds the wheel and sdist and **publishes to PyPI** (via trusted publishing — see below),
   - **creates the GitHub Release** from the matching `CHANGELOG.md` section and attaches the
     wheel + sdist,
   - **builds, measures and pushes the container image** to `ghcr.io/<owner>/belay` (the
     `ghcr` job; see the callout above for what "measures" buys and what it does not).

   Each channel is an independent job, so one failing does not block the others. Watch it with
   `gh run watch` or the Actions tab.

5. **Verify each channel before calling the release done** — the honesty rule the product
   enforces, applied to its own release. PyPI: check the **`/simple/`** index, not the JSON
   API, which is CDN-stale for minutes after a publish (measured on v0.25.0, where even the
   per-version endpoint 404'd). GitHub Release: `gh release view vX.Y.Z`. Container:
   `docker pull ghcr.io/<owner>/belay:vX.Y.Z` **from a shell with no credentials** — a push
   that succeeded into a private package pulls fine for you and fails for everyone else.

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
