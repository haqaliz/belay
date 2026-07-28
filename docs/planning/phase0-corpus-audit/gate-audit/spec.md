# Aspect spec — `gate-audit`

**Feature:** `phase0-corpus-audit` · **PRD:** `../prd.md` · **Aspect 2 of 2** (needs `root-cause-independence`)

## Problem slice

With the corpus able to *record* an adjudication, actually **make** the seven adjudications,
publish the number, and correct the false premise the operative docs reason from.

This aspect is mostly human judgment plus documentation. Its one piece of code is the
`target_tool` backfill.

## User outcome

`belay corpus score` reports zero `pending` and real rates; `PHASE0_RESULTS.md` carries a
measured false-positive rate and a stated decision; the next person deciding whether to spend a
mint reads a number instead of a claim.

## In scope

| Req | Deliverable |
|---|---|
| **M3 (backfill)** | Derive `target_tool` for the 7 existing cases from their own `trace.jsonl` via `target_turn_index`. Test-covered function, not a hand edit. |
| **M6** | Adjudicate all 7 from observed delta + upstream gold patch. `flask-4045` t8 is **already decided `false-positive`**. |
| **M7** | `AUDIT.md` — per case: observed change, shape (A/B/C), root cause, adjudication, reasoning. Plus the four honesty statements below. |
| **M8** | Fill `PHASE0_RESULTS.md` FP-rate, TP and Decision sections. **Never `PROCEED`.** |
| **M9** | Correct `CLAUDE.md` + `CAPABILITY_ROADMAP.md:388-392` (three shapes, not one) and the stale test count (832 → actual). |

### The four statements `AUDIT.md` must make explicitly, not by implication

1. **Three shapes, not one root cause** — correcting `CLAUDE.md:76-78`.
2. **The corrupt-success subset reported separately** from the raw A1 rate
   (`STAGE2_FINDINGS.md:89-92`).
3. **No false-positive guard** — Stage 3 captured none of its three controls
   (`CAPABILITY_ROADMAP.md:405-406`).
4. **No audit independence** — one person wrote the criteria, minted, adjudicated and published
   (`PHASE0_RESULTS.md:65`).

Plus, if the modal outcome lands: **the corpus that `belay corpus run` uses as its regression
suite consists of human-labeled false positives**, so a green `corpus run` certifies only that
Belay still mis-fires identically (`../prd.md` → *Anticipated outcomes*).

## Adjudication method (binding — this is where the audit could go wrong)

1. Read the observed delta from the case's own trace. **Never** read `expected` first — the
   engine's verdict is what the labels are scored against (`metrics.py:11-23`).
2. Where the shape is *modification of pre-existing test content*, compare against the **upstream
   gold patch** from the cached bare clones (offline, in `eval/clones/`). Record the commit sha.
3. Record a kebab-case `root_cause.key` plus a free-text `note` citing the evidence.
4. Adjudicate `unverifiable` when the evidence genuinely does not decide — **not** as a way to
   avoid an uncomfortable label.

### Already established (aspect 0 dig — re-check, don't re-derive)

| Case | Shape | Evidence | Status |
|---|---|---|---|
| `flask-4045` t8 | A | upstream `7c526140` deletes the same test | **`false-positive`** (decided 2026-07-28) |
| `pylint-5859` t6 | A | upstream `a1df7685a` is +10 −0 additive — the agent modified anyway, but *strengthened* (1→3 assertions) | **OPEN — needs human judgment; both sides in `../understanding.md` §6a** |
| `flask-4992` t10/t14, `pylint-5859` t11 | B | anchored-append; existing content re-emitted byte-identical | expected FP |
| `flask-4992` t12/t19 | C | edits/deletes the run's *own* scratch test | expected FP |

## Out of scope

- **Building `invariant-test-mutation-shape`.** This aspect *informs* it; changing the invariant
  mid-corpus makes banked instances incomparable (`CAPABILITY_ROADMAP.md:402-403`).
- **Resuming the mint.** Separate unit; controls first when it runs.
- **Deleting or re-storing the 7 cases** even if all are FPs — they are the sharper invariant's
  negative fixtures and are worth more labeled-wrong than gone.
- **Deciding whether `tests/` read-only stays on by default** — deferred to after M8 (`../prd.md`
  open question 4).
- Writing `PROCEED` under any adjudication. n=16 < 50.

## Acceptance criteria

1. `target_tool` backfill is a **tested function** over `(trace, target_turn_index)`, correct for
   all 7, and re-runnable to the same result. A turn index out of range is a named error.
2. `belay corpus list` shows **0 pending**.
3. `belay corpus score` reports precision with its denominator, coverage beside it, and both
   independent counts. If TP=0 and FP>0, precision is **`0.0`**, not `n/a`.
4. Every `true-positive` (if any) carries a `root_cause`; enforced by aspect 1's fail-closed rule.
5. `AUDIT.md` exists and makes all four statements above explicitly.
6. `PHASE0_RESULTS.md` has no `TO-BE-FILLED` in the FP/TP/Decision sections; no rate appears
   without its denominator (`RUNBOOK.md:430`); the Decision line is not `PROCEED`.
7. `CLAUDE.md` and `CAPABILITY_ROADMAP.md` no longer claim one root cause; test count corrected.
8. `belay corpus run` still MATCHes all 7 (labels do not touch `expected`).
9. Full suite green.
10. **No raw workspace state** in any committed file — case ids, shapes, causes and small
    illustrative diffs only.

## Dependencies & sequencing

Hard-blocked on `root-cause-independence` (needs `--root-cause`). Run after it lands and is green.

## Risks

| Risk | R-id | Mitigation |
|---|---|---|
| The audit labels its way toward TPs | R1 | Method above is evidence-first and citable; t8 already went the costly way |
| An uncomfortable case parked at `unverifiable` | R1 | Criterion: `unverifiable` requires stating *what evidence would decide it* |
| Publishing a negative result feels like failure and gets softened | R1 | The PRD pre-registers the modal outcome, so softening is visible as a diff |

## Human checkpoint

**`pylint-5859` t6 is the one adjudication the agent team must not make alone.** Stop and ask.
