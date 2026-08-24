# Understanding: PyPI publish + quickstart flip (launch checklist L4)

Phase 2 dig for the L4 unit. Sources: `docs/planning/_card/issue.md` (brief), the two
read-only research passes over `pyproject.toml`, `RELEASING.md`, `README.md`,
`.github/workflows/{ci,release}.yml`, `tests/`, `docs/planning/launch-readiness/CHECKLIST.md`,
`docs/planning/docker-selfhost/prd.md`, `CHANGELOG.md`, and the guardrail docs.

## What this work is really asking

L4 is the **distribution** half of "a stranger can run Belay" — the Phase-1 installability
block. It is **not** an engine capability: it touches no verdict axis, no replay path, no
sandbox logic. The moat (replay + execution-grounded verification + corpus) is already
shipped; this unit makes the Phase-0 number and the harness *installable by a stranger on
their own box*, which is the precondition for the Phase 1→2 gate (≥3 external self-hosts,
`ROADMAP.md:283`).

**The critical discovery from the dig:** the PyPI publish channel is ALREADY LIVE and has
been since v0.1.0. Verified 2026-08-24 against the PyPI JSON API
(`https://pypi.org/pypi/belay-harness/json`): `belay-harness` is owned by Ali Haqiqi, and
every release 0.1.0 → 0.21.1 has wheel + sdist uploads whose timestamps match the
CHANGELOG dates (0.21.0 and 0.21.1 both uploaded 2026-08-20; first upload 2026-07-18). The
trusted-publisher pipeline (`release.yml`) has evidently been working since the v0.1.0 tag.
So L4's "published" clause is satisfied in substance — the checklist's "v0.1.0" wording and
the README's "until then, run from source" caveat are the stale artifacts, not the publish.
**What L4 genuinely still needs:** artifact-path install verification in CI (nothing
installs the built wheel today), the README quickstart flip, and the stranger-timed metric.

**The critical discovery from the dig (as originally written, retained):** most of the packaging machinery already exists and
is correct. `pyproject.toml` is publish-ready (`name = "belay-harness"`, hatchling, empty
runtime deps, `belay = "belay.cli:main"` entrypoint, wheel targets only `src/belay`,
`pyproject.toml:9,44,52-53,67-68`). `release.yml` is a complete tag-driven build →
tag==version check → PyPI trusted-publish → GitHub Release pipeline
(`release.yml:3-5,22,24-32,39-54,56-93`). `RELEASING.md` documents the whole cut-a-release
flow and the one-time PyPI trusted-publisher setup (`RELEASING.md:26-68`). The version is
read from the installed distribution, so the published wheel stamps the true version
(`src/belay/__init__.py:16-21`).

**What L4 actually adds, then, is narrow and concrete:**
1. **Artifact-path install verification the repo does not have.** Every CI job today runs
   the source tree via `uv sync`; nothing installs the *built* wheel/sdist
   (`ci.yml`, confirmed by research — no `uv build`/`pip install <dist>` step in CI). L4's
   DONE ("works on a clean macOS and Linux box") has no CI surface asserting the artifact
   path. This is the load-bearing, test-first acceptance.
2. **The PyPI publish itself** — a one-time, owner-only act: create/reserve `belay-harness`
   on PyPI, add the trusted publisher (`RELEASING.md:52-68`), then push a version tag so
   `release.yml` runs. Not something CI can do; it is an operator step *after* the PR merges.
3. **README quickstart flip** — delete the "until then, run from source" caveat
   (`README.md:56`) and promote the install block (`README.md:58-62`) to the primary path.
   Keep the Develop/from-source section (`README.md:287-297`).
4. **The 15-minute stranger measurement** — a manual, human-timed run (R10). Provide a
   runbook so the timing is reproducible; the timing itself is an operator step.

## Affected areas

- `pyproject.toml` — version bump only when cutting the release; no metadata change expected.
- `.github/workflows/ci.yml` — add an artifact-install check (build via `uv build`, install
  the wheel into a clean venv, run `belay --help` / `belay sandbox check` / a minimal
  capture→verify roundtrip) on macOS (`test` job) and Linux (`test-linux` job). Possibly a
  dedicated job to keep it orthogonal.
- `README.md` — install section (lines 54–62), develop section (287–297) stays.
- `RELEASING.md` — the stale "C7 → v0.2.0" example (`RELEASING.md:22`); confirm the
  trusted-publishing instructions are current.
- `CHANGELOG.md` — new dated section when the release is cut (post-merge).
- `docs/planning/launch-readiness/CHECKLIST.md` — mark L4 ✅ only when DONE holds (post-publish),
  per the checklist's own rule (`CHECKLIST.md:8-20`).
- New: a runbook/script for the time-to-first-verdict measurement.

## Contradictions surfaced (flagged, not papered over)

1. **L4 DONE says "`belay-harness` v0.1.0 published" but the repo is at `0.21.1`**
   (`CHECKLIST.md:195` vs `pyproject.toml:10`). The v0.1.0 wording is stale — it predates
   the release history (tags v0.1.0…v0.21.1). The publish must happen at the *next real
   version* (post-merge bump → 0.22.0), not v0.1.0. Needs a decision, but the resolution is
   near-certain: keep versioning as-is, publish the next bump.
2. **`ROADMAP.md:277` frames the metric as "from `docker run`", while L4's DONE frames it as
   "following the quickstart"** (install path). Both are in the README quickstart; the
   stranger test should measure the README quickstart as written and report which path.
3. **"Zero runtime dependencies" is load-bearing and already enforced**
   (`pyproject.toml:43-44`, `tests/test_import_guard.py:84-111`, `Dockerfile:16-18`). The
   publish must not perturb it; the artifact-install CI is itself a new enforcement surface.
4. **The GHCR "SAME image" rule is a cross-doc invariant** (`CLAUDE.md:40-41`,
   `RELEASING.md:16-18`, `CHANGELOG.md:73-75`, `CHECKLIST.md:182-184`) — it is a *deferred,
   separate* slice and is **out of scope** for L4. Flagged so the PRD does not silently
   absorb it.
5. **`belay` is taken on PyPI** (an unrelated MicroPython tool) — that is *why* the dist is
   `belay-harness` (`pyproject.toml:6-8`). `belay-harness`'s own availability is **not
   verified anywhere in the repo**; it must be checked (PyPI JSON API) before publish.

## Strategic constraints honored

- **Not an agent framework, not an LLM judge** — this is pure distribution; orthogonal to
  both guardrails by construction.
- **Runs on user's infra / no raw-data egress** — publishing the wheel is an explicit,
  opted-in code egress (the user publishes it), and nothing about install/run changes the
  on-box posture. The README must keep the honest coverage line with the quickstart.
- **UNVERIFIED never PASS / honest claims** — the stranger-timing metric must be *reported*
  honestly (measured once, n=1), not asserted as a guarantee. The README flip must not
  over-claim what install gives you.
- **R10 (solo-founder bandwidth)** is the named risk: the 15-minute metric needs a real
  external timer.

## Verdict-axis placement

**None.** This unit changes no verdict axis (A1/A2/A3), no trace format, no replay engine.
It is distribution + docs + CI. It *uses* the verdict machinery (the install acceptance runs
`belay verify` on a capture→verify roundtrip) but does not modify it.

## Open questions for the PRD interview

1. **Version at publish**: confirm the next bump (0.22.0) is the publish version, and that
   the checklist's "v0.1.0" wording is corrected to "the next release".
2. **Artifact CI scope**: build-and-install check in the existing `test`/`test-linux` jobs,
   or a dedicated job? Which install frontends must CI exercise (`pip install <wheel>`,
   `uv tool install`/`uvx`, `pipx`) vs which are documented-and-manually-verified at publish?
3. **Name availability**: verify `belay-harness` free on PyPI via the JSON API now, or at
   publish time? (Recommend: a CI-checkable or PRD-recorded verification now.)
4. **Trusted publisher**: is the one-time PyPI setup (project + trusted publisher) already
   done by the owner, or is it part of this unit's operator steps?
5. **README flip**: keep `uv tool install` as the headline with `pipx`/`pip` as alternates
   (current structure), or restructure? Keep the Docker quickstart in place (yes, per L3).
6. **What does "clean box" mean for the CI check**: fresh `python:3.12` container (Linux)
   and a fresh venv on the macOS runner — confirm that is the acceptance.
