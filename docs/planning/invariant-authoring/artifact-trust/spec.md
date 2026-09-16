# Spec: `artifact-trust` — the authored artifact schema and verify-side trust

**Parent:** `docs/planning/invariant-authoring/prd.md` (M4, M5, M6)
**Status:** draft, pending review gate

## Problem slice

An authored invariant must reach A1 without weakening the provenance boundary
("the agent must never be able to author its own policy",
`docs/planning/phase0-corpus-audit/understanding.md:194-195`), and an authored
invariant whose calibration is absent or invalidated must **never** produce a FAIL.
This aspect owns the artifact format, its loader, the trust rules, and the guard
amendments. It is the interface the other aspects build against.

## In scope

- The authored artifact schema (`"belay-authored-invariants/1"`): provenance
  fields, the canonical policy set, the calibration digest.
- The loader and trust check, wired additively into the existing `--invariants`
  flag by **shape dispatch**: a JSON list is operator policy (byte-unchanged); a
  JSON object with the authored schema is the trust path; anything else is exit 2,
  fail-closed.
- `Invariant` gains one additive field (`untrusted_cause: str | None = None`);
  when set, evaluation short-circuits to UNVERIFIED with that cause. Every existing
  producer leaves it unset.
- Two new closed-vocabulary verdict causes: `AUTHORED_INVARIANT_UNCALIBRATED`
  (missing/malformed calibration) and `AUTHORED_INVARIANT_ALTERED` (digest
  mismatch).
- The provenance-guard amendment: the new producer is admitted **by name** into
  `tests/test_invariants.py:55-114`, plus a new pin that authored policy can never
  come from a trace.
- Placement: schema + loader + trust check in `src/belay/verify/` (so the guard
  sees the producer); the zero-LLM AST guard over `src/belay/verify/` stays green.

## Out of scope

- Running the author or emitting an artifact (`authoring-protocol`).
- The reference `claude -p` author (`reference-author`).
- Any new rule, any new verdict axis or status, any change to operator files or
  defaults.

## Acceptance criteria (testable)

1. **Calibrated artifact enforces like policy.** A well-formed calibrated artifact
   loaded via `belay verify --invariants <artifact>` FAILs the corrupt fixture at
   the exact turn (naming the invariant and the diff) and PASSes or abstains the
   clean control — identical verdicts to the same declarations loaded as an
   operator list.
2. **Uncalibrated degrades, never FAILs.** An artifact whose calibration block is
   absent, malformed, or not `"calibrated"` yields UNVERIFIED with the named cause
   `AUTHORED_INVARIANT_UNCALIBRATED` on every evaluated turn — no FAIL, no PASS,
   no silent skip.
3. **Altered degrades, never FAILs.** An artifact whose policy set was edited
   after calibration (digest mismatch) yields UNVERIFIED with
   `AUTHORED_INVARIANT_ALTERED`. Rationale-text-only changes do not invalidate
   (rationale is not policy).
4. **Fail-closed on malformed.** An unknown rule name in an artifact, an unknown
   schema string (including a future version this engine does not know), or a JSON
   object that is neither shape → exit 2 before any trace is read (same contract as
   a malformed operator file, `invariants.py:247-253`). A plain operator list is
   byte-unchanged; `--no-default-invariants` unchanged.
5. **One loader, four surfaces.** `--invariants` reaches `verify`, `corpus add`,
   `phase0 run`, and `gate baseline` (`cli.py:2949,3090,3345,3636`;
   `test_cli_flag_parity.py:97`); criteria 1–4 hold identically on all four,
   enforced by a single shared loader (a structural pin: no surface-specific
   loading path).
6. **The provenance guard admits the new producer by name and stays green.** The
   producer set in `test_no_invariant_is_ever_sourced_from_a_trace` is exactly
   `{load_invariants, default_invariants, resolve_library_entry, <new loader>}`,
   and a new pin asserts the authored policy originates from the author command's
   output — the control trace is calibration evidence only, never a policy source.
7. **No model in the verdict path.** `test_verify_zero_llm.py` stays green; the
   trust check imports no model client and spawns no subprocess.
8. **Untrusted invariants only lower.** A property test over the status enum: for
   any untrusted authored invariant, the emitted verdict is UNVERIFIED — never
   PASS, never FAIL — regardless of what the underlying evaluation would have said.

## Dependencies and sequencing

The schema and digest canonicalization are the interface `authoring-protocol`
emits and `corpus-fixtures` enforces. This aspect can land before or after
`authoring-protocol`; both must agree on the canonical form (a shared helper, one
definition).

## Open questions

- Per-invariant digests instead of one digest over the policy set (nice-to-have,
  deferred).
- Whether the artifact may also declare the invariant library entries it used
  (informational only) — deferred, not needed for the first slice.