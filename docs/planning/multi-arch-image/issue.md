# Issue #56 — feat: multi-arch container image and image supply chain

## Why
`ghcr.io/haqaliz/belay` is `linux/amd64` only; multi-arch, signing/provenance and a Docker Hub mirror were deferred by name at `ghcr-publish` (2026-09-05).

## Scope
- `linux/arm64` built and measured with the same in-image acceptance.
- Image signing/provenance attestation.
- Keep the measured-image-equals-pushed-image rule.

## Exit criteria
- Anonymous pull of both arches runs `belay verify --help`.
- Release workflow test still proves measured == pushed.

## Status
Deferred by name; not launch-blocking.
