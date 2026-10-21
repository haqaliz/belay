# Brief (inline; no GitHub issue)

Unit: `feat authored-invariant-scope-shape` — the belay-next pick 2026-10-17. A C5
follow-on (A1 policy authoring; R3's third mitigation), not a new capability.

## Problem

The shipped `belay invariant infer` path is broken by measurement. The reference author
emits **glob** scopes (`tests/**`) while A1 scope semantics are a **raw byte-prefix**, so
authored invariants are dead teeth: they PASS trivially and never fire. Sources:

- `src/belay/authoring/reference_author.py:99` — the prompt literally asks for
  `"scope": "<path glob>"`.
- `src/belay/verify/invariants.py:326` (`parse_authored_invariants`) — the scope is taken
  as bytes with no shape check.
- The finding, produced by running the experiment at n=1:
  `docs/planning/invariant-authoring/reference-author/live-run.md:53-74` — *"a follow-on
  normalization (the author declares `tests/` style prefixes, or the protocol rejects
  glob-shaped scopes with a named cause) is the likely next unit."*
- Risk R3 ("nobody authors the invariant") is **High/High** (`docs/ROADMAP.md:372`;
  `docs/planning/invariant-authoring/prd.md:16`); CLAUDE.md: *"User-declared invariants
  remain the load-bearing A1 mechanism; annotations are a free supplement."* A silent
  no-op in the zero-friction authoring path is worse than no policy, because it looks
  like coverage.

## Scope

Decide at the review gate between **normalizing** authored scopes to real prefixes and
**refusing** glob-shaped scopes with a named cause that surfaces UNVERIFIED (never PASS,
never FAIL) on every turn — consistent with the existing `AUTHORED_INVARIANT_UNCALIBRATED`
/ `AUTHORED_INVARIANT_ALTERED` provenance causes. The fix must not change A1 semantics,
add an axis/status/default, or move any published number.

Acceptances to write first (test-first, RED before GREEN):

1. RED: an authored glob scope is never silently loaded as a dead byte-prefix that can
   never match a real path.
2. A **firing** test proving a scope-scoped rule actually FIRES on a fixture whose delta
   touches the scoped path (a clean control cannot see dead teeth — `live-run.md:66-67` —
   so a negative fixture whose delta touches the scoped path is required).
3. The artifact digest / `AUTHORED_INVARIANT_ALTERED` / `AUTHORED_INVARIANT_UNCALIBRATED`
   provenance pins still hold (no regression).
4. No verdict movement: no new axis/status/default; `--no-claim-axis` refutation unchanged.

## Honesty lines

- No published number moves — `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
  `recall 0.00`, `3/93` stand unedited.
- This is an authoring/protocol fix; A1 evaluation semantics are untouched.
- Not a gate run.

Suite baseline (measured on this worktree's base, `master` @ 86d726a): see Phase 2 —
to be re-measured before planning.
