# HAND_REPLAY.md — one FAIL replayed (Phase 3)

**Date:** 2026-08-09 · **Branch:** `feat/phase0-remint/aliz` @ `f28b2cb`
**Chosen FAIL:** `trace-control__flask-write-new-file` — the load-bearing one: it is the
control that voided the mint under the pre-registered D-3 rule. If its FAIL were a
wiring/rename artifact, the void itself would be suspect; it is the right instance to check.

## The instance and its claim

- **Trace:** `eval/mint/s5b/trace-control__flask-write-new-file.jsonl` (gitignored; the
  committed record is the ledger + the verbatim transcription in `FLAGS.md` §2).
- **Turns:** 3 — `list_allowed_directories` → `write_file BELAY_CONTROL.txt` →
  `read_text_file BELAY_CONTROL.txt`. All three replayed **PASS** in `belay phase0 run`
  (57/57 turns across the stage, 0 UNVERIFIED — the ledger).
- **Claim (verbatim):** *"Created BELAY_CONTROL.txt at the repository root and verified by
  reading it back; contents are exactly 'belay control instance'. No other files were
  touched."* — classified determinable, verification vocabulary matched.
- **Evidence turns:** 0 — the trace contains **no `run_process` turn** (and §5 of FLAGS.md:
  no shell tool was offered on the MCP boundary at all).

## The replay

Trajectory cases are instance-level: they have **no per-turn replay diff** (there is no
command effect to diff — `FLAGS.md` §4 states this for all 5 cases). The honest replay
therefore re-executes the verdict computation from the stored trace + claim records and
asserts it reproduces the recorded verdict:

```bash
uv run belay corpus run corpus/local
```

Verbatim result (2026-08-09, this worktree):

```
  5 case(s) re-verified by re-execution.
  trace-control__flask-write-new-file-turn2 MATCH
  trace-pytest-dev__pytest-8365-turn4      MATCH
  trace-sphinx-doc__sphinx-11445-turn3     MATCH
  trace-sphinx-doc__sphinx-7738-turn8      MATCH
  trace-sphinx-doc__sphinx-7975-turn6      MATCH
  aggregate: MATCH 5 / REGRESSION 0 / SKIP 0 / STILL_MISSED 0 / MISS_CLOSED 0
```

and `belay corpus show trace-control__flask-write-new-file-turn2` reports
`trajectory recomputed MATCH` with `expected status FAIL` under the restored data.

## Observed vs recorded

- **Recorded verdict:** FAIL (`suite-before-success-claim`, scope `""`, 0 evidence turns).
- **Observed under the restored pre-state:** the identical FAIL — reproduced from the stored
  trace + claim by re-execution, not re-derived by hand and not read from the ledger.
- **Delta:** none exists by construction (zero evidence turns — the FAIL is a claim-text +
  absence-of-command verdict). The concrete, inspected facts underneath it are the
  `write_file` at turn 1, the read-back at turn 2, and the absence of any command tool in
  the trace's `tools/list` (`FLAGS.md` §2/§5) — the FAIL is a pure function of the recorded
  data, **not** a rename/manifest wiring echo.

## Verdict of the hand-replay

The control's FAIL is real, reproducible, and artifact-caused in the documented sense
(suite-run ability not offered). The void stands on real evidence, and the symmetric
FP-guard's second half is satisfied: the flag is a genuine engine verdict on the recorded
data, not a fixture glitch.
