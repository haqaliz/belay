# Spec — library-surface (aspect 2 of 3)

Aspect of `invariant-library` (PRD M2, M3, M4, M5, S1). Depends on aspect 1
(`delta-rules` — the library names `no-create`/`no-delete`).

## Problem slice

The R3 mitigation seam: named, pre-authored, user-selectable invariant declarations
with zero JSON authoring. The library is module-level plain data; selection is a
repeatable `--invariant-library <name>` flag on the three `--invariants` surfaces;
discovery is `belay invariant-library list`.

## In scope

- **The table** (module-level plain data in `src/belay/verify/invariants.py`):
  `LIBRARY: dict[str, LibraryEntry]` where each entry carries its declarations
  (list of `{"scope": str, "rule": str}`), a one-line description, and grounding
  metadata. v1 entries: `no-create`, `no-delete` (whole-tree presets, aspect 1
  rules), `tests-read-only` (`{"scope":"tests/","rule":"read-only"}`),
  `source-read-only` (`{"scope":"src/","rule":"read-only"}`),
  `network-egress` (M3, below).
- **The resolver** — a **deliberately amended third producer** of `Invariant`
  policy: `test_no_invariant_is_ever_sourced_from_a_trace`
  (`tests/test_invariants.py:55-123`) admits it by name, and a **new pin** asserts
  library selection can never come from a trace (same purpose, grown set — the
  interview decision). Unknown name → `ValueError` (fail-closed, same contract as
  the file loader).
- **The egress entry (M3).** `network-egress` is curated and evaluates
  UNVERIFIED-with-named-cause on every turn; its rule name is **not** in
  `_KNOWN_RULES`, so operator *files* declaring it are still rejected (exit 2) and
  the partition test is untouched; `evaluate_invariant`'s catch-all
  (`invariants.py:278-288`) gains the named cause/message for it. The listing and
  README state the honesty boundary (Belay has no egress instrument; the sandbox
  denies egress by construction — seccomp deny-all).
- **The flag.** Repeatable `--invariant-library <name>` on `verify`, `corpus add`,
  `phase0 run` (`cli.py:2522, 2651, 2895`); `--invariants <file>` unchanged;
  both compose on top of defaults; flag-parity table
  (`tests/test_cli_flag_parity.py:85-86`) updated; unknown name → exit 2 with a
  `belay:` message (pinned on all three surfaces, mirroring
  `test_malformed_invariants_file_is_fail_closed`).
- **Discovery.** `belay invariant-library list`: name, rule(s), scope semantics
  (byte-prefix vs segment), grounding status, and the egress honesty note.
- **Docs (S1).** README library section (entry table + the egress line +
  "apply by name, no JSON"); `--invariant-library` in help/coverage text where
  `_VERIFY_COVERAGE` states the A1 contract (nothing overclaimed).

## Out of scope

- Per-entry fixture servers / banked corpus round trips (aspect 3).
- `--json` for `list` (deferred, N2).
- Any change to defaults, `load_invariants`'s signature, or the partition test.

## Acceptance criteria (test-first)

1. `--invariant-library no-create` on `verify` FAILs a creating turn at the exact
   turn, naming the invariant and path; `--invariants`-only behavior unchanged
   (existing CLI tests green untouched).
2. An unknown name (`--invariant-library bogus`) is exit 2 on all three surfaces,
   before any trace is read; a malformed operator file is still exit 2.
3. `belay invariant-library list` renders all five entries with grounding column;
   the `network-egress` row states it is unobservable.
4. The producer guard admits exactly `{load_invariants, default_invariants,
   <resolver>}` and the new pin: library selection is unreachable from any trace
   record.
5. Operator files declaring `network-egress` are rejected (exit 2) — the curated
   entry is the only path, and it yields UNVERIFIED-with-cause, never PASS.
6. Flag parity: `--invariant-library` declared on exactly the three surfaces.
7. No published number moves; `default_invariants()` unchanged.

## Dependencies

Aspect 1 (`delta-rules`) — the library must only name rules that evaluate.

## Risks

Guard amendment must be deliberate and pinned (PRD R-C); the resolver must not
silently shadow `--invariants` (a file and a name never collide — separate flags).