# Spec: `corpus-fixtures` — per-authored-invariant corrupt-success cases

**Parent:** `docs/planning/invariant-authoring/prd.md` (M8)
**Status:** draft, pending review gate

## Problem slice

An authored invariant that never fires is dead teeth (R-b). Every invariant the
authoring path can emit must be proven to catch a real corrupt success — and the
proof must be banked, so drift in the artifact trust path or the calibration
digest turns CI red instead of silently disarming the detector. This is the
`invariant-library` "no dead entries" rule (`invariant-library/prd.md:28-32`)
applied to authored invariants.

## In scope

- A fixture pair per authored invariant exercised by the first slice (the
  vocabulary the fake author proposes): a **corrupt** trace that violates it and a
  **clean** control that does not.
- Fixtures built by the house pattern: hand-built traces via `TraceWriter` over
  real snapshots, replayed against fixture servers
  (`tests/test_invariant_library_e2e.py`; cheat servers in `tests/fixtures/`).
- Banked round trips: each corrupt fixture's case is created via real `add_case`
  and recomputes **MATCH** through `corpus run`; a deliberately broken rule flips
  **REGRESSION**.
- The clean half: the control verified with the calibrated artifact yields no FAIL
  (PASS or abstain).
- Recompute uses the case's **stored** invariants and never re-runs the author.

## Out of scope

- The library's own entries and fixtures (shipped).
- Any new corpus schema version or field; the case format is unchanged (stored
  invariants are `{"scope","rule"}` as today, `add.py:409`).
- Live-model fixtures; the fixtures use the fake author.

## Acceptance criteria (testable)

1. **Fire at the exact turn.** For each authored invariant, the corrupt fixture
   verified with the calibrated artifact FAILs at the exact turn, naming the
   invariant and the diff — while A2 independently returns PASS on that same turn
   (the C5 contract, `CAPABILITY_ROADMAP.md:367-375`).
2. **No over-fire.** The clean control verified with the same artifact yields no
   FAIL (PASS or UNVERIFIED) — the calibration half proven end-to-end.
3. **Banked and MATCH.** Each corrupt fixture banks via real `add_case`;
   `belay corpus run` recomputes **MATCH** per case, 0 REGRESSION, 0 SKIP.
4. **Regression simulation.** A deliberately broken rule flips the corresponding
   case to **REGRESSION** (the suite is a detector, not a rubber stamp).
5. **The author is never re-run on recompute.** A pin: recompute with an author
   command that would fail if invoked (or with no author configured at all) still
   MATCHes — the stored policy is what is enforced (the `invariant-library`
   staleness rule, `docs/STATUS.md:165-166`).
6. **Deterministic and offline.** No network, no model; darwin-gated only where
   replay re-invokes seatbelt.

## Dependencies and sequencing

Depends on `authoring-protocol` (the artifact) and `artifact-trust` (the trust
path). Ships last: it is the acceptance measurement for the whole unit.

## Open questions

- Which invariant vocabulary the fake author exercises: leading set is
  `no-assertion-weakening` on a `tests/` scope (the shape A1's history is built on)
  plus one delta rule (`no-create` or `no-delete`). Confirm in the plan.
- Whether to also bank the clean control as a case (expected PASS) — deferred;
  the clean half is asserted in-process for the first slice.