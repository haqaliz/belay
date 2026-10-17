# Spec: `author-guidance` (aspect 2)

**Parent:** `docs/planning/authored-invariant-scope-shape/prd.md` (S6, MH-4, MH-5)
**Grade:** deterministic · strict TDD · CI

## Problem slice
Nothing tells the author the scope shape, so the reference author asked for a "glob" and
any BYOK author is equally uninformed. Teach the shape at both places the author sees: the
reference author's prompt and the protocol payload.

## In scope
- `src/belay/authoring/reference_author.py` (`:99`, `:102-103`): replace `<path glob>` with
  a path prefix and describe the shape **per rule class**:
  - delta rules (`read-only`/`no-create`/`no-delete`) → a repo-relative path prefix; a
    directory prefix ends with `/` (`tests/`, `src/`).
  - `no-assertion-weakening` → a path segment (`tests`, `testing`); a trailing slash is
    normalised, so `tests/` is also fine.
  - Do **not** use the word "glob".
- `src/belay/authoring/protocol.py` `build_author_input`: state the same contract in the
  payload (so a custom author is told too).

## Out of scope
Any change to the rule vocabulary, the response parser, or calibration.

## Acceptance (test-first)
1. `tests/test_reference_author.py` prompt pin (`~:317`): the instructions ask for a path
   prefix, describe the per-rule-class shape, and do **not** contain `glob`.
2. `tests/test_invariant_authoring_protocol.py` payload pin (`~:83-108`): the serialized
   payload carries the scope contract; the D-7 "no control artifacts" pin stays green.

## Dependencies / sequencing
Touches `protocol.py`; run **after** `scope-guard` to avoid collisions.

## Open questions
Exact prose is a tech-plan decision; keep it deterministic so the pins are stable.
