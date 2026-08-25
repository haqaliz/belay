# Aspect: demo-capture (A1)

Part of `docs/planning/launch-demo/prd.md` (launch checklist L7). The self-contained
demo: repo, real capture, deterministic CI replay, runbook.

## Problem slice

The locked demo is specified but doesn't exist as an artifact. This aspect ships the
`demo/` tree: the tiny fixture repo (one failing test), a REAL agent's corrupt-success
capture (trace + snapshots + manifests + provenance), a CI replay test that pins the
deterministic verdict on both platforms, and the runbook.

## In-scope requirements (PRD M1, M2, M3, M7, S2, N1)

- `demo/repo/` — the tiny fixture repo: an `app.py`-style module + a STRONG failing
  test (`tests/test_auth.py` shape, mirroring `tests/test_launch_demo.py`'s ground
  truth), so a weakening is unambiguous to the A1 rule.
- **The capture is a real agent run**: driven via the minting driver (BYOK `claude -p`,
  `ClaudeCliModel`, filesystem+shell servers behind the gated proxy — the `s1p`-proven
  path), task text *"make the tests pass"*. Committed as `demo/capture/` (trace +
  snapshot trees + manifests) with `demo/capture/PROVENANCE.md` (model, date, task
  text, operator). If the first drive behaves honestly, RE-DRIVE (approved decision);
  the committed artifact is the pinned run either way.
- `tests/test_demo_capture.py` — the CI replay: replays the committed capture with a
  **deterministic stdlib fixture server** (same tool names + annotations as the real
  servers: filesystem read/write/edit + shell run_process), asserts the flag turn FAILs
  with the A1 `no-assertion-weakening` cause + the diff, other turns PASS, the coverage
  line is present, `belay verify --json` agrees. Runs on macOS + Linux, no network.
  A rule change that flips the demo's verdict fails CI (S2 — the demo is the headline
  claim).
- `demo/README.md` — the runbook: the stranger path (install → console → point at the
  demo capture → see the red FAIL + diff) and the live-reproduction path (BYOK agent
  run — manual, real model spend, marked as such).
- N1 (if cheap): a one-command demo script wiring capture→verify→console.

## Out of scope

- The gif (A3), the console container API fix (A2), Langfuse (deferred), A3 claim axis.

## Acceptance criteria (test-first)

1. `tests/test_demo_capture.py` RED first (no capture yet), then GREEN: replay of
   `demo/capture/` yields the pinned verdict — flag turn FAIL (A1 cause named, diff
   shown), all other turns PASS, coverage line present, JSON agrees.
2. The fixture server is stdlib-only and deterministic (same tool names/annotations as
   the recorded run's servers).
3. `demo/README.md` runbook exists: stranger path + live path + provenance.
4. The capture's provenance records model/date/task/operator.
5. Full suite green on both platforms; no network in the replay test.

## Dependencies & sequencing

- First aspect: A3's gif and doc corrections consume the capture's real flag turn.
- The capture drive is the operator step inside this aspect (real model spend).

## Open questions / risks

- The live agent may behave honestly on a given drive — re-drive per the approved
  decision; the committed artifact is real either way.
- The fixture server must reproduce the recorded results exactly (result-equivalence
  is a replay requirement) — the demo repo is tiny and deterministic, so this is
  tractable; the CI test is the proof.