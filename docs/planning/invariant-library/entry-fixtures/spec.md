# Spec — entry-fixtures (aspect 3 of 3)

Aspect of `invariant-library` (PRD M6). Depends on aspects 1–2.

## Problem slice

The library's promise is "no dead entries, and the corpus compounds": every
grounded entry is proven to fire on a real replay and banks as a corrupt-success
case. Without this aspect the library is prose.

## In scope

- **CLI-level fixture servers** under `tests/fixtures/` (house pattern:
  `weakening_editor_server.py`; `[sys.executable, str(FIXTURES / "<name>.py")]`):
  - `create_server.py` — on `tools/call`, creates a file under a known path.
  - `delete_server.py` — on `tools/call`, deletes a file present in the pre-state.
  (The existing `weakening_editor_server.py` covers the write-under-tests shape;
  `tests-read-only` / `source-read-only` fixtures reuse its pattern with a
  `src/`-targeting sibling if needed.)
- **Per-entry corrupt-success fixtures:** hand-built traces via `TraceWriter` over
  real snapshots (pattern `tests/test_verify_cli_invariants.py:42-108`), replayed
  against the fixture servers with `--invariant-library <entry>`:
  - `no-create`: the creating turn FAILs at the exact turn naming the invariant and
    path; A2 stays PASS on the same turn (axes non-redundant).
  - `no-delete`: the deleting turn FAILs naming the invariant and path.
  - `tests-read-only` / `source-read-only`: a write under the scope FAILs.
- **Banked round trips:** each grounded entry's fixture case is banked via real
  `add_case` and recomputes MATCH through `corpus run` (pattern
  `tests/test_corpus_trajectory_run.py` — real `add_case`, stubbed or real replay
  as the house pattern dictates); drift on that entry's rule flips the set →
  REGRESSION → CI red.
- **Egress fixture:** a run with `--invariant-library network-egress` renders every
  turn UNVERIFIED with the named cause, never PASS (the honesty fixture).
- **Fixture guard:** the new cheat fixtures genuinely cheat (pattern
  `tests/test_fixture_guard.py`) — the create/delete servers really create/delete,
  so a green A1 verdict would be a false PASS.

## Out of scope

- The rules themselves (aspect 1) and the selection surface (aspect 2) — fixtures
  consume them.
- Any change to published numbers, verdict reduction, or corpus schema.

## Acceptance criteria (test-first)

1. Each grounded entry has a test: violation at the exact turn, FAIL naming the
   invariant and the diff, A2 PASS on the same turn.
2. Each grounded entry's fixture case banks and `corpus run` reports MATCH; a
   deliberately broken rule (regression sim) turns it REGRESSION.
3. `network-egress` fixture: UNVERIFIED with named cause on every turn; no surface
   renders it PASS.
4. Fixture guard proves the servers really create/delete.
5. Deterministic, no network; darwin-gated only where replay-reinvokes-seatbelt.

## Dependencies

Aspects 1 (`delta-rules`) and 2 (`library-surface`). Last aspect.

## Risks

Fixture servers must not leak state between tests (each banks its own snapshot);
the banked cases live only in tests (corpus/local is gitignored and never
committed — the fixture case is the committed artifact, exactly as
`test_corpus_trajectory_run.py` does it).