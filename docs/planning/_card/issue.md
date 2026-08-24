# Card: PyPI publish + quickstart flip (launch checklist L4)

Source: inline brief from the `belay-next` handoff (2026-08-24) + `docs/planning/launch-readiness/CHECKLIST.md` item L4. No GitHub issue exists for this work (`id` is the descriptive slug `pypi-publish`); the id lives in the branch and PR.

## Brief

L4 of `docs/planning/launch-readiness/CHECKLIST.md` — publish `belay-harness` to PyPI and flip the README quickstart off the "run from source" path. It is the first open item in the launch checklist's dependency order (Block B installability, `CHECKLIST.md:10-12`); L1–L3 are done so nothing blocks it, and `README.md:59` already names `uv tool install belay-harness` as unpublished. DONE = `uv tool install belay-harness` / `pipx install` / `pip install` all work on a clean macOS AND Linux box; the `uv build` sdist/wheel carries zero runtime deps and imports cleanly; the README's "until then, run from source" line is deleted; and time-to-first-verdict < 15 minutes is measured by a stranger (have one person time it). Test-first acceptance: a CI job installs the freshly built package into a clean venv on ubuntu-24.04 and macOS and runs `belay sandbox check` plus a minimal capture→verify roundtrip; package metadata (name, entrypoints, zero-deps) is asserted by test; `RELEASING.md`'s checklist becomes executable ("tag → CI green on both platforms → publish → build Docker image"), and the GHCR publish (when it lands) pushes the SAME image the `docker` job already validated. Caveat: R10 — the 15-minute metric needs a real external timer, and `belay-harness` must be free on PyPI before publishing.

## DONE criteria (from CHECKLIST.md L4)

> `belay-harness` v0.1.0 published; `uv tool install belay-harness` / `pipx install` / `pip install` all work on a clean macOS and Linux box; the README's "until then, run from source" line is deleted; **time-to-first-verdict < 15 minutes** (roadmap metric) measured by a stranger following the quickstart — have one person time it.

## Blockers / dependencies

- **Depends on nothing unshipped:** L1 (the number, 11/60 = 18.3%), L2 (Linux sandbox slice, v0.20.0) and L3 (Docker self-host, v0.21.0) are done. The checklist records "Next after this item: L4 — PyPI publish + quickstart flip" (`CHECKLIST.md:191`).
- **Known caveat (named before the dig):** R10 (solo-founder bandwidth) — the 15-minute metric requires a real external timer, which no CI job can fake. Secondary: `belay-harness` must be free on PyPI; the `uv build` sdist/wheel must import cleanly with zero runtime deps on both macOS and Linux. The GHCR publish channel is a separate deferred slice and must push the SAME image the `docker` job already validated (`RELEASING.md`).

## Open questions (flag for the PRD)

- What exactly does "zero runtime deps" assert, and how is it tested (import-time vs install-time)? The repo's zero-dependency contract is a stated constraint (`CLAUDE.md`).
- Package name: is `belay-harness` confirmed, and does it need to be verified free on PyPI before the PRD is final?
- The release/versioning mechanics: how does the 0.x version bump interact with the existing `RELEASING.md` flow (tag → CI green both platforms → publish → Docker image)?
- Does L4's CI install-test run against the built artifact (sdist/wheel) or the source tree? The checklist DONE says "freshly built package" — the test must prove the artifact path, not the editable path.

## Context links

- Launch checklist: `docs/planning/launch-readiness/CHECKLIST.md` (L4 at lines 193–199; L3 done note at 121–191; "how to use" binding belay-next at 10–12)
- Phase-1 metric: `docs/ROADMAP.md` line 277 ("time-to-first-verdict < 15 minutes from `docker run`")
- Packaging facts: `README.md:59` quickstart (`uv tool install belay-harness` — not yet published, L4); `RELEASING.md`; `.github/workflows/ci.yml`
- `belay-next` handoff: pick L4 / `pypi-publish`, alternates C7 `live-console` and C9 `interop-export-back`
