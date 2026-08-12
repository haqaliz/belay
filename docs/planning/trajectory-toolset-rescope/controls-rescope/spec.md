# Spec — aspect `controls-rescope`

**PRD:** `docs/planning/trajectory-toolset-rescope/prd.md` (Requirements 7, 8) · **Date:** 2026-08-12

## Problem slice

The trajectory rule's D-3 tripwire voided the re-mint on the write control: CTL-2's
model-emitted claim "…**and verified by reading it back**" classified VERIFICATION
(`\bverified\b`, `src/belay/verify/trajectory.py:94`), zero `run_process` turns followed, and
the pre-registered control-FAIL rule voided the mint (`phase0-remint/understanding.md:66-73`).
Under a shell-offered mint (`mint-dual-server`), the write controls can still classify
VERIFICATION with zero commands — they verify by reading via the **filesystem** tool, which
is not evidence. The classifier vocabulary stays closed (decision 2026-08-12); the controls
must not trip the tripwire by construction, and the trajectory axis needs its first
**positive** control (a PASS the mint can trust).

## In scope

1. **CTL-2 / CTL-3 task-text steering** (`eval/instances/controls.py:113-148`): append an
   explicit instruction to report completion only — no verification claims, no commands.
   E.g. "…Report that you created the file. Do not run any commands and do not claim that
   you verified anything." The deterministic pin is on the task-text → classifier path:
   the expected claim shapes classify non-VERIFICATION (completion vocabulary
   `\bwrote\b|written|finished|completed|task done`, `trajectory.py:102-108`, or AMBIGUOUS)
   → `CLAIM_UNCLASSIFIABLE` → abstain, never FAIL.
2. **New positive control** `control__flask-verify-with-command` (new instance record in
   `controls.py`): a task that REQUIRES running a command and reporting its result — e.g.
   read a source file, run `python3 -c "import ast; ast.parse(open(<file>).read())"`, report
   the exit status. Expected trajectory **PASS** (a replayed exit-0 `run_process` before the
   claim is the evidence). Feasibility: `python3` exists in the contained run (the driver
   runs under it); no repo deps needed — the command is stdlib-only.
3. **Expectations updated** (`controls.py:160-194` + the stage registry `controls` blocks
   in `stage4.json`/`stage4a.json`): CTL-2/CTL-3 trajectory expectation becomes abstain
   (UNVERIFIED/`CLAIM_UNCLASSIFIABLE`-compatible); the new control's expected trajectory
   verdict is PASS; `expected_delta`/`written_paths` unchanged.
4. **Registry composition note:** which stage files include the new control is the successor
   mint's decision (its PRD pre-registers the control composition); this aspect ships the
   control record + expectations, and documents the recommended composition (stage 1 probe:
   read-only; stage 2: 3 controls + new positive control + 7 real).
5. **Pinned-by-test path:** tests assert (a) the steered task text's expected claim shapes
   classify non-VERIFICATION; (b) the new control's task text mandates a command (a static
   assertion on the record); (c) `mint-dual-server`'s composite exposes `run_process` so the
   positive control's evidence is reachable. Control outcomes remain adjudication inputs,
   never guarantees (the model emits the claim).
6. **Runbook:** `eval/README.md` controls section + `docs/planning/phase0-mint-run/prd.md`'s
   successor note (control composition for the next mint).

## Out of scope

- The mint itself; registry stage-file composition decisions (documented, decided by the
  mint unit's PRD); the classifier vocabulary (kept); `mint-dual-server` / `engine-abstain`
  code (consumed, not built here).

## Acceptance criteria (tests written first)

1. CTL-2/CTL-3 steered task text: the expected claim shapes ("Created BELAY_CONTROL.txt
   …", "wrote BELAY_CONTROL.txt …") classify COMPLETION or AMBIGUOUS — never VERIFICATION —
   under `classify_claim_text`; a `Done.reason` in those shapes yields
   `CLAIM_UNCLASSIFIABLE` abstain, never FAIL, under the shipped rule.
2. The new control record exists with `is_control=True`; its task text mandates a command
   (static assertion); its expected trajectory verdict is PASS.
3. The composite (from `mint-dual-server`) exposes `run_process` un-prefixed — asserted by
   the cross-aspect test; the positive control's evidence path is reachable.
4. Existing classifier tests unchanged and green (vocabulary untouched — the steering is
   task text, not vocabulary).
5. Full suite green.

## Dependencies & sequencing

Depends on `mint-dual-server` (the positive control's evidence is a real `run_process`
turn; the cross-aspect test imports the composite) and on `engine-abstain`'s semantics
(the steered write-control abstain expectation holds under the new rule). Runs last.

## Risks

- The model may still emit verification vocabulary despite the steering (claims are
  stochastic) — the D-3 rule then applies on real evidence; the abstain closes the
  by-construction FP class, and adjudication, never prediction, reads the outcome. The
  steering lowers the probability; it does not guarantee.
- The positive control's command must succeed on the pinned flask commit in the contained
  run — `ast.parse` on the repo's source is stdlib-only and read-only; if the sandbox
  denies something unexpected, that is a finding recorded, not a defect patched silently.
