# Aspect spec — `audit-and-publish`

**Parent PRD:** `docs/planning/phase0-live-mint/prd.md` (must-haves 12, 13, 16;
should-haves 18, 19; nice-to-haves 20, 21)
**Sequencing:** last. Depends on `mint-execution` having produced ledgers + corpus cases.
**This aspect produces the actual deliverable.**

## Problem slice

A mint produces a ledger and a pile of `pending` corpus cases. Until a human labels them,
`belay phase0 report` prints the FP-rate as `n/a` (`corpus/metrics.py:126-156`) — and the
gate **requires** a stated FP rate. The number does not exist until the audit is done, and
the results document is the artifact everything else in the project rests on.

## In scope

1. **Hand-audit every flagged case** — `belay corpus list`, `belay corpus show <case-id>
   --corpus-dir <dir>`, then `belay corpus label <case-id> --label
   {true-positive|false-positive|unverifiable}`. No sampling (decided).
2. **Record each TP's root cause**, so the **≥3 _independent_** requirement is auditable by
   a reader rather than asserted. Three flags from one mis-annotated tool = **one** finding.
3. **Hand-replay one FAIL end-to-end**, confirming its state delta is real and not an
   artifact of the rename/manifest wiring. Documented.
4. **Fill `docs/technical/PHASE0_RESULTS.md`** — all 18 fields, plus:
   - the violation rate **with its denominator**, never a bare percentage;
   - the **instance-pool composition** published beside the number (the django/sympy
     concentration is a stated limitation);
   - the UNVERIFIED breakdown, **every instance traced to a named cause**;
   - the FP rate with coverage stated beside it;
   - the "reproducible" clarification: the *mint* is a fresh observation; the
     *ledger → report path* is fully reproducible from fixed traces.
5. **Write the decision** — `PROCEED` or `PIVOT`, against the pre-registered criteria, in
   the document, plainly, whichever way it goes.
6. **RUNBOOK corrections** (`docs/planning/phase0-corpus-run/RUNBOOK.md`), all five:
   - `:35` "NOT YET BUILT" → the driver shipped in v0.3.0;
   - `:60-71` invalid `python -m belay.proxy <server> -- <agent-runner>` argv (no `--`
     separator; the proxy does not launch an agent-runner);
   - `:54` false claim that traces are named `trace-<instance-id>.jsonl`;
   - `:183` wrong `belay corpus show corpus/local/<case-id>` form;
   - `:58` "all 300" vs `:79` "≥50".
   Plus: document the rename bridge and the two-batch (filesystem/shell) procedure.
7. **Reconcile the two gate statements** — `ROADMAP.md:117-121` vs
   `PHASE0_RESULTS.md:92-100`. One canonical, the other points at it.
8. **Update `CLAUDE.md` status** and the roadmaps to reflect the gate outcome.

## Out of scope

- Re-running the mint to get a different number. If a defect requires a re-mint, that is
  `mint-execution`, and the discard is **disclosed** in the results.
- Building report→markdown tooling (transcription is manual and that is acceptable at n=1
  gate; nice-to-have at most).
- Any claim beyond what the replay actually checked (`README.md` honest-coverage limits).

## Acceptance criteria

1. Every flagged case has a human label; **no case remains `pending`** when the FP rate is
   published. Verifiable via `belay corpus list`.
2. `belay phase0 report` prints an FP rate that is **not** `n/a`.
3. `PHASE0_RESULTS.md` has **zero** remaining `TO-BE-FILLED` markers.
4. ≥3 TPs are recorded **with distinct root causes**; if fewer, the document says PIVOT.
5. The violation rate never appears without its denominator anywhere in the document.
6. `INSTRUMENT SUSPECT`, if it fired, is reported as UNVERIFIED-of-the-experiment and
   **never** as a 0% violation rate.
7. The five RUNBOOK defects are fixed, and the corrected procedure is followed end-to-end
   by the author at least once (it is the reproduce-the-number artifact — if it does not
   work, the number is not reproducible).
8. A reader who disagrees with the conclusion can locate every underlying case and
   re-derive the number from the committed ledger.

## Dependencies

- `mint-execution` outputs (two ledgers, corpus cases).
- Existing CLI: `belay corpus list/show/label/score`, `belay phase0 report`.

## Risks / open questions

- **Audit volume is unknown** (R10). If it proves infeasible, the sampling rule is
  revisited **explicitly and stated in the results**, never silently.
- **Auditor bias** — the person labelling wants the premise to hold. The control instances
  and the hand-replayed FAIL (from `mint-execution`) are the structural counterweight;
  recording root causes makes the independence claim checkable by others.
- **A PIVOT is a real possible outcome** and must be written with the same care as a
  PROCEED. The roadmap explicitly frames discovering it in week 4 as success
  (`ROADMAP.md:118`).
