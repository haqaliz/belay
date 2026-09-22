# AUDIT — the owner's adjudication surface (run 2)

> **This is not a gate run, it produces no Phase-0 number, and it is not a result
> about agents.** It is the stage-1 probe of the declared second run, stopped by its
> own pre-registered gate.
>
> **S-1: the auditor is the owner. The preparer lists evidence and applies no
> TP/FP/FN words.** Two evidence grades, never merged: *execution* (what the committed
> ledger and the engine's own replay established) and *human adjudication* (the
> owner's, below the line, not yet written).

## Evidence — execution grade

**There is nothing to adjudicate as a detection.** The run produced 0 per-turn FAILs,
0 trajectory FAILs, 0 A3 FAILs (`FLAGS.md`). No flag was dropped, because there were
none. No case banked (`corpus-banking/FINDINGS.md`).

What the owner can adjudicate is **why the instrument abstained**. Every abstention,
with its root-cause key and independence key `(instance, tool)`:

| Instance | Turn(s) | Tool | Cause (ledger) | Root-cause key (preparer's derivation, `STAGE1_FINDINGS_RUN2.md`) |
|---|---|---|---|---|
| CTL-1 | 2 | `read_text_file` | `replayed but effect unverified` | composite-transport snapshot correlation: tool absent from the latest `tools/list` (seq 13, shell), present in seq 12 (filesystem) |
| CTL-4 | 2 | `read_text_file` | `replayed but effect unverified` | same key |
| CTL-4 | 1 | `run_process` | `UNRESTORABLE_SNAPSHOT_FAILED` | restore failure. Pre-existing: the 2026-08-12 gate run carried 16/122 |
| CTL-1, CTL-4 | instance | — | trajectory + claim `CLAIM_UNCLASSIFIABLE` | a control's completion-shaped claim is outside the closed vocabulary by design |

Distinct root-cause keys: **3**. Distinct `(instance, tool)` pairs: **3**
(`CTL-1/read_text_file`, `CTL-4/read_text_file`, `CTL-4/run_process`).

The root-cause key for the 4 effect abstentions is a **derivation** (an offline
`annotation_for_turn` probe over the committed traces). No re-execution established
it. It is execution-adjacent and has not been adjudicated.

## Pre-registered reading

- Void (D-3)? **No control FAILed.** Both are `NO_VERIFIABLE_TURNS`.
- `INSTRUMENT SUSPECT`? **Yes** → the pre-registered STOP fires; stage 2 does not
  launch.
- The PRD amendment's warrant (*"turns now reduce to decided"*) is **refuted by the
  run**. The branch still holds (`STAGE1_FINDINGS_RUN2.md`).

## Human adjudication — owner

_Not written. The owner confirms or rejects the root-cause keys above and signs the
decision line._

**Decision (S-1), unsigned:**
- [ ] **continue** — fix the composite-transport correlation (`annotation_for_turn`:
  latest snapshot *containing* the tool), then a third probe. The preparer's
  recommendation, as in `STAGE1_FINDINGS_RUN2.md`.
- [ ] **re-scope** — accept trajectory/A3-only banking
- [ ] **stop** — end the corpus-filling-mint line

Signed: ________ Date: ________
