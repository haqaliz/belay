# Aspect: stranger-timing

Part of `docs/planning/pypi-publish/prd.md` (launch checklist L4). The runbook for the
remaining DONE clause: time-to-first-verdict < 15 minutes, measured by a stranger.

## Problem slice

L4's headline metric — *"time-to-first-verdict < 15 minutes measured by a stranger
following the quickstart"* (`CHECKLIST.md:197-199`) — has never been measured and cannot
be measured by CI (R10: it needs a real external person on a clean box). Without a
runbook the measurement is ad hoc and the number is not reproducible; with one, the
post-merge operator step is a 20-minute task with a recordable result.

## User outcome

The launch gate's "a stranger can install and run Belay in under 15 minutes"
(`CHECKLIST.md:250`, `ROADMAP.md:277`) has a defined, reproducible way to be measured —
and the number, once taken, lands in the checklist the operator can mark L4 ✅.

## In-scope requirements (from PRD M5, S2)

- `docs/planning/pypi-publish/stranger-timing/runbook.md`:
  - clean-box preconditions: fresh macOS or Linux machine (or VM), Python 3.10–3.12
    (`requires-python = ">=3.10"`, `pyproject.toml:13`), uv recommended (`uv tool
    install`) with `pipx`/`pip` alternates; record which path and Python were used;
  - the exact commands, matching the README quickstart (headline:
    `uv tool install belay-harness`, then `belay --help`, then the minimal
    capture → verify example — the runbook either reuses the README's example or
    points at the roundtrip fixtures' shape: gated proxy over a tiny deterministic
    server, snapshot, `belay verify` → first verdict);
  - the definition of "time-to-first-verdict": stopwatch starts at the first
    command, stops when `belay verify` prints its first verdict line with the
    coverage line — state it explicitly so two timers agree;
  - the record step: write the number, environment, install path, and date into the
    checklist L4 entry (the completion contract) and the progress log;
  - the operator live-install check (PRD's documented-live-check decision): on the
    clean box, `uv tool install belay-harness` installs the LIVE PyPI package (not a
    local build), `belay --help` works, `belay sandbox check --scope <tmp>` works —
    the network-dependent verification that CI deliberately does not run;
  - an honest-claims note: n=1 is a measurement, not a guarantee; the number is
    recorded as such.
- The checklist completion contract already written by `quickstart-flip` is the
  record target; this aspect makes the measurement executable.

## Out of scope

- Taking the measurement (operator step after the PR merges — the runbook is the
  deliverable).
- Automating the timing in CI (impossible by decision: R10, and the live-PyPI path is
  network-dependent by design).

## Acceptance criteria

1. `runbook.md` exists and its install command matches the README headline install
   command — asserted by `tests/test_quickstart_docs.py`'s cross-aspect test, which
   must now pass (no longer skip) once this file exists.
2. The runbook defines the stop condition ("first verdict line printed by `belay
   verify`") unambiguously and names the record target (checklist L4 entry).
3. The runbook's sandbox-check and live-install steps name the honest limits (kernel
   ≥ 5.13 for Landlock on Linux; the macOS-path note where relevant).
4. Full suite green (`uv run pytest -q`); the docs test's runbook check stops skipping.

## Dependencies & sequencing

- Depends on `quickstart-flip` (the runbook matches the flipped README; the checklist
  completion contract is its record target). Build order A1 → A2 → A3.
- The live-install check needs the package on PyPI — already true (live since 0.1.0).

## Open questions / risks

- R10 is the whole risk: the measurement must be taken post-merge by a non-owner (or
  recorded as owner-measured n=1 — the PRD's hard question; the runbook supports
  either but the checklist records who timed it).