# Spec: `scope-guard` (aspect 1)

**Parent:** `docs/planning/authored-invariant-scope-shape/prd.md` (S1,S2,S3,S5,R-D,R-F)
**Grade:** deterministic · strict TDD · CI

## Problem slice
An authored artifact carrying a glob scope is silently dead (PASS, 0 files compared). Make
the two **authored** seams reject/surface it with a named cause, without touching A1
evaluation semantics or the operator `--invariants` path.

## In scope
- Shared predicate: a scope string is interpretable iff it contains no glob metacharacter
  (`*`, `?`, `[`, `]`); `""` and plain prefixes are interpretable.
- `parse_authored_invariants`: tag each glob-scoped invariant with
  `AUTHORED_INVARIANT_SCOPE_UNINTERPRETABLE` via the existing `untrusted_cause` field.
  Per-invariant; artifact-level `UNCALIBRATED`/`ALTERED` take precedence; scope **bytes
  never mutated**.
- `_validate_candidate` (author protocol): glob scope → `Rejection(cause=SCOPE_UNINTERPRETABLE)`.
- Constants: `AUTHORED_INVARIANT_SCOPE_UNINTERPRETABLE` (invariants.py),
  `SCOPE_UNINTERPRETABLE` (protocol.py).

## Out of scope
Normalization; A1 matching semantics; operator `--invariants` files; `_parse_invariant`
changes; the emit-side (`infer.py`) beyond what falls out of the protocol guard.

## Acceptance (test-first)
1. Calibrated artifact, one `tests/**` (`read-only`) + one `tests/` (`no-create`):
   glob → `untrusted_cause == AUTHORED_INVARIANT_SCOPE_UNINTERPRETABLE` and
   `evaluate_invariant` **UNVERIFIED** on a `tests/test_auth.py` delta; prefix → trusted
   and **FAIL** on the same path. RED first.
2. Artifact-level precedence: uncalibrated artifact with a glob scope → `UNCALIBRATED`.
3. Digest stability: the same artifact's digest still validates (not `ALTERED`).
4. Operator path byte-unchanged: `load_invariants` on a JSON **list** with `tests/**`
   loads, `untrusted_cause is None`, evaluates exactly as today.
5. Protocol: `tests/**` → `Rejection(SCOPE_UNINTERPRETABLE)`; `tests/`, `tests`, `""` →
   `Candidate`.
6. R-F: no committed test pins the frozen live-run artifact's old verdict.

## Dependencies / sequencing
None. Aspect 2 (`author-guidance`) touches `protocol.py` too — run after this aspect to
avoid edit collisions.

## Open questions
Metacharacter set (`*?[]`) and message detail are tech-plan decisions.
