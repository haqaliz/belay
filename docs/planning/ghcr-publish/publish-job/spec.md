# Aspect spec — `publish-job`

**Parent PRD:** `docs/planning/ghcr-publish/prd.md`
**One-line boundary:** one `ghcr` job in `release.yml` that builds, measures and pushes the
same image, plus the guard that keeps it that way. No engine change; no doc may claim
`docker pull` works until a real pull has proved it.

---

## Problem slice & user outcome

L3 shipped the image and deferred the channel by name. A reader who wants the container
today must clone and build. This aspect adds the push — and the only interesting part of it
is the ordering, because the naive version of this job (`docker build` then `docker push`)
ships strangers an artifact nothing ran inside.

## In-scope (PRD M1–M6)

1. **`.github/workflows/release.yml` → job `ghcr`** — `runs-on: ubuntu-24.04` (the same pin
   the `docker` CI job uses, because that is the substrate the in-image acceptance
   measures), `permissions: {packages: write}` and nothing wider, no `needs` (channels stay
   independent), triggered by the existing `v*` tag.
2. **Build → measure → push, one job, that order.** `docker build -f Dockerfile -t belay:test .`
   from the tagged checkout; then the same three modules the `docker` CI job runs
   (`test_docker_image.py`, `test_docker_inimage.py`, `test_docker_compose.py`); then tag
   and push `ghcr.io/<owner>/belay:<vX.Y.Z>` and `:latest`.
3. **`BELAY_TEST_IMAGE` adoption in `tests/conftest.py`.** The `built_image` session fixture
   builds its own image and `docker rmi`s it on the way out — so without this the job would
   measure an artifact that no longer exists when the push runs. Set, the fixture adopts the
   named tag and neither builds nor removes. Unset — every local run and every other CI job
   — behaviour is byte-identical to before.
4. **An ID equality check between measurement and push.** `docker image inspect --format
   '{{.Id}}'` on the measured tag and on each pushed reference; a mismatch fails the job.
   Ordering alone would still permit measuring one tag and pushing another.
5. **`tests/test_release_workflow.py`** — parses the workflow as YAML (no Docker, no
   network, runs anywhere) and fails if: the `ghcr` job is missing; the push is not preceded
   by the build and the measurement *in the same job*; the measurement does not adopt the
   tag the build produced; the ID check is gone; the permissions widen; either published
   reference stops being pushed; the version stops coming from `github.ref_name`; the job
   grows a `needs`; or the workflow starts triggering on anything but a `v*` tag.
6. **OCI labels on the image** (`source`, `description`, `licenses`) so the package links
   back to this repository.

## Explicitly out of scope

- **Multi-arch.** `linux/amd64` only, because that is what `ubuntu-24.04` measures.
  Publishing arm64 would ship an unmeasured substrate — the thing this aspect exists to
  prevent, in a new hat.
- Signing / provenance attestation, a Docker Hub mirror, any change to image contents.
- **Every doc line that says `docker pull` works.** They land in a separate commit after an
  anonymous pull has succeeded against the live package.

## Verification, and what it is worth

Run locally before the job existed, against the real Docker daemon on this machine
(2026-09-05):

- `docker build -f Dockerfile -t belay:test .` → `sha256:8061318bc72a…`
- `BELAY_TEST_IMAGE=belay:test uv run pytest <the three modules> -q` → **20 passed**
- `docker image inspect --format '{{.Id}}' belay:test` afterwards → **the same id**

That is the job's exact sequence minus the push, so what remains unproven until the first
tag is: the login, the push, and the package's visibility. **None of those may be described
as working before they are observed.**

## The finding this aspect produced

`test_docker_inimage.py` hard-coded its dev dependencies as `("pytest", "mcp==1.28.1")` —
"measured by running the suite in the container and extending the list until it imported".
Adding `pyyaml` for the workflow guard broke the in-image run with a collection error, and
**nothing connected the two lists to say so**. Found by running the measurement, not by
reading it. The list is now derived from `pyproject.toml`'s dev group minus a named,
reviewable exclusion (`ruff`, `mypy` — tools this run never invokes), so the next dev
dependency cannot reintroduce it.
