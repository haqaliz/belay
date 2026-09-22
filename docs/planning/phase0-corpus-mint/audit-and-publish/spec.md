# Aspect — `audit-and-publish`

**Grade: DOCS / evidence pack.** Owner decision work is **prepared, never judged**
(S-1: "the auditor is the owner; agents prepare evidence, never judgments" —
`phase0-remint/audit-and-publish/plan_20260809.md:24-29`).

## Problem slice

Make the second run's outcome **auditable by a stranger and decidable by the owner**:
an evidence pack in the committed precedent shape (the gate-mint's
`audit-and-publish/`), the record updated honestly, and the honest first paragraph
leading every write-up (MH-6: *"three places, because two have not been enough before"*).

## In scope

1. **Evidence pack** at `docs/planning/phase0-corpus-mint/audit-and-publish/`, copying
   the gate-mint precedent (`docs/planning/mint-shell-toolset-run/audit-and-publish/`):
   - `FLAGS.md` — every flagged turn + the trajectory table, from the committed ledgers
     (re-renderable via `belay phase0 report` / `phase0 combine` — byte-identical
     re-render is the reproducibility claim).
   - `AUDIT.md` — the owner's adjudication surface: every flag and every trajectory FAIL
     listed with its evidence, root-cause keys, independence off `(instance, tool)`.
     **Prepared, never judged.**
   - `HAND_REPLAY.md` — one flagged case (or one trajectory FAIL) hand-replayed
     end-to-end if any FAIL exists; if none exists, the file says so plainly.
   - `REPRODUCIBILITY.md` — a clean-checkout re-render of the ledgers is byte-identical
     to the committed outputs (mismatch → STOP), the `not-a-gate-run` sentence, and the
     engine-version delta stated (run 1: 0.33.0 → run 2: v0.37.0; the NOT_COVERED
     boundary means the UNVERIFIED rate across runs is **not comparable**).
2. **`docs/technical/PHASE0_RESULTS.md` entry** opening with the not-a-gate-run
   paragraph (MH-6): what this run is not (not a gate run, no Phase-0 number, no rate —
   Q1), then what it is: captures with denominators, banked cases, the A3 column,
   dispositions.
3. **STATUS.md entry + CLAUDE.md block + launch-checklist row** in the house style,
   with the honesty lines (no published number moves; a run that banks nothing is a
   recorded result).
4. The **S-1 decision surface**: the pack ends with the decision line the owner signs
   (continue / stop / re-scope), with the mandatory disclosure set — nothing decided
   here.

## Out of scope

- **Any judgment** — TP/FP/FN labels, precision/recall, or "violation" verdicts on any
  flag. The owner adjudicates on this pack.
- Any recorded-miss declaration (owner-only, schema v3).
- Re-deriving or editing any published number.
- The mint re-run decision itself — that is the owner's post-pack S-1 act.

## Acceptance

| # | Criterion |
|---|---|
| A1 | The pack's first paragraph states what this is not, in all three places (MH-6) |
| A2 | Every ledger line is re-derivable: `belay phase0 report` on the committed ledgers reproduces the committed outputs byte-identically (clean checkout) |
| A3 | Every flag and trajectory FAIL is listed with its evidence — zero flags dropped, zero judged |
| A4 | The engine-version delta and the NOT_COVERED boundary are stated where any rate appears (UNVERIFIED rates not comparable across runs) |
| A5 | No published number moves (M10); `precision`/`recall` read `n/a` wherever the corpus is scored |
| A6 | STATUS/CLAUDE/checklist entries land with the same honesty lines |

## Dependencies / sequencing

Depends on `mint-run` + `corpus-banking` (ledgers, banked cases). Final aspect of the
unit; no later aspect blocks on it.

## Risks

- **AUDIT.md judged by the preparer** — the strongest self-discipline risk in the unit.
  The file's header must restate S-1 and the evidence-grade split
  (*execution* vs *human adjudication*, never merged — the `mint-shell-toolset-run`
  discipline).
- A run that banked nothing still ships a full pack — the honest case is the more
  important one to write well.