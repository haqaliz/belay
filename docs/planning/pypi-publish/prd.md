# PRD: PyPI publish + quickstart flip (launch checklist L4)

Slug: `pypi-publish` · Branch: `feat/pypi-publish/aliz` · Type: feat · Owner: aliz
Sources: `docs/planning/_card/issue.md` (brief), `docs/planning/_card/understanding.md`
(dig — includes the live-PyPI verification), `docs/planning/launch-readiness/CHECKLIST.md`
item L4.

## Problem Statement

A stranger cannot yet be pointed at the README quickstart: the install block says
*"Install (once v0.1.0 is published — until then, run from source)"*
(`README.md:56`), and nothing in CI proves that the *built artifact* installs and runs on
either platform — every CI job runs the source tree via `uv sync`
(`.github/workflows/ci.yml`). The launch gate requires "a stranger can install and run
Belay on macOS **and** Linux in under 15 minutes, with `docker run` and `pip install` both
real paths" (`CHECKLIST.md:250`), and the Phase 1→2 gate is ≥3 external parties self-hosting
(`ROADMAP.md:283`) — impossible while the install path is marked "until then".

**Measured reality check (2026-08-24, PyPI JSON API):** the publish channel is **already
live** — `belay-harness` on PyPI is owned by the project's author, and every release
0.1.0 → 0.21.1 has wheel + sdist uploads whose timestamps match the CHANGELOG dates (first
upload 2026-07-18; 0.21.0/0.21.1 on 2026-08-20). The tag-driven `release.yml` →
trusted-publisher pipeline (`RELEASING.md:26-68`) has been working since v0.1.0. So the
problem is not "publish" — it is that **the docs and the CI do not reflect the live
channel**, and the stranger-timed metric has never been measured. The checklist's
"`belay-harness` v0.1.0 published" wording (`CHECKLIST.md:195`) is stale in both version
and status.

## Goals & Success Metrics

1. **Artifact-path proof.** CI builds the wheel + sdist via `uv build` and installs the
   wheel into a fresh venv on **both** macOS and ubuntu-24.04; `belay --help`,
   `belay sandbox check`, and a minimal capture→verify roundtrip all succeed from the
   installed artifact. *(Nothing in CI does this today.)*
2. **Quickstart is true.** The README install section is the live path: `uv tool install
   belay-harness` / `pipx install` / `pip install` with the "until then, run from source"
   caveat gone, the Docker quickstart retained, and the develop/from-source section kept
   as the contribution path. A docs-consistency test asserts the README no longer carries
   the stale caveat and that its install commands match the real distribution name and
   entrypoint.
3. **The metric is measured.** A reproducible time-to-first-verdict runbook ships; the
   stranger-timed measurement is an operator step post-merge (R10 — a real external timer,
   never a CI number). The number is recorded where the checklist can see it.
4. **The record is corrected.** `CHECKLIST.md` L4's stale "v0.1.0" wording is corrected to
   what actually shipped (channel live since 0.1.0, 2026-07-18) with L4 marked ✅ only when
   its DONE criteria hold, per the checklist's own rule (`CHECKLIST.md:8-20`).

## User Personas & Scenarios

- **The stranger / design-partner evaluator** (the Phase-1 gate's "≥1 external
  self-hoster", `CHECKLIST.md:253-255`): lands on the README, follows the quickstart on a
  clean box, gets a verdict on a real trace in < 15 minutes. Today they hit "until then,
  run from source" and leave.
- **The PH launch audience**: the README is the demo; the install line must not read like
  vaporware.
- **The maintainer (aliz)**: cutting the next release already auto-publishes
  (`RELEASING.md:26-44`); after this unit, CI tells them the artifact is good *before* the
  tag is pushed, not after.

## Requirements

### Must-have

- **M1 · Artifact build + install verification in CI.** A dedicated `install` job (or
  equivalent, per the confirmed decision: dedicated job) on **macOS and ubuntu-24.04**:
  `uv build` → fresh venv → `pip install` the built wheel → assert `belay --help` exits 0
  and lists the CLI surface → `belay sandbox check` runs → a minimal capture→verify
  roundtrip (gated proxy → snapshot → `belay verify`) produces a verdict from the
  installed artifact. Deterministic, no live network dependency (the artifact is local).
  **M1 must also assert the version stamp from the INSTALLED artifact** —
  `belay.__version__ == <pyproject version>` — mirroring the docker image test's stamp
  check (`tests/test_docker_image.py:111-119`): a wheel built with a stale version would
  install fine but stamp the wrong version into `phase0` ledgers (the version-drift
  history recorded in `src/belay/__init__.py:3-14` shows this class of defect is real).
- **M2 · Zero-dependency contract survives the artifact path.** The built wheel carries
  only `src/belay` (`pyproject.toml:67-68`), the import guard stays green
  (`tests/test_import_guard.py`), and the install test asserts the installed package
  imports without third-party deps (fresh venv + `dependencies = []` is the whole story).
- **M3 · README quickstart flip.** Rewrite `README.md:54-62`: delete the "until then, run
  from source" caveat; make `uv tool install belay-harness` the headline, `pipx`/`pip`
  alternates; keep the distribution-name note (`README.md:60`); keep the Docker quickstart
  (`README.md:64-84`) and the Develop section (`README.md:287-297`).
- **M4 · Docs-consistency test.** A test asserts: README contains no "run from source"
  install caveat; README's install command names match `pyproject.toml` (`belay-harness`,
  entrypoint `belay`); the README quickstart and `RELEASING.md` agree on the distribution
  name. (The repo's convention is machine-checked claims.)
- **M5 · Timing runbook.** A short runbook (`docs/planning/pypi-publish/` or
  `docs/`-adjacent) specifying: clean-box preconditions (macOS or Linux, fresh Python
  3.10–3.12), the exact commands (`uv tool install belay-harness` or `pipx`/`pip`, then a
  minimal capture→verify), what "time-to-first-verdict" measures (first successful
  `belay verify` verdict), and where to record the number (the checklist L4 entry /
  PHASE0-style record). The measurement itself is an operator step post-merge.
- **M6 · Checklist wording correction + completion contract.** `CHECKLIST.md` L4: correct
  "`belay-harness` v0.1.0 published" to reflect the live channel (published since 0.1.0,
  current 0.21.1), append a Progress-log row per the checklist's convention
  (`CHECKLIST.md:266-271`), and mark L4 ✅ only when DONE holds. **Completion contract,
  stated explicitly:** the PR merges with L4's shipped work complete but its headline
  metric pending — the checklist entry reads "work shipped; the <15-min stranger timing is
  the remaining clause, per the runbook" — and the operator marks ✅ after the timed run
  (M5). This keeps the item visible instead of silently lingering.

### Should-have

- **S1 · Stale-example fix in `RELEASING.md:22`** ("C7 → v0.2.0" is a stale example;
  correct to a real capability→version pair).
- **S2 · Live-channel note in the README install block**: one line stating the package is
  published (version stamp) — making "runs on the user's infra" legible at install time.
- **S3 · CI also asserts the sdist path** (install from the `.tar.gz`) or at least builds
  it (`uv build` already produces both; asserting the wheel is the must, sdist a should).

### Nice-to-have

- **N1 · A `--version` flag on the CLI** (the CLI currently has no `--version`;
  `src/belay/cli.py:2015-2017`). Not required by L4; flag as a candidate follow-up — the
  stranger's first "did it install?" check would be nicer with `belay --version`.

## Technical Considerations

- **Capability placement:** distribution for the Phase-1 launch block; not a C1–C9 engine
  capability. It *uses* the C1–C6 spine (the capture→verify roundtrip in the install test
  exercises proxy/snapshot/verify) but changes none of it.
- **Verdict impact:** **none** — no axis (A1/A2/A3), no trace format, no verdict contract
  changes. The coverage line rules that bind verdict *rendering* do not extend to
  packaging; the README keeps its existing honest coverage statement.
- **Zero runtime deps is load-bearing for the wheel** (`pyproject.toml:43-44`; enforced by
  `tests/test_import_guard.py:84-111`): the install test's fresh venv makes the contract
  observable — if a third-party import ever leaks into `src/belay`, the wheel install in a
  fresh venv fails loudly instead of silently resolving a dep.
- **Determinism:** the install test must be deterministic (no network beyond the local
  artifact). Live-PyPI installs are **documented operator steps**, not CI (confirmed
  decision).
- **CI shape:** new `install` job(s) on `macos-latest` + pinned `ubuntu-24.04`, following
  the existing `setup-uv` + `uv python install 3.12` pattern (`ci.yml`); `uv build` then a
  fresh `venv` + `pip install dist/*.whl` + the roundtrip, or a pytest module
  (`tests/test_artifact_install.py`-style) that does the same locally so the acceptance is
  a repo test (the docker-selfhost precedent: test module + CI job invoking it).
  **Clean-box definition:** CI pins Python 3.12 (consistent with all existing jobs); the
  stranger runbook (M5) allows 3.10–3.12 (`requires-python = ">=3.10"`,
  `pyproject.toml:13`) and records which was used.
- **Feasibility:** small unit — one test module + one CI job + README/RELEASING/checklist
  edits + a runbook. Roughly 1–2 days of owner time, low risk; the only genuinely
  uncertain deliverable is the stranger timing (R10, operator step by design).
- **Release flow untouched:** `release.yml` and `RELEASING.md` already publish on tag push;
  this unit adds no new publish machinery. Next release continues to auto-publish.
- **Guardrails:** no agent framework, no LLM judge, no raw-data egress (the wheel is
  already public; install is on the user's box). BYOK posture unchanged.

## Risks & Open Questions

- **R10 (solo-founder bandwidth, `ROADMAP.md:369`)** — the stranger timing needs a real
  external person; the runbook ships, the number is recorded post-merge. Named, not
  papered over: the checklist is marked ✅ only when the number is actually measured.
- **Name availability** — resolved by measurement: `belay-harness` is the project's own
  live package on PyPI (verified 2026-08-24). The `belay` name remains the unrelated
  MicroPython tool (`pyproject.toml:6-8`); nothing to do.
- **Trusted publisher** — resolved by measurement: uploads have succeeded for 22 releases,
  so the PyPI trusted publisher (`RELEASING.md:52-68`) is configured and working. Nothing
  to do.
- **`uv tool install` vs `pipx` vs `pip` behavior on a clean box** — the fresh-venv CI
  check proves the `pip` path; `uv tool install`/`pipx` are thin wrappers over the same
  wheel and are verified in the operator live-install step. Flagged as residual
  (a wrapper-level regression would be caught post-merge, not by CI).
- **Open:** whether the install-test roundtrip can reuse the docker test's roundtrip
  fixture (gated proxy + snapshot + verify) or needs its own minimal fixture — decide in
  the plan.

## Out of Scope

- **Cutting/publishing a new release (0.22.0)** — the channel is proven; the next tag-push
  auto-publishes. No version bump in this unit unless the checklist needs one to be true.
- **GHCR publish job** — a separate deferred slice by the cross-doc "SAME image" rule
  (`CLAUDE.md:40-41`, `RELEASING.md:16-18`, `CHECKLIST.md:182-184`).
- **`belay --version` flag** (N1) — candidate follow-up, not L4.
- **Docker quickstart changes** — L3 shipped it; this unit only keeps it intact.
- **Any verdict, trace-format, sandbox, or replay-engine change.**