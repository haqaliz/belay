# Spec: surface-threading

**Slice:** carry the sub-cause to every surface that already carries the `NO_CHECK_AUTHOR` one.

**In scope:** verify `--json` claim record, phase0 ledger, corpus case (schema stays v5),
verify text, phase0 report, corpus show, via `sub_cause_fields`; corpus recompute ignores a
sub-cause difference for MATCH/REGRESSION; amend the two surface pins additively.

**Out of scope:** interop, triage-ledger, console; back-filling old ledgers.

**Acceptance (failing tests first):**
- Each surface renders the sub-cause and detail for a `FINAL_STATE_UNOBSERVABLE` record.
- Records without a sub-cause render byte-identically to today; `cm-stage1.report.txt` golden
  unchanged (run `test_claim_ledger_goldens.py` unmodified).
- Corpus schema version still 5 (`test_schema_version_is_still_5`); a case differing only in
  sub-cause is a MATCH.
- One end-to-end test through the real CLI per reason where reachable, else a stated gap.
- `--no-claim-axis` document identity holds.

**Dependencies:** `sub-cause-producer`. **Risk:** exact-record pins amended additively (M7).
