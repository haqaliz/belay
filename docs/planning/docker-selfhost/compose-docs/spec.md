# Spec: Aspect A3 — compose, threat model, docs (`compose-docs/`)

Part of `docs/planning/docker-selfhost/prd.md` (L3, Docker self-host).

## Problem slice

The surfaces a stranger reads and runs first: a minimal `docker-compose.yml` (engine service; C7 console hook named, not built), the honest container-boundary statement in `docs/technical/THREAT_MODEL.md`, the README quickstart replacing the "no container yet" callout (`README.md:64`), and the L3 ✅ mark on the launch checklist.

## In-scope requirements

1. `docker-compose.yml` — engine service only (`docker compose run belay <args>` / `docker compose exec`); comment names the future C7 console service. No broken console service ships.
2. `THREAT_MODEL.md` container section — measured not assumed:
   - Landlock is the host kernel's (unprivileged, ≥5.13, not namespaced); pre-5.13 host ⇒ launcher refuses (exit 2, named cause), suite skips `landlock-unavailable`.
   - Docker's default seccomp profile vs Belay's nested BPF filter — verified in-image by A2, then stated here.
   - Overlayfs ⇒ `reflink-unavailable` ⇒ copy path; cross-capability restore = SKIP with `UNRESTORABLE_CAPABILITY_MISMATCH`, never a guessed restore (`substrate.py:423-433`).
   - World-writable `/tmp` TMPDIR neighborhood unbound in containers (`THREAT_MODEL.md:398-407,495`) — restated, not fixed.
   - The docker.sock line stays closed: `network-bind` grant measured narrow (`THREAT_MODEL.md:133-136`); the image's contained processes cannot reach the daemon.
   - The claim split: Linux-host measured in CI; macOS-host (Docker Desktop VM) re-probe manual.
3. README — replace the callout with the `docker run` quickstart (kernel ≥5.13 requirement carried), the volume/ownership contract from A1, and the coverage line; update the platform coverage table if needed.
4. `docs/planning/launch-readiness/CHECKLIST.md` — L3 ✅ with DONE-criteria evidence; progress-log row.

## Out-of-scope

- The console and its service.
- GHCR/publish docs (deferred slice).
- L4 PyPI quickstart flip.

## Acceptance criteria (test-first)

- `docker compose config` validates (no orphan/undefined-service errors) and `docker compose run --rm belay --help` exits 0 in CI.
- THREAT_MODEL container section exists and cross-references the A2 in-image measurements (a doc test or checklist item asserts the section exists and names the measured artifacts — mirror the L2 discipline: "every claim cross-referencing a measured artifact").
- README quickstart's docker path is executable verbatim by a stranger (no invented flags; commands verified in A2 CI).
- CHECKLIST L3 marked ✅ with the four acceptance items cited; the README "no container yet" callout is gone.

## Dependencies / sequencing

Third aspect — consumes the image (A1) and its measurements (A2). Docs update in the same PR as the merge.

## Open questions / risks

- Compose environment mapping: which env vars the service exposes (`BELAY_TRACE_DIR`, `BELAY_SANDBOX_NETWORK`, …) and default volume mounts.
- README size discipline: the docker section must stay quickstart-sized; deeper material lives in THREAT_MODEL and the checklist.
