# PRD: The container CHANNEL — `docker pull ghcr.io/haqaliz/belay`

Slug: `ghcr-publish` · Branch: `feat/ghcr-publish/aliz` · Type: feat · Owner: aliz
Sources: `RELEASING.md` (the deferral and its shape), `docs/planning/docker-selfhost/`
(L3, which shipped the image), `docs/planning/launch-readiness/CHECKLIST.md` → L3 and the
publish gate.

## Problem Statement

**L3 shipped the image; it did not ship the channel.** `docker build -t belay .` works from
any checkout and the `docker` CI job re-runs the whole in-image measurement on every PR — so
the artifact is real and validated. What does not exist is a place to *get* it:

> "there is no `docker pull ghcr.io/haqaliz/belay` — a reader builds it from the checkout"
> — `RELEASING.md`

Three costs, and only the third is new:

1. **The quickstart's container path asks for a build.** `pip install` is one command against
   a live index; the container path is a clone plus a multi-minute build. The README says so
   honestly, which is why this is a gap and not a lie.
2. **The launch gate's L2–L5 clause is narrower than it reads.** It says *"`docker` and
   `pip install` both real paths"*, and the docker half currently means *build it yourself*
   (stated in-line as of 2026-09-05). A Product Hunt reader will read "self-host in one
   command" and try `docker pull`.
3. **Publishing is the one release channel with a real footgun.** PyPI publishes an artifact
   built and version-checked in the same run. A naive container job would `docker build` and
   `docker push` with **nothing between them** — shipping to strangers an image no test ever
   ran inside. `RELEASING.md` pre-registered the rule against exactly that: *"it should push
   the SAME image the `docker` job already validated rather than rebuilding an unvalidated
   one."*

## Goals & Success Metrics

1. **`docker pull ghcr.io/haqaliz/belay:vX.Y.Z` works for a stranger**, anonymously, on the
   next tag — **verified by actually pulling it**, from a shell with no credentials, before
   any doc says it works.
2. **No image is ever pushed that was not measured.** The validation runs against the exact
   image id that is pushed, in the same job, and the push is unreachable if it fails.
3. **The claim split from L3 survives.** The `docker` job's Linux-host measurement is what
   validates; the macOS-host path remains a documented manual re-probe. Publishing changes
   the *channel*, not the substrate claims.
4. **No verdict axis, invariant, published number, or engine line moves.** This slice is
   distribution only.

## Requirements

### Must-have

- **M1 · A `ghcr` job in `.github/workflows/release.yml`**, triggered by the same `v*` tag as
  the other channels, `permissions: packages: write` and nothing wider, in the repo's own
  workflow so the push is the repo's (never a local `docker push` by hand — the same rule
  `RELEASING.md` already states for `gh release create`).
- **M2 · Build → validate → push, in that order, in ONE job.** The job builds the image from
  the tagged checkout, runs the in-image acceptance against it, and only then pushes. A
  separate "validate" job that rebuilt the image would be validating a *different* build; a
  cached image from an earlier PR would be a *different commit*. The image that is measured
  and the image that is pushed are the same image id, and the job proves it.
- **M3 · Tags: `vX.Y.Z` and `latest`.** The version tag is the honest one; `latest` is a
  convenience that must always resolve to the newest released version, never to a build from
  an untagged commit (the job only ever runs on a tag).
- **M4 · Independent, like every other channel.** `release.yml`'s existing jobs are parallel
  and independent so one failing channel does not block the others. `ghcr` joins them on the
  same terms: a GHCR failure must not un-publish PyPI or the GitHub Release.
- **M5 · A guard test over the workflow itself.** `tests/test_release_workflow.py` parses
  `release.yml` (no network, no Docker) and fails if the push step is reachable without the
  validation step ahead of it in the same job, if the pushed reference is not the version
  tag, or if the job requests write scopes beyond `packages`. This defect class — "ship an
  artifact nothing checked" — is exactly what this repo exists to catch; it does not get to
  live in our own release pipeline unguarded.
- **M6 · `org.opencontainers.image.source` on the image**, so the published package links to
  this repository rather than floating unattributed.
- **M7 · Docs land AFTER the first push is verified, never with it.** `README.md`,
  `RELEASING.md`, `CHECKLIST.md` (L3 and the L2–L5 gate qualifier), `CLAUDE.md` and
  `STATUS.md` all currently say the publish job is deferred **by name**. Those lines are
  retired in a **separate commit, after `docker pull` has been run against the live package
  from an unauthenticated shell** — an unverified channel is `UNVERIFIED`, not `PASS`, and
  this project does not get to make an exception for its own release notes.

### Should-have

- **S1 · Multi-arch is NOT in this slice, and is named.** The `docker` job measures
  `linux/amd64` on `ubuntu-24.04`. Publishing an `arm64` image would ship a substrate nobody
  measured — the exact thing M2 exists to prevent. An Apple Silicon reader keeps building
  locally (which works today) until an arm64 runner measures it.

### Nice-to-have

- **N1 · The digest in the release notes**, so a reader can pin by digest rather than tag.

## Technical Considerations

- **Where it lives:** `.github/workflows/release.yml` plus one `LABEL` in `Dockerfile`. No
  `src/belay/` change; the engine is untouched.
- **Package visibility is an OWNER action and may not be automatable.** A package first
  published by Actions can land **private**, in which case an anonymous `docker pull` fails
  even though the push succeeded. If that happens it is reported as an unfinished channel and
  a one-click owner fix, never worked around and never quietly claimed as done.
- **The validation step reuses the existing measurement**, `tests/test_docker_image.py` +
  `test_docker_inimage.py` + `test_docker_compose.py` — the same three modules the `docker`
  CI job runs, against a session-built image. Nothing new is written to check the image; a
  second, weaker check would be the more dangerous outcome.

## Risks & Open Questions

- **The first push lands private** → named above; verified, not assumed.
- **Tag-time build ≠ PR-time build.** After a squash or merge, master's tree differs from the
  PR head, so "reuse the PR's image" was never actually available. Building at the tag and
  measuring *that* image is the stronger reading of the pre-registered rule, and it is what
  M2 specifies.
- **Open:** whether `latest` should exist at all before there is a second release to move it.
  Decided yes — it is the reference every reader types first, and it can only ever point at a
  tagged release.

## Out of Scope

- Multi-arch images (S1), signing/attestation (cosign, provenance), a Docker Hub mirror.
- Any change to the image's contents, the sandbox substrate claims, or the L3 claim split.
- The ≥1-external-self-hoster gate item, which is blocked on a person and not on work.
