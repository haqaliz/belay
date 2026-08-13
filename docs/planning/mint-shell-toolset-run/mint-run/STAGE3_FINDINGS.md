# STAGE 3 FINDINGS — s6c

> **STATUS: RUN, once (resumed once on the same root, declared — 2026-08-12).**
> Verbatim output: `acceptance-stage3.out` (two declared blocks: the initial run
> and the identical-command resume); ledger: `ledgers/s6c.json`.

## Gates — PASSED

- [x] **Denominator ≥50 distinct fresh non-control instances** — **60 distinct**
      (7 from stage 2 + 53 from stage 3; controls partitioned out)
- [x] Every UNVERIFIED to a named cause — 131/441 turns (29.7%), by cause:
      `UNRESTORABLE_SNAPSHOT_FAILED` 122, `embedded path unrelocatable` 1,
      `replayed but effect unverified` 8
- [x] No `INSTRUMENT SUSPECT` — exit 0, run size 53
- [x] Capture rate 53/58 ≥ 50% (stop-loss not reached)

## The number

- **Violation rate = 37/52 = 71.2%** — 15 VERIFIED_CLEAN, 37 VERIFIED_FLAGGED,
  1 NO_VERIFIABLE_TURNS (excluded from the denominator), 0 ERRORED
- Per-turn FAIL rate 160/441 = 36.3%
- **Trajectory aggregate: 20 FAIL / 0 PASS / 33 UNVERIFIED**
  (CLAIM_UNCLASSIFIABLE 20, EVIDENCE_UNOBSERVABLE 7, NO_CLAIM_RECORDED 6)
- FP-rate n/a (0 labeled — adjudication is the audit aspect's first act)

## Exposure lines (from `belay phase0 report`)

- File-comparisons: reported per instance in the ledger — A1 exposure on
  `tests/`/`testing/` paths (the 2026-07-29 scope fix is in force)
- Trajectory: 20 judged FAIL of 53 — the D-1 exposure gate's reading is now
  population-scale; every one of the 20 is S-5 adjudication material

## Findings

- **The ≥50 denominator is filled for the first time** — 60 distinct fresh
  non-control instances, 392+ turns, and the trajectory axis measured real text
  at population scale: **20 FAILs of 53 instances (37.7%)** claim verification
  success with zero replayed command evidence. Whether these survive S-5
  adjudication as true positives (vs the U9 verify-seam reading — commands run
  but replaying through the filesystem-only `--server` cannot produce exit-0
  evidence) is the audit aspect's question, and the 7 `EVIDENCE_UNOBSERVABLE`
  abstains are the exposure the rule counted rather than hid.
- **Attrition: 5 failed of 58 (8.6%)**, all honest terminal shapes — 3
  no-`kind`-JSON replies, 1 unrecognised `run_process` kind, 1 git worktree
  checkout failure. Recorded `failed`, never re-rolled; the attrition rate is a
  finding, not a defect.
- **The interrupted verify run (2 h tool timeout) left one torn corpus dir** —
  removed (no `case.json` = never a complete case, never labeled); the final
  clean `belay phase0 run` ingested everything and the number reproduced
  identically across runs (37/52 = 71.2% both times) — the ledger is
  deterministic.
- **Corpus: 182 cases, `belay corpus run` 182 MATCH / 0 REGRESSION** — the
  flagged turns of this mint are banked and replayable (moat #2 compounding).
- The canonical gate block was confirmed present in `PHASE0_RESULTS.md` before
  this stage ran.
