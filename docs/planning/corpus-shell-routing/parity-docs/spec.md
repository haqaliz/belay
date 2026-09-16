# spec.md — aspect `parity-docs`

**Unit:** `feat/corpus-shell-routing/aliz` · **PRD:** `docs/planning/corpus-shell-routing/prd.md` (M8, S1).

## Problem slice

The flag-parity guard (`tests/test_cli_flag_parity.py`) is the repo's machine-checked
answer to the twice-bitten "a replay-bearing surface cannot ask for the shell boundary"
defect class. The moment the three corpus flags land, the guard must declare the widened
contract or it fails red; and the docs (`corpus-trajectory-banking` PRD's NOT-built line,
`docs/STATUS.md`) must retire the deferral exactly as wide as the slice, following the
repo's append-only correction discipline.

## In scope

- `REPLAY_BEARING` gains `"corpus show"` (its recompute re-invokes a server; the "corpus
  show replays nothing" comment is stale), with the per-case exclusions stated.
- Row edits in `EXPECTED`, each with its comment updated, not just its frozenset:
  `--shell-server` (gains `corpus run`, `corpus add`, `corpus show`), `--server`, `--replays`,
  `--timeout`, `--manifest-dir` (each gains `corpus show` in its exclusion set), and
  `--corpus-dir` (gains `corpus show` — it carries that flag today).
- Both guard tests stay green by construction.
- Docs: the `corpus-trajectory-banking` PRD's NOT-built line gains a `Closed 2026-09-16`
  note (append-only correction, mirroring the AUDIT.md "Closed 2026-09-01" pattern); a new
  `docs/STATUS.md` entry is appended (newest first) stating what shipped and the
  reclassification discipline (the no-flag behavior change touches constructed fixtures
  only — no real banked two-server case exists, no published number moves).

## Out of scope

- The flags themselves (`cli-wiring` aspect) and the SKIP engine (`honest-boundary` aspect).
- Editing historical `STATUS.md` entries (append-only; the new entry supersedes).
- `corpus show` gaining `--no-claim-axis` (declared out by decision; a display surface).

## Acceptance criteria (test-first)

1. RED: after the flags land, `tests/test_cli_flag_parity.py` fails naming the undeclared
   surfaces; the row edits make it green with every row's comment matching its set.
2. The corrected REPLAY_BEARING comment states why `corpus show` is now in scope and why
   `corpus label/list/score` still are not.
3. The `--shell-server` comment names all seven surfaces and the per-case rationale for
   `corpus run`/`corpus add`/`corpus show`.
4. `docs/STATUS.md` gains the entry; the deferral lines are retired by the new entry's
   "closed" statement, never by editing history.
5. The `corpus-trajectory-banking` PRD out-of-scope line carries the `Closed 2026-09-16`
   note.