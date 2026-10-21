# PRD — triage budget suggestion

**Issue:** #53 · **Slug:** `triage-budget-suggestion` · **Branch:** `feat/53/aliz` (stacked on #52)

## Problem

The calibration ledger measures every candidate threshold but the operator still reads the
sweep by eye and sets `--triage-threshold` by hand. Auto-tuning was deferred by name at
`calibration-ledger` (2026-09-22). Applying a budget automatically would violate the
product's rule that the ledger *informs* and a human decides.

## What ships

`belay triage-ledger ... --suggest-budget` — a **recommendation**, never an application.

- Over the merged rows, consider the existing `SWEEP_THRESHOLDS` (0.1 … 0.9).
- Recommend the threshold with **zero violations skipped** and the largest `budget_saved`;
  ties go to the higher threshold.
- Text: `suggested budget: --triage-threshold 0.7 — skips 2/5 (40.0%), 0 violations skipped`.
- When **every** candidate skips at least one violation: no threshold is recommended; the
  line says so and names the least-bad candidate (lowest violation count, then lowest
  threshold).
- `--json`: an additive `suggestion` key **only when the flag is set**:
  `{threshold, skipped, violations_skipped, budget_saved}` or
  `{threshold: null, skipped, violations_skipped, budget_saved: null, reason}`.
- Without the flag: text and JSON are **byte-identical** to today (existing snapshots pass).
- Zero decided rows: the existing `NO_DECIDED_ROWS` refusal is returned unchanged; no
  suggestion is fabricated from a zero denominator.

## Non-goals

- No automatic application, no writing of flags/config, no top-N recommendation (threshold
  only; named in the docs), no new sweep grid, no new command, no replay.
- No division-by-zero guess: an empty column never suggests.

## Acceptance criteria

1. A ledger whose violations all score ≥ 0.9 suggests the highest threshold that still skips
   nothing violated, with the honest skipped/budget numbers.
2. A ledger where some candidate thresholds skip violations picks only among the zero-skip
   candidates.
3. A ledger where every candidate skips a violation returns `threshold: null` with a reason
   naming the least-bad candidate.
4. Without the flag, text and JSON are byte-identical (the two existing snapshots pass
   unmodified); with it, the text gains exactly one line and the JSON exactly one key.
5. Zero decided rows: refusal unchanged, exit 0, no suggestion key.
6. Deterministic: the same rows and flag render byte-identically twice.

## Risks

- **R-a:** a recommendation on n=1 reads like calibration. Mitigated: it is presented as
  "suggested", the denominator is printed, and nothing is applied.
- **R-b:** ties are arbitrary. Mitigated: a stated rule (higher threshold) and a test.
- **R-c:** a threshold outside the measured grid could save more. Accepted: the suggestion
  never proposes a value the ledger did not measure.

## Open questions

- 🟡 **Q1:** also suggest top-N? Proposed: no — threshold is the budget's primary knob and
  the two have different failure shapes; name it as the follow-up.
