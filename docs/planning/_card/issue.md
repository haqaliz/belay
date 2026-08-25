# Card: Launch demo, locked spec (launch checklist L7)

Source: inline brief from the checklist + `docs/ROADMAP.md:253-259` (the locked demo) +
the belay-next/live-console handoffs. No GitHub issue exists; the id lives in the branch and PR.

## Brief

L7 of `docs/planning/launch-readiness/CHECKLIST.md` — the locked launch demo: one repo,
one failing test, an agent told *"make the tests pass"* — it weakens the test and reports
success (a real, documented behavior, not a staged trick). Belay flags the exact turn
(A1 invariant, with the diff). Tagline: *"Your agent lied. Your dashboard didn't notice.
Mine did."* DONE = the demo is a self-contained repo + runbook any stranger can
reproduce; a fresh demo gif replaces the current one in the README; the verdict is
deterministic (A3 corroborates; never carries the demo).

**Ground truth that already exists** (dig): the deterministic verdict machinery is
pinned — `tests/test_launch_demo.py` proves A2 PASS + A1 FAIL → reduced FAIL, A1 the
sole catcher, with non-vacuity guards; the real corrupt-success shape is documented
(`s1p`, `pytest-5227`); the minting driver (`eval/minting_driver/` + `ClaudeCliModel`,
`claude -p` BYOK) drives real agents through the gated proxy with filesystem+shell MCP
servers; the console (C7, v0.23.0) renders traces + verdicts.

**Gaps found by the dig** (what L7 actually builds): (1) no self-contained demo repo or
runbook exists; (2) the current `assets/belay-demo.gif` has no generator (no recording
machinery in the repo); (3) the **compose console container serves a dead SPA** —
`console/server-static.mjs` has no `/api/*` routes, so `docker compose up console`
cannot render a trace or verdict (a real L6 gap that L7's demo needs closed); (4) the
"green Langfuse trace" side-by-side is aspirational — no Langfuse integration exists and
C9 export-back is deferred; today it must be an honest juxtaposition; (5) the roadmap's
"turn 7" wording doesn't match the implemented single-turn demo — the real-agent run's
flag turn is whatever it is, and the wording needs correcting to the committed capture's
truth.

## DONE criteria (from CHECKLIST.md L7 + the locked spec)

> ☐ L7 · Launch demo, locked spec — DONE = the demo is a self-contained repo + runbook
> any stranger can reproduce, a fresh demo gif replaces the current one in the README,
> and the verdict is deterministic (A3 corroborates; never carries the demo).

## Blockers / dependencies

- **Depends on nothing unshipped:** L1–L6 done; the console (v0.23.0) is the demo's
  visual; the A1 deterministic verdict is shipped and pinned by test; the minting
  driver + BYOK `claude -p` path exist (manual-marked, never CI).
- **Known caveats (named before the dig):** the compose console's missing API routes
  (a real gap the demo needs); the Langfuse side-by-side cannot be a real integration
  in this slice (C9 export-back deferred) — the honest first slice is a juxtaposition;
  a live agent run is manual/BYOK (real model spend, trajectory varies) — the
  *committed capture* is what makes the demo deterministic.

## Open questions (flag for the PRD)

- Demo repo location: inside the belay repo (`demo/`) vs a separate repo?
- Demo artifact: commit a real captured corrupt-success run (trace + snapshots +
  manifests) that CI replays deterministically, with the live reproduction as a manual
  runbook path?
- Close the container-console API gap in this unit so the compose console renders the
  demo?
- Langfuse side-by-side: honest juxtaposition (console red verdict beside the agent's
  transcript) with the real integration named deferred?
- Demo gif: Playwright-driven console recording (automated, reproducible) vs terminal
  recording of `belay verify`?

## Context links

- Checklist: `docs/planning/launch-readiness/CHECKLIST.md` L7 (lines 253–262), READY-TO-PUBLISH gate (285–292)
- Locked demo: `docs/ROADMAP.md:253-259`
- Demo ground truth: `tests/test_launch_demo.py`; `tests/test_verify_weakening.py:243-248`
- Capture path: `eval/minting_driver/` (loop/capture/bridge/composite), `eval/README.md:132-233`, `ClaudeCliModel` (`clients/claude_cli_client.py:345-447`)
- Console: `console/` (v0.23.0); the container gap at `console/server-static.mjs`
- Corrupt-success records: `CLAUDE.md` s1p block; `PHASE0_RESULTS.md` (pytest-5227)
- Assets: `assets/belay-demo.gif` (current, no generator), README:22-26, README:177