# PRD — multi-arch container image

**Issue:** #56 · **Slug:** `multi-arch-image` · **Branch:** `feat/56/aliz`

## Problem

`ghcr.io/haqaliz/belay` is `linux/amd64` only. Apple Silicon and arm64 servers pull it
emulated. Multi-arch, signing/provenance and a Docker Hub mirror were deferred by name at
`ghcr-publish` (2026-09-05).

## What ships

**Multi-arch, on the pre-registered rule that the pushed image is the measured image.**

- `release.yml` gains `docker/setup-qemu-action` + `docker/setup-buildx-action`.
- **amd64** is built and measured exactly as today (unchanged).
- **arm64** is built with `buildx --platform linux/arm64 --load`, then measured under QEMU
  with the same **in-image acceptance** (`tests/test_docker_inimage.py`) via
  `BELAY_TEST_PLATFORM=linux/arm64`.
- Push both measured images as `:$TAG-amd64` / `:$TAG-arm64`, then
  `docker buildx imagetools create` assembles `:$TAG` and `:latest` from those two digests.
- The ID check stays: each pushed arch tag is the image the daemon measured.
- `tests/conftest.py`'s in-image runner honours `BELAY_TEST_PLATFORM` (adds `--platform`) so
  the acceptance can run against the non-native image.

## Non-goals

- **Signing/provenance (cosign/attestations) and a Docker Hub mirror stay deferred by name.**
- compose acceptance stays amd64-only (a compose stack under QEMU is a different substrate
  claim); document that honestly.
- No change to `ci.yml`'s PR docker job (amd64, fast).
- No image rebuild between measurement and push.

## Acceptance criteria

1. `release.yml` parses (YAML) and contains: QEMU + buildx setup, an arm64 build, an arm64
   measurement with `BELAY_TEST_PLATFORM=linux/arm64`, and `imagetools create` over both
   arch tags.
2. The amd64 build → measure → ID-check → push sequence is unchanged in substance.
3. `tests/test_docker_inimage.py`'s `docker run` gains `--platform` only when
   `BELAY_TEST_PLATFORM` is set; unset behaviour is byte-identical.
4. `tests/test_release_workflow.py` pins the new steps and the arch tags.
5. Docs: README says both arches are published and what was measured; RELEASING.md states
   arm64 is measured by the in-image acceptance only; signing/provenance remain deferred.

## Risks

- **R-a:** arm64 under QEMU is slow (the acceptance can take tens of minutes). Accepted:
  release-time only, not PR CI.
- **R-b:** `buildx --load` for a non-native platform depends on the docker driver. Mitigated:
  the workflow fails loudly rather than pushing an unmeasured image.
- **R-c:** a manifest assembled from measured tags could drift if a tag is overwritten
  between push and manifest creation. Mitigated by using the pushed digests in order, in one
  job.

## Open questions

- 🟡 **Q1:** publish `linux/arm/v7` too? Proposed: no — untested substrate, no demand.
