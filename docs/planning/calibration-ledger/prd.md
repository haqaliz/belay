# PRD — C10 slice 2: the calibration ledger

**Status:** prioritized next (the C10 moat half) · owner confirmed 2026-09-22 · not started
**Capability:** `docs/technical/CAPABILITY_ROADMAP.md` → C10 (slice 2; slice 1 shipped in
v0.36.0).
**Source:** the merged C10 PRD (`docs/planning/jev-triage/prd.md`) — its "Eval data
captured" promise, now being built.

---

## Problem

Slice 1 (v0.36.0) records per-turn triage scores in shadow mode, and that is all it
does: **nothing measures whether the triage model's "calibrated confidence" actually
predicts a real violation on real Belay verdicts.** Jev's calibration is a vendor claim
until the ledger measures it. Without the ledger, the budget cannot be tightened
honestly — the PRD's own rule: *"until then the safe budget is shadow mode"*.

## Approach

A **pure re-render** ledger, mirroring the `phase0 report` discipline
(`cli.py:2995-3031`; "a pure re-render: no replay, no re-verification, no clock read"):

- **`belay triage-ledger <verify-json>`** — reads a stored `belay verify --json`
  document (the `triage.scores` rows + the `turns` verdicts, already paired by
  `ordinal`) and renders the calibration measurement: reliability curve, ECE, and the
  decision-relevant number — **at each candidate threshold, how many true violations
  would have been skipped and how much budget would have been saved**. Deterministic,
  byte-identical re-render, `--json` + text pair.
- **The violation column** (owner-confirmed): per-turn **reduced FAIL** (the corpus
  precedent: positive = FAIL alone, WARN folded with PASS — `corpus/metrics.py:236`),
  with **UNVERIFIED turns excluded** and the denominator stated. Never a rate over a
 100%-UNVERIFIED column (the R6 false-zero defense, `phase0/report.py:65-75` shape).
- **The section extension** (the named v0.36.0 follow-up, owner-confirmed): the
  `triage` JSON section gains skipped turns' scores in budgeted mode, each row marked
  `"skipped": true` — one computation, two renderers (`triage_surfaces.py:228-263` +
  `cli.py:1456-1488`). Shadow mode is unchanged.
- **Honest small-n posture:** the demo capture (all-PASS) validates the mechanics and
  contributes zero violation rows — the ledger prints its denominator and never
  presents small n as a base rate. FAIL rows come from synthetic fixtures until the
  mint's second run (the owner's S-1 decision) supplies real volume.

## Requirements

**Must**
- `belay triage-ledger <verify-json> [--json]` — pure re-render; fail-closed exit 2 on
  a missing/malformed document (the `_cmd_phase0_report` load shape,
  `cli.py:3007-3022`).
- The calibration math, stdlib only, deterministic: reliability curve (confidence
  bins vs observed violation rate), ECE, threshold sweep (violations-skipped ×
  budget-saved per candidate threshold; top-N sweep too).
- Violation column = reduced FAIL per turn; UNVERIFIED excluded with the denominator
  stated; a 100%-UNVERIFIED column refuses to print a rate (named refusal).
- The `triage` section extension: skipped turns' scores with `"skipped": true` in
  budgeted mode; shadow mode byte-unchanged; the refutation identity test stays green.
- `--json` output for the ledger (machine-consumable); widen the flag-parity `--json`
  row in the same commit (`tests/test_cli_flag_parity.py:114`).
- Zero-LLM guard green (the calibration module lives under `src/belay/verify/` or a
  sibling with stdlib-only imports).

**Should**
- A text renderer for the ledger (reliability bins, ECE, the decision table) in the
  house style (`phase0/report.py` register).

**Won't (this slice)**
- **Budget auto-tuning** — the ledger *informs* the budget; the operator still sets the
  knobs. "The ledger earns a tighter budget" is a human decision on this measurement.
- **Aggregation across many verify documents** — one document per invocation; a
  directory-level aggregate ledger is a follow-on (the C9 multi-trace deferral shape).
- The mint re-run (the owner's S-1 decision; supplies the ledger's real volume).
- Live-model CI; per-model reference authors; any verdict authority for the triage
  model (unchanged from slice 1).

## Acceptance (test-first)

1. **Mechanics on real data:** the demo capture verified with a stub triage author
   (shadow mode) → `belay triage-ledger` renders with 0 violations, the honest
   denominator (7 turns, 7 decided), exit 0.
2. **Exact math:** a synthetic document with known (score, confidence, verdict) rows
   pins the reliability bins, the ECE value, and the threshold-sweep table exactly
   (byte-pinned fixture).
3. **UNVERIFIED excluded:** a document mixing FAIL/PASS/UNVERIFIED rows states the
   excluded count and the denominator; a 100%-UNVERIFIED document refuses a rate with
   a named cause and exit ≠ 0.
4. **Deterministic:** the same document re-renders byte-identically (the phase0 report
   discipline, pinned by test).
5. **Section extension:** budgeted mode carries skipped turns' scores marked
   `"skipped": true`; the budgeted-mode tests re-pin; the shadow-mode section and the
   on/off identity test are byte-unchanged.
6. **Guards:** zero-LLM guard green; flag-parity guard green with the `--json` row
   widened; full suite green.

## Eval data captured

The ledger itself: per-turn (score, confidence) paired with the execution-grounded
verdict (reduced status, cause), the reliability curve, ECE, and the
violations-skipped × budget-saved sweep. It is pure Belay measurement — the project's
own thesis applied to the triage vendor. Real volume arrives with the mint's second
run; until then the denominator is stated and small n is never a base rate.

## Dependencies

Slice 1 (v0.36.0): the `triage` section + shadow mode (`verify/triage_surfaces.py`,
`verify/triage_budget.py`), the closed cause vocabulary, the refutation pins. The
`phase0 report` pure-re-render precedent (`phase0/ledger.py`, `phase0/report.py`).
The demo capture fixture (`tests/test_demo_capture.py:295-323`).

## Honest limits

The ledger measures **prediction of violations on the turns actually replayed** —
calibrated ≠ caused; a high-confidence FAIL proves nothing about other turns. UNVERIFIED
turns are excluded because there is no verdict to calibrate against; the excluded count
is stated. A tiny or all-PASS set renders honestly (denominator printed), never a
fabricated curve. **No published number moves** from earlier units (`11/60 = 18.3%`,
`precision 0.00`, `1/15`, `4/16`, `recall 0.00` stand unedited).

## Open questions

- None blocking: surface, violation column, and section extension confirmed by the
  owner 2026-09-22.

## Out of scope

Budget auto-tuning; multi-document aggregation; the mint re-run; anything that gives
the triage model verdict authority; raw-state egress (nothing new leaves the box —
scores and verdicts are both local).