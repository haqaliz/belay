# Aspect A3 — `verify-shell-server`

> `belay verify` gains the `--shell-server` routing that `belay phase0 run` has had since
> `9138cea`, and the README states the replay-boundary limit it has never stated.

## Problem slice

The engine supports per-tool server routing (`verify_turn(shell_server_command=...)`,
`src/belay/verify/turn.py:210`), but the **documented, user-facing** command cannot reach it:
`belay verify --help` shows `[--server ...]` and nothing else. Only the batch/eval surface
`phase0 run` has the flag (`src/belay/cli.py:2561`).

`tests/test_phase0_dual_server.py:14` records why: *"The CLI `--shell-server` flag is Phase 3
of the aspect"* — planned for the batch runner, never extended.

**Same defect class has now occurred twice:** the L7 work found `belay verify` lacked the
`--timeout` that `corpus add` / `phase0 run` / `interop correlate` already had.

## In scope

1. `belay verify --shell-server CMD` — the **same shape** as `phase0 run`'s: a single quoted
   string, `shlex.split` at use, **fail-closed** on an un-lexable string (`--server` is
   `nargs=REMAINDER` and argparse cannot host a second remainder — `src/belay/cli.py:1770`).
   Absent flag -> `None` -> today's behavior byte-for-byte.
2. **README:** a new subsection under *"Coverage & limits, stated exactly"* — which today has
   **12 subsections and none stating the replay-boundary/server limit**. It must say: replay
   re-invokes against the server(s) you name; a turn whose tool none of them offers is
   UNVERIFIED with a named cause, never a PASS and never a FAIL.
3. A **flag-parity guard test** so a third occurrence of this defect class is caught by CI
   rather than by running the product: assert the replay-bearing surfaces agree on the flags
   they share.

## Out of scope

- `belay replay` / `corpus add` / `interop correlate` parity (PRD open question 3 — proposed
  `verify` only).
- N-server routing or a new repeatable flag shape.

## Acceptance criteria (failing tests first)

- **AC-1** `belay verify --shell-server "..."` parses and reaches `verify_turn` as
  `shell_server_command`; absent flag -> `None`.
- **AC-2** An un-lexable string is a **hard error** (exit 2, named), never half-executed.
- **AC-3** End-to-end on the **committed demo capture**: `belay verify` with both servers
  produces a real verdict for the `run_process` turns — the capture becomes fully verifiable
  from the documented CLI, which it is not today.
- **AC-4** Absent the flag, output is byte-identical to today (regression fixture).
- **AC-5** README's new subsection exists and is machine-checked by the existing docs test
  (`tests/test_quickstart_docs.py` shape), so the claim cannot drift from the flag.
- **AC-6** The flag-parity guard fails if a replay-bearing surface loses a shared flag.

## Dependencies & sequencing

- **Independent of A1/A2** — may land in parallel. AC-3's *verdict* will be honest either
  way; before A1 lands, an unrouted turn still FAILs, so AC-3 should assert the routed path.

## Risks specific to this aspect

- `--server` is `REMAINDER`: flag **order** matters on the command line
  (`--shell-server` must precede `--server`, as `eval/minting_driver/entrypoint.py` already
  does). Help text must say so, and a test should pin it.
