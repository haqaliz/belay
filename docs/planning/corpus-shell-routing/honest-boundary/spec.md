# spec.md — aspect `honest-boundary`

**Unit:** `feat/corpus-shell-routing/aliz` · **PRD:** `docs/planning/corpus-shell-routing/prd.md` (M3, M4, M5, M5b).

## Problem slice

`_recompute_trajectory_case` re-verifies a trajectory case's WHOLE stored trace against the
case's ONE stored command. For a two-boundary trace (turns of both `run_process` and other
tools) the recompute silently mis-routes one family: a `run_process` turn with no
`--shell-server` replays against the stored filesystem command (`verify/turn.py:363-368`),
which the trajectory evidence seam can read as either false agreement or false REGRESSION.
And a case whose stored command IS the shell boundary (recorded `case.target_tool ==
"run_process"`) can never express the fs side on this surface. The recompute must refuse —
SKIP with a named cause, before any replay — rather than mis-route.

## In scope

- Two named SKIP causes (operator-omission / capability class, decided pre-replay):
  `TRAJECTORY_SHELL_BOUNDARY_NOT_SUPPLIED` and `TRAJECTORY_FILESYSTEM_BOUNDARY_UNEXPRESSIBLE`.
- The pure boundary-need decision and its wiring into `_recompute_trajectory_case`.
- The fixture flip (`_build_mixed_trajectory_case` → mint-faithful turn order) and the
  enumerated test updates (M5b).
- Single-boundary byte-identity preserved (no flag).

## Out of scope

- The CLI flags (`cli-wiring` aspect), the parity table and docs (`parity-docs` aspect).
- `_recompute_claim_case` (self-consistent; PRD Technical Considerations).
- Any case-schema change, any `_SKIP_CAUSES` change (these are substrate-class; the new
  causes are operator/capability class, rendered via `CaseResult.skip_reason`).

## Acceptance criteria (test-first, all in `tests/test_corpus_trajectory_run.py`)

1. A two-boundary trajectory case (stored fs command, recorded `target_tool` ≠
   `run_process`) recomputes faithfully with a supplied `shell_server_command` and reads
   MATCH — **unchanged** from today (pinned by
   `test_trajectory_recompute_routes_run_process_to_the_shell_command`, now mint-faithful).
2. Same shape WITHOUT a supplied command → SKIP, `skip_reason ==
   "TRAJECTORY_SHELL_BOUNDARY_NOT_SUPPLIED"`, and **no replay occurred** (the recording
   stub sees nothing). Replaces
   `test_trajectory_recompute_without_a_shell_command_is_byte_for_byte_today`.
3. A two-boundary case whose recorded `target_tool == "run_process"` (stored command IS the
   shell boundary) → SKIP `TRAJECTORY_FILESYSTEM_BOUNDARY_UNEXPRESSIBLE`, **with or without**
   a supplied flag.
4. A single-boundary trajectory case recomputes byte-identically with no flag (pinned by the
   existing single-boundary tests); a supplied flag does not fire the SKIP decision.
5. The mixed fixture `_build_mixed_trajectory_case` flips to turn order
   `("run_process", "edit_file")`; `test_a_case_written_in_the_pre_change_format_still_loads_and_recomputes`
   passes `shell_server_command=["shell-server"]` and keeps its key-set + MATCH assertions.
6. SKIP outranks a declared recorded miss (the decision never consults `expected`).