# Aspect — `verify-parity`

**Grade: DETERMINISTIC** (strict TDD: RED → GREEN → REFACTOR). Eval-only — no
`src/belay/` change, no verdict impact.

## Problem slice

The mint's in-process `--verify` path is **not equivalent to the printed CLI command**
it claims to run. `run_verify` threads `claim_author` (fixed in `a3-author`, `b030843`)
but **not** `shell_server_command` (`eval/minting_driver/entrypoint.py:995-1063`), while
the printed command emits `--shell-server` for the shell toolset
(`entrypoint.py:696-698`). With `--toolset filesystem+shell --verify`, every
`run_process` turn replays against the **filesystem** server → `Tool run_process not
found` → DIVERGED → boundary probe → abstention: the 2026-08-12 "171 per-turn FAILs are
A2 replay artifacts" shape, reproducible on demand. `eval/README.md:727-729` still calls
the two equivalent — the same defect class the a3-author aspect fixed for A3, in the
same file.

Not blocking the second mint run (the frozen scripts verify via stock
`belay phase0 run`), but the eval surface carries a documented lie, and the fix is the
run's own hygiene: the run's `--verify`-adjacent tooling must be what it says it is.

## In scope

- Thread `shell_server_command` through `run_verify(...)` and the mint CLI's `--verify`
  branch (`eval/minting_driver/cli.py:294-305`), resolved exactly as the printed
  `verify_command()` resolves it (`entrypoint.py:696-698`: `--shell-server` first,
  shlex-split single string).
- The in-process verify then routes `run_process` turns to the shell server, per the
  engine's routing rule (`src/belay/verify/turn.py:351-368`).
- Correct `eval/README.md`'s `--verify` ≡ printed-command equivalence claim, quoting
  what it replaces (the `62d8643` precedent for the A3 half).
- Lazy-import contract preserved (`entrypoint.py:1014-1023` — "runs with `belay`
  absent" holds).

## Out of scope

- Any `src/belay/` change. The engine already routes correctly; this is eval wiring.
- The `--verify` claim-author half (already shipped, `b030843`).
- Changing the frozen run scripts (they use `phase0 run` directly, unchanged).

## Acceptance (test-first)

1. **RED:** a test drives `run_verify` with a `--toolset filesystem+shell` batch and a
   `run_process` turn, asserting it replays against the shell server command (spy on
   the resolved command; without the fix the test fails — the turn resolves to the
   filesystem command).
2. The constructed `run_verify` call carries `shell_server_command` when the toolset
   includes shell, and exactly `None` when it does not (engine parameter parity —
   `src/belay/phase0/runner.py:104-122` takes `list[str] | None`, never a string,
   never an empty list).
3. The CLI `--verify` branch passes the shlex-split shell command exactly as the
   printed `verify_command()` would print it (string-equality on the tokens).
4. The "runs with `belay` absent" contract holds (the lazy-import block is untouched in
   shape) — the RED test must import the driver without `belay` present, as the
   existing `tests/test_minting_driver_entrypoints.py` does.
5. `eval/README.md` equivalence claim corrected; the prior text quoted in the commit.
6. Full suite green (baseline 2743).

## Dependencies / sequencing

Must land **before** `mint-run` (the run) — deterministic aspects gate the spend. No
dependency on the run; can proceed immediately.

## Risks

- The engine's `shell_server_command` parameter shape (`phase0/runner.py:104-122`) must
  be matched exactly — thread the same type (`list[str] | None`), never a string.
- Regression risk is contained to `eval/`; the mint driver's own test module
  (`tests/test_minting_driver_entrypoints.py`) is the seam to extend.