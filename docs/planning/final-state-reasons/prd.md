# PRD: final-state-reasons

**Phase:** 1 follow-on (C8, A3 claim axis) · **Capability:** follow-on slice of C8 (no new C-id)
**Status:** draft for review gate · **Slug confirmed by owner:** 2026-10-02

## Problem Statement

`evaluate_claim` (`src/belay/verify/claims.py:380-390`) files ONE cause,
`FINAL_STATE_UNOBSERVABLE`, for four different situations (`_materialize_final_state`,
`claims.py:458-492`): (a) no `tools/call` turn exists, (b) `replay_turn` raised, (c) the last
turn did not replay (`reply.status != REPLAYED`), (d) it replayed but yielded no workspace.
The operator's fix differs per reason (the trace, the `--server`, the engine), and today
nothing says which applied. `claim-axis-legibility` (v0.39.0) closed the identical gap for
`NO_CHECK_AUTHOR` (8 sub-causes) and named this one as a follow-up (`prd.md` section 8).

Evidence is thin and stated: `FINAL_STATE_UNOBSERVABLE` appears in the committed `cm-stage1`
golden (`cm-stage1.json:63`), but no operator has asked for this. It is hygiene with no
roadmap dependency.

## Goals & Success Metrics

- Every `FINAL_STATE_UNOBSERVABLE` carries exactly one of four named sub-causes plus a
  one-line detail, on every surface the `NO_CHECK_AUTHOR` sub-cause already reaches.
- **Legibility only.** No verdict, status, reduction, exit code, gate or corpus outcome moves.
  No published number moves (`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
  `recall 0.00`, `3/93`).
- Predicted test delta **+20 to +35** (stated so the actual is compared; the last two units ran
  well over their predictions).

## User Personas & Scenarios

The engineer running agents unattended who reads `belay verify` or `phase0 report` and sees
`claim UNVERIFIED [FINAL_STATE_UNOBSERVABLE]`, and must decide whether to fix the trace, the
replay `--server`, or file an engine bug.

## Requirements

**Must**
- M1. Four sub-causes in the shared closed vocabulary `SUB_CAUSES` (8 -> 12):
  `FINAL_STATE_NO_TURN`, `FINAL_STATE_REPLAY_RAISED`, `FINAL_STATE_NOT_REPLAYED`,
  `FINAL_STATE_NO_WORKSPACE`. Each unambiguously maps to one reason in `claims.py:474-490`.
- M2. A pinned cause-to-sub-cause map: a sub-cause can only appear under its own cause
  (`AUTHOR_*` under `NO_CHECK_AUTHOR`, `FINAL_STATE_*` under `FINAL_STATE_UNOBSERVABLE`);
  `Abstention` construction rejects a mismatch.
- M3. One-line detail, at most 200 chars, never raw state or trace bytes. Reason (c) carries
  `reply.status` / `reply.cause` in the detail, not as extra vocabulary.
- M4. Threaded through the existing six surfaces via `sub_cause_fields`
  (`verify/json.py:319-334`): verify `--json`, phase0 ledger, corpus case, verify text,
  phase0 report, corpus show. Corpus schema stays v5.
- M5. Old ledgers/cases without a sub-cause render exactly as today. Never back-filled or
  inferred. The `cm-stage1` golden stays byte-identical.
- M6. Cause remains UNVERIFIED; never PASS. A caller-supplied `workspace=` still bypasses all
  four reasons. The `--no-claim-axis` identity holds.
- M7. The three pins the dig found are amended additively and named in the commit:
  `test_claim_subcause_surfaces.py:113-127`, `test_verify_claims_subcause.py:143-151`,
  `test_claim_vocabulary_guard.py` (8 -> 12 plus the map).

**Should**
- S1. `FINAL_STATE_UNOBSERVABLE` per-sub-cause tally in `phase0 report` only if it falls out of
  the shared rendering for free; otherwise out of scope.

## Technical Considerations

Axis: A3 only. Replay determinism is untouched: no replay behaviour changes, only what is
recorded about why a final state was unavailable. Producers: `_materialize_final_state`
currently returns `None` for all four; it must return a reason alongside (the
`last_abstention` pattern at `claims.py:413-423`, or a returned value; decided in the plan).
The case validator accepts null/string sub-cause and does not check vocabulary membership
(`corpus/case.py:425-430`), so no `case.py` change.

Corpus recompute: a different sub-cause must never decide MATCH/REGRESSION (as for
`NO_CHECK_AUTHOR`, `corpus/run.py` ~L695).

## Risks & Open Questions

- Q1. `test_verify_claims_subcause.py:143-151` parametrization was not read in the dig; read it
  in planning before amending.
- Q2. Reason (b) exception text can be long or multi-line; `_one_line` bounds it. The detail
  must not embed a path that leaks workspace content; state what is recorded.
- Q3. Sharing `SUB_CAUSES` widens a guard that was "pinned at eight"; M2's map is what keeps
  the sharing honest. Declined alternative: a separate vocabulary and type (leaves the 8
  untouched, needs a second guard and per-surface branching).
- R6/R7 not touched.

## Out of Scope

Classifier coverage and the 2026-08-12 vocabulary decision; `AUTHOR_TIMEOUT`; interop,
triage-ledger and console surfaces; re-deriving or back-filling any past run's reasons;
splitting reason (c) into per-replay-status vocabulary (the engine owns that vocabulary);
any new A3 firing.

## Aspects

1. `sub-cause-producer`: vocabulary, the M2 map, `Abstention` check, `_materialize_final_state`
   returning its reason, the guard (M1-M3, M6, guard half of M7).
2. `surface-threading`: the six surfaces, corpus recompute, goldens unchanged, e2e through the
   real CLI (M4, M5, rest of M7).
