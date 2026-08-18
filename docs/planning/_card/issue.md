# Card: Docker self-host (launch checklist L3)

Source: inline brief from the `belay-next` handoff (2026-08-18) + `docs/planning/launch-readiness/CHECKLIST.md` item L3. No GitHub issue exists for this work (`gh issue list` → "No Issues"); the id lives in the branch and PR.

## Brief

L3 of `docs/planning/launch-readiness/CHECKLIST.md` — a `Dockerfile` (+ `docker compose` scaffolding for the future console) whose image runs the REAL Linux sandbox backend (`src/belay/sandbox/linux.py`), working on Linux and macOS hosts. Test-first acceptance: the full suite runs green inside the image on CI (ubuntu-24.04); an escape attempt inside the container is contained by Landlock and recorded as a denial; a snapshot restore round-trips byte-identically inside the container or degrades to UNVERIFIED with a named cause — never a silent fallback; the `docker run belay` entrypoint behaves identically to the installed CLI. The caveat is the container boundary: verify Landlock availability, seccomp profile interplay, and FICLONE-on-overlayfs degradation on the pinned image, and extend `docs/technical/THREAT_MODEL.md` for the container boundary before claiming anything about it.

## DONE criteria (from CHECKLIST.md L3)

> `docker run` (and `docker compose` for the console) works on Linux + macOS host, per the roadmap's Phase-1 deliverable. The image runs the real sandbox — not a container that can't do the core.

## Blockers / dependencies

- **Depends on nothing unshipped:** L1 (the number, 11/60 = 18.3%) and L2 (Linux sandbox slice, v0.20.0) are done. The L2 entry records "now packaging on top of a substrate that exists, no longer a blocker on a mechanism" (`CHECKLIST.md:119`).
- **Known caveat (named before the dig):** the container boundary. Inside Docker: Landlock needs a host kernel ≥5.13; Docker's own seccomp profile must not pre-empt Belay's deny-all; reflink (FICLONE) snapshot fidelity is unavailable on overlayfs (needs the named-cause degradation path, never a silent fallback); TMPDIR in containers is the world-writable-`/tmp` hazard `THREAT_MODEL.md:495` names as "not bounded … CI, containers, launchd, cron". `THREAT_MODEL.md:319` already scopes "nothing here is claimed about any other Linux image: a Docker image…" — the container boundary extends that doc, not the claims. R8 territory (`ROADMAP.md:367`).

## Open question (flag for the PRD)

- L3's DONE says "`docker compose` for the console" — but C7 (the console) does not ship yet. Decide in the PRD: does L3 ship a compose file whose console service is added by C7, or does the compose file cover the engine service only, with the console clause deferred to L6?

## Context links

- Launch checklist: `docs/planning/launch-readiness/CHECKLIST.md` (L3 at lines 121–126; L2 done note at 119)
- C2 spec: `docs/technical/CAPABILITY_ROADMAP.md` §C2 (lines 150–189); sequencing table line 860
- Linux sandbox planning: `docs/planning/linux-sandbox/`
- Threat model: `docs/technical/THREAT_MODEL.md` (container notes at lines 135, 319, 495)
- Packaging facts: `README.md:59` quickstart (`uv tool install belay-harness` — not yet published, L4); `RELEASING.md`; `.github/workflows/ci.yml`
