# spec.md — aspect `cli-wiring`

**Unit:** `feat/corpus-shell-routing/aliz` · **PRD:** `docs/planning/corpus-shell-routing/prd.md` (M1, M2, M6, M7, S1, S2).

## Problem slice

The engine seam is complete (`run_corpus` / `run_case` / `_recompute_trajectory_case`
accept `shell_server_command`), but no CLI surface can express the shell boundary for the
corpus. `corpus run` / `corpus add` / `corpus show` each need the `--shell-server <cmd>`
flag — single string, shlex-split at use, fail-closed on an un-lexable string — plus the
threading that makes a two-server trajectory case recompute faithfully through the real CLI.

## In scope

- `belay corpus run --shell-server CMD` → `run_corpus(shell_server_command=...)`
  (M1; the CLI end-to-end that makes M2 true through the real surface).
- `belay corpus add --shell-server CMD` → the target turn's stored command is resolved for
  its tool exactly as `phase0 run` does (a `run_process` target stores the shell command)
  (M6).
- `belay corpus show --shell-server CMD` → threaded to both `run_case` recompute calls
  (trajectory and claim) (M7).
- Help texts: each flag's shlex rule, the `corpus add` REMAINDER-ordering warning ("WRITE
  `--shell-server` BEFORE `--server`"), and the `corpus run`/`corpus show` honesty line that
  a two-boundary trajectory case without the flag SKIPs with a named cause (S1, S2).
- The `corpus run` SKIP sign-off wording widened to name the new cause class (substrate →
  "off substrate, server unavailable, a missing replay boundary, or capability mismatch").
- `corpus show` renders the SKIP outcome (its recompute can now SKIP).

## Out of scope

- The SKIP decision itself (`honest-boundary` aspect).
- The parity guard and `docs/STATUS.md` (`parity-docs` aspect).
- `interop correlate` / `interop export` / `invariant infer` (documented single-boundary).

## Acceptance criteria (test-first)

1. CLI RED: `corpus run --shell-server` over a constructed two-server mixed trajectory case
   recomputes **MATCH** end-to-end (parser → `run_corpus` → recompute), driven through the
   real command handler with a recording `replay_turn` stub.
2. `corpus add --shell-server` on a `run_process` target turn stores the shell command in
   `case.json` (`server_command == ["shell-server"]`), and that case recomputes MATCH on
   `corpus run` with no further flag.
3. `corpus show --shell-server` shows MATCH for a two-server trajectory case with the flag
   and the named-cause SKIP without it.
4. An un-lexable `--shell-server` string fails closed (exit 2, named message) on all three
   surfaces — the `verify`/`phase0 run` precedent (`cli.py:924-931, 2586-2588`).
5. The `corpus add` help text carries the REMAINDER-ordering warning; `corpus run`/`corpus
   show` help texts carry the shlex rule and the SKIP honesty line.
6. The `corpus run` SKIP aggregate wording names the missing-boundary cause class.