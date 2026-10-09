# Aspect spec: probe

**Source:** `docs/planning/claim-author-live-probe/prd.md` (requirements P1–P6, S1–S2, N1).

## Problem slice

Make R-D's deferred evidence run cheap and honest: re-verify the two banked run-3
trajectory-FAIL traces through the real CLI with the shipped reference claim author, and
commit the observed `last_abstention` sub-cause plus any A3 verdict — whatever it says.

## In-scope requirements

- P1 Freeze protocol (Rule D): invocation script committed first, containing no result
  (grep-checked); the run happens once; verbatim stdout committed next, whatever it says;
  the freeze commit hash named in the findings.
- P2 Wrapper-record trick: `--claim-author` is a recording wrapper (marker byte per
  invocation + wall start/stop) that `exec`s the shipped `reference_claim_author` module;
  "the author ran" is an observed fact, asserted `invocations >= 1`.
- P3 Surface: `belay verify <trace> --manifest-dir <stem>.manifests --claim-author <wrapper>
  --server node <fs-server> '{workspace}' --json` — the `{workspace}` token and
  `--manifest-dir` are mandatory (the two documented operator-error hazards).
- P4 Traces: `~/dev/at/holder/belay/mint/cm6/batch/trace-django__django-{11422,14382}.jsonl`
  (referenced by absolute path; never copied into the worktree).
- P5 Manual-marked probe test (never CI; fails with instructions when the model env is
  unset, never a skip).
- P6 Findings note: observed sub-cause(s), A3 verdict(s) or silence, author wall-times,
  headroom vs the 60 s cap, the R-D answer, named follow-up.
- S1 Author wall-time recorded via the wrapper (start/stop around the exec).
- S2 Findings carry a one-line triage-timeout reading (observation only).

## Out-of-scope boundaries

No verdict/status/reduction/exit-code/gate/corpus mutation; no model choices beyond the
BYOK reference author; no knob (that's the gated `timeout-knob` aspect); no changes to
`src/belay/`; the corpus labels remain the owner's alone.

## Acceptance criteria

1. The frozen script contains no result shape (grep-checked: no `AUTHOR_TIMED_OUT`, no
   `NO_CHECK_AUTHOR`, no `claim` key, no exit-code literals from the run) at its commit.
2. The owner-run probe completes once; verbatim `.out` files are committed in the commit
   after the freeze.
3. The manual test asserts, per trace: the wrapper marker grew (`invocations >= 1`) —
   the axis engaged — and the `verify --json` document carries a `claim` record whose
   shape is one of: `NO_CHECK_AUTHOR` with a `sub_cause` from the closed vocabulary
   (incl. `AUTHOR_TIMED_OUT`), D3 `claim_silence` (exit 0), or an A3 WARN/FAIL record.
   A `claim` key absent with an author configured is a failed probe.
4. `FINDINGS.md` states the R-D answer in the project's evidence language (finding vs
   non-finding), quotes the observed sub-cause verbatim, and states whether the
   `timeout-knob` aspect's trigger (≥1 `AUTHOR_TIMED_OUT`) fired.
5. The suite stays at 2895 passing (45 skipped, 14 deselected) at the end of the unit.

## Dependencies & sequencing

Depends on nothing unshipped (A3, sub-cause surfaces, and the ledger threading are live at
v0.40.0). Runs after the manual-marked test + frozen script are committed. The
`timeout-knob` aspect depends on this aspect's evidence (≥1 `AUTHOR_TIMED_OUT`).

## Open questions / risks

- Model availability on probe day (quota/network) → `AUTHOR_EXITED_NONZERO` is a valid
  observation but does not test R-D; stated as such; a re-run is the owner's declared
  decision.
- Replay drift vs run 3 (the committed ledger rows are the correctness anchor; divergence
  is itself a finding, recorded not papered over).
- Wall cost: each verify replays its trace before authoring (~1 author invocation +
  full-trace replay per trace); bounded by the e2e precedent's 600 s-per-process wall.