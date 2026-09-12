# Spec — delta-rules (aspect 1 of 3)

Aspect of `invariant-library` (PRD M1, M6-partial, S2). Buildable alone; no
dependency on aspects 2–3.

## Problem slice

A1 needs two new delta-grounded rules so the library can name them: `no-create`
(nothing may appear under the scope) and `no-delete` (nothing under the scope may
disappear). Today the only delta-grounded rule is `read-only`; `no-create` /
`no-delete` are reserved names the loader rejects by design
(`src/belay/verify/invariants.py:29-31, 74-76`).

## In scope

- `RULE_NO_CREATE = "no-create"`, `RULE_NO_DELETE = "no-delete"` join `_KNOWN_RULES`
  and `_DELTA_GROUNDED_RULES` (`invariants.py:77-79, 230`); the partition test
  (`tests/test_invariant_trajectory_plumbing.py:249`) must stay green.
- Evaluation branches in `evaluate_invariant` (byte-prefix scope, mirroring the
  `read-only` branch at `invariants.py:290-325`): created path under scope →
  FAIL naming the invariant and path(s); deleted path under scope → FAIL; no
  violating paths → PASS; `delta is None` → UNVERIFIED (existing cause). Messages
  must be **rule-generic** (the `read-only` branch's hard-coded message text is
  factored so the rule name comes from the invariant), and the two rules must be
  distinguishable in the FAIL message.
- Byte-prefix semantics only: the brief's asymmetry rule
  (read-only=prefix, no-assertion-weakening=segment) is preserved; the new rules
  are delta-grounded siblings of read-only (interview decision).
- Pure unit fixtures: real trees + BTH-1 `diff_records` (house pattern from
  `tests/test_inferred_invariants.py`): created/absent paths FAIL each rule; clean
  delta PASSes; scope prefix honored; near-miss prefix does not fire; `delta=None`
  → UNVERIFIED, never PASS; `no-assertion-weakening` behavior byte-unchanged
  (regression pin).
- Scoped operator-file use (S2): `{"scope":"scratch/","rule":"no-create"}` works.

## Out of scope

- The library table, resolver, CLI flag, `list` command (aspect 2).
- Fixture servers / banked corpus round trips (aspect 3).
- Any change to `read-only` or `no-assertion-weakening` semantics.

## Acceptance criteria (test-first)

1. `_KNOWN_RULES` and the partition test admit both rules; the loader accepts
   `{"scope":..., "rule":"no-create"}` / `"no-delete"` from an operator file.
2. A created path under the scope → FAIL naming `no-create` and the path; a deleted
   path under the scope → FAIL naming `no-delete` and the path; near-miss prefixes
   (e.g. `testsuite/` vs scope `tests/`) do not fire.
3. A clean delta → PASS; `delta is None` → UNVERIFIED with a named cause.
4. `read-only` and `no-assertion-weakening` fixtures are byte-unchanged green
   (regression: asymmetry untouched).
5. Deterministic, no network; pure tests run on both platforms.

## Dependencies

None beyond shipped C1–C6. Sequencing: first aspect (the rules exist before the
library can name them).

## Risks

The delta-only decision is exact and structural (`FieldDiff.field is None`), so no
heuristic risk; the only trap is message hard-coding — the rule name must come from
the invariant.