# Spec — record-corrections

**Aspect of:** `corpus-trajectory-banking` · `docs/planning/corpus-trajectory-banking/prd.md`
(requirement S2, goal 4's no-backfill statement).

## Problem slice

The committed record must close the loop the way the repo's honesty discipline demands:
the spec that described the old namespace is corrected, the AUDIT's follow-up line records
the closure, and the changelog/status entries state what the fix did — and did **not** do.

## In scope

- The **release step** (repo convention, `RELEASING.md`): bump `version` to `0.26.0` in
  `pyproject.toml`, move the `[Unreleased]` notes into a dated version section in
  `CHANGELOG.md`, and push the `v0.26.0` tag once CI is green on both platforms + the
  docker job. The release commit is part of this unit, matching the `release: v0.x.0`
  commit pattern of every shipped capability.
- `docs/planning/trajectory-success-invariant/corpus-trajectory/spec.md` — the ingestion
  section gains the namespace fact: trajectory cases mint `f"{source_trace_id}-trajectory"`
  (instance-level namespace, disjoint from per-turn `-turnN`), with the collision rationale
  and the plan edge-case row 134 now satisfied.
- `docs/planning/mint-shell-toolset-run/audit-and-publish/AUDIT.md` — the corpus-banking
  finding's follow-up line records the closure (fixed in v0.26.0 by this unit) while the
  historical finding stands (zero of 23 banked — the s6 captures are gone; nothing
  backfilled).
- `CHANGELOG.md` — entry in the repo's existing format (check the most recent release
  block's shape before writing).
- `docs/STATUS.md` — append entry (newest first, per the file's convention) stating: the
  namespace split, the two shapes now coexisting, the unrestorable-pre-state stay-unbankable
  contract, and the no-backfill fact.
- `docs/technical/PHASE0_RESULTS.md` — if and only if the correction policy there allows it:
  the corpus-banking finding's "recorded follow-up defect" line gains a pointer to the
  closure. Read the file's own correction discipline first; a historical record that must
  stand unedited stays unedited.

## Out of scope

- Re-editing any published number (`11/60`, `precision 0.00`, `1/15`, `4/16`, `recall n/a`).
- Rewriting the mint's audit verdicts or the PHASE0 gate decision.

## Acceptance

1. Every doc changed in this aspect is checked into the same PR as the code, and each says
   the fix's value is forward-looking — nothing claims the mint's 11 TPs entered the corpus.
2. The `-trajectory` id format is stated identically in spec.md, CHANGELOG.md and
   STATUS.md (one fact, three surfaces).
3. `tests/test_docs*.py`-style machine checks (if any exist for these files) stay green;
   any docs that are machine-checked are updated in the same commit as the prose.
4. No line in PHASE0_RESULTS.md is rewritten in a way that changes a number; the correction
   discipline section of that file governs.

## Dependencies & sequencing

Last aspect — after the code and tests land (aspects 1–2), so the record states shipped
facts. The CHANGELOG entry format should be read from the repo before writing.

## Open questions

None.