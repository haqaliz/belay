# The claim axis cannot say what it did — A3 coverage legibility

> Inline brief (no GitHub issue). Source: belay-next handoff 2026-09-25, picked after
> v0.38.0 (`corpus-mint-second-run`). A follow-on slice of shipped C8 (A3, v0.27.0).

## Brief

Make the A3 claim axis legible on every surface **without changing any verdict**.

1. **`--json` must separate "axis never ran" from "check executed and exited 0".** Today
   both are an absent `claim` key (`docs/STATUS.md:259-263`, recorded as a finding by
   `phase0-corpus-mint/a3-author`, never fixed): `evaluate_claim` returns `None` both when
   no author is configured and when the check exited 0 (D3 silence, confirmed). A reader
   cannot tell *checked* from *never checked* — the collapse `NOT_COVERED` was introduced
   to fix on A2. "Confirmed" must **never** render as, or next to, PASS: A3 never
   promotes, and the coverage line travels with it.
2. **`NO_CHECK_AUTHOR` gains a recorded sub-cause** — returned-none / raised:<ExcType> /
   timeout / non-zero exit / malformed reply / stdout cap — that lands in the phase0
   ledger and the corpus case. Run 3's `phase0-corpus-mint/audit-and-publish/AUDIT.md:89`
   could not say which happened: *"The ledger does not record which, and nobody observed
   it."*

## Acceptance tests (written first)

- The two states differ in `--json` (byte-stable snapshot).
- Each abstention sub-cause is pinned through a fake author.
- The `--no-claim-axis` identity refutation still passes **unmodified**.
- Old ledgers re-render byte-identically (additive field, absent-never-zero).
- Closed-vocabulary guard on the new sub-causes.

## Caveat

C8 is cuttable and last by design, so this is **legibility only**: no classifier change,
no new A3 firing, no verdict semantics change. The 10/12 `CLAIM_UNCLASSIFIABLE` in run 3
is a separate, named alternate — not this unit. No published number moves (`11/60 =
18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00`, `3/93`).
