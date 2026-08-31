# Card — feat/corpus-trajectory-banking/aliz

**Source:** no GitHub issue (`gh issue list` → "No Issues"; the repo's tracker is empty).
The source of record is the inline brief below, produced by the `belay-next` pick on
2026-08-31 against the committed record.

## Brief

Fix the recorded mint defect: `belay phase0 run`'s trajectory ingest banks a trajectory
FAIL into the same `trace-<instance>-turnN` id namespace as the per-turn A2 cases, the
guard rightly refuses to overwrite, and **zero of the shell-toolset mint's 23 trajectory
FAILs — including all 11 hand-audited TPs — entered the corpus**. `belay corpus score`
reads `n/a` on the axis that earned the 18.3% number.
`docs/planning/mint-shell-toolset-run/audit-and-publish/AUDIT.md:122-142`.

Two named causes, from the audit:
1. **Case-id collision:** the trajectory ingest targets the same
   `trace-<instance>-turnN` id namespace as the per-turn A2 seam cases already banked by
   the first verify pass — every Shape-A/B instance's trajectory case collides with its
   already-stored per-turn case and the guard refuses to overwrite (the guard is correct;
   the id namespace is the gap).
2. **Unrestorable pre-state:** 5 trajectory FAILs (django-12184, 12470, sympy-13437,
   18057, 20442) name a turn whose `state_handle` is `unrestorable` — no restorable
   pre-state, so no replayable case by the format's fail-closed rule. This is honest
   behaviour, not the defect; these must stay unbankable.

The audit's own demand: *"The trajectory-case id-collision is a follow-up defect to fix
before any future mint trusts `phase0 run`'s trajectory ingest"* (`AUDIT.md:141-142`).

### Acceptance sketch (test-first, from the handoff)

1. A trajectory FAIL from a synthetic mint banks **alongside** the already-banked per-turn
   case of the same instance; both replay via `belay corpus run` as MATCH.
2. `corpus score` computes precision/recall on the trajectory dimension against labeled
   cases with real denominators (no more `n/a` once labels exist).
3. An unrestorable-pre-state trajectory FAIL still refuses to bank with a named cause —
   fail-closed, never a guessed restore (negative test).
4. No verdict axis, status or Phase-0 number moves; the docs state plainly that the s6
   captures are gone so **nothing is backfilled** — the value is forward-looking.

### Caveats carried in from the pick

- **Not an R-id — a recorded defect** (`AUDIT.md:141-142`). The nearest register entries:
  moat #2 (C6 "every caught failure becomes a labeled, replayable case") is the promise
  the defect breaks; R12 (corpus consent) is untouched.
- The **s6 captures no longer exist on disk** (`docs/STATUS.md`: the 171 per-turn FAILs are
  historical and were NOT recomputed — "the s6 captures no longer exist on disk"), so the
  11 TPs **cannot be backfilled**. The fix is forward-looking: the next trajectory FAIL
  banks; `corpus score` stays `n/a` until a future mint runs under fixed ingest.
- The 5 unrestorable-pre-state FAILs must remain unbankable (fail-closed honesty feature,
  not a casualty).
- **Reclassification discipline:** no published number moves (`11/60 = 18.3%`, `precision
  0.00`, `1/15`, `4/16` stand unedited).

## Related record (not issues — commits/docs)

- `docs/planning/mint-shell-toolset-run/audit-and-publish/AUDIT.md:122-142` — the
  corpus-banking finding and its two named causes.
- `docs/technical/PHASE0_RESULTS.md:1189-1195` — the published record: zero of 23 banked,
  `corpus score` reads `n/a`, "the id-collision is a recorded follow-up defect".
- `docs/technical/CAPABILITY_ROADMAP.md` — C6 status (2026-08-09, `corpus-trajectory`):
  ingestion (`0f8878c`), schema v4 (`02e033b`), recompute (`1a88a04`); "no real trajectory
  case exists yet — no mint has run under the rule".
- `docs/planning/trajectory-success-invariant/corpus-trajectory/` — the C6 trajectory
  aspect's own planning.
- `docs/STATUS.md` (v0.25.0 entry) — "the s6 captures no longer exist on disk" (the
  no-backfill constraint).