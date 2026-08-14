# Spec — aspect 1: `verify-dual-server` (engine)

Unit: `feat/phase0-gate-mint` · Source: `docs/planning/phase0-gate-mint/prd.md` M1-M5 ·
Verdict axis: **A1 (instance-level trajectory evidence), A2 unchanged** · Test-first.

## Problem slice

`belay phase0 run` resolves ONE `--server` command per trace (`src/belay/phase0/runner.py:110-154`,
`src/belay/cli.py` phase0 run `--server` nargs=REMAINDER). A dual-server capture's `run_process`
turns replayed against the filesystem command are "not expected to reproduce their replies"
(`eval/README.md:797-805`): the replayed reply carries no `result.isError`, so
`TurnFact.replayed = False` (`src/belay/verify/trajectory.py:208-283`) and the turn falls into
`EVIDENCE_UNOBSERVABLE` (`trajectory.py:491-503`) while A2 can manufacture divergences. The
trajectory rule's evidence (a replayed exit-0 `run_process` before a VERIFICATION claim) is
therefore **structurally unobservable** for every shell turn: CTL-4's expected PASS is
unreachable, real suite-runners are never judged, and the D-1 gate can stop the mint at stage 2.

The honest replay path already exists per-turn: the manual smoke asserts a captured
`run_process` turn replays against the **rootless pinned shell server command**
(`node <abs>/mcp-server-commands/build/index.js`, no `{workspace}` token), PASS or
UNVERIFIED-with-cause, never a silent miss (`tests/test_minting_driver_dual_server_smoke.py:52-57`;
the shell relocation machinery ships — `replay-relocation-shell`, cwd relocation in
`src/belay/replay/client.py:341-394`). What does not exist is the **per-tool routing inside
`belay phase0 run` / `verify_turn`**.

## In-scope requirements

1. **Per-tool server resolution.** `verify_turn` gains `shell_server_command: Sequence[str] |
   None = None` (keyword). Resolution rule, exactly: the turn's recorded tool name is
   `run_process` (`_EVIDENCE_TOOL`, `trajectory.py:149`) AND `shell_server_command` is given →
   the turn replays against it; any other combination → `server_command`, byte-for-byte today.
   The resolved command feeds BOTH `replay_turn` and `classify_determinism` inside
   `verify_turn` (`turn.py:225-267`).
2. **Batch threading.** `run_batch` / `_verify_one_trace` gain the same optional
   `shell_server_command` and pass it to `verifier(...)` AND to every `ingester(...)` call —
   **resolved per flagged turn by that turn's `tool_name`**, so a corpus case stores the
   command its turn actually replayed against (self-contained cases preserved: a shell case
   stores the shell command, an fs case stores the fs command). The trajectory case's
   `server_command` resolves by the final turn's `tool_name`.
3. **CLI.** `belay phase0 run` gains `--shell-server CMD` (a **single string**, shlex-split at
   use — argparse cannot host a second REMAINDER). Help text states the shape and the
   requirement to quote. Absent flag = today's behavior, unchanged (regression fixture).
4. **Mint verify command.** `eval/minting_driver/entrypoint.py` `verify_command()` gains the
   dual-server form (fs `--server` + `--shell-server` with the resolved rootless shell
   entrypoint) when `cfg.toolset == "filesystem+shell"`; the filesystem-only form is unchanged.
5. **Honest verdicts preserved.** A shell turn that replays with an unreadable outcome is
   UNVERIFIED with its named cause (existing `_replayed_is_error` None path); a shell turn
   that cannot replay at all is UNVERIFIED with the engine's cause; **never a silent miss,
   never PASS on an unobservable** — pinned by test per surface.
6. **The dual-server live smoke runs** (operator step, `-m manual`, never CI —
   `docs/planning/trajectory-toolset-rescope/mint-dual-server/smoke.md`, currently NOT RUN).
   Result committed per the freeze protocol (verbatim output; finding classes pre-registered:
   model / wiring / instrument).

## Out of scope

- Any change to the trajectory rule, the claim classifier, or the verdict vocabulary.
- A2/A3 semantics; trace-format or ledger-schema changes; `belay phase0 combine` sections.
- Per-tool routing for any tool other than `run_process` (the mint boundary has exactly two
  servers; the map shape must not over-abstract).
- Multi-server corpus `run` support (a stored case is single-command and stays that way).
- `--toolset shell`-only.

## Acceptance criteria (failing tests written first)

- **AC-1**: a `run_process` turn with `shell_server_command` given replays against it —
  asserted through the real `verify_turn` + `replay_turn` (rootless fixture server, e.g.
  `tests/fixtures/shell_command_server.py`), exit-0 reply read → `TurnVerdict.replayed_is_error
  is True` (trajectory evidence becomes observable).
- **AC-2**: every non-`run_process` turn with `shell_server_command` given still replays
  against `server_command` — routing is by exact tool name, pinned by test.
- **AC-3**: `run_batch` with `shell_server_command=None` behaves byte-for-byte as today —
  regression fixture over an fs-only batch.
- **AC-4**: corpus ingest stores the resolved command per flagged turn (a shell turn's case
  carries the shell command; `corpus show` proves it), and the trajectory case resolves by the
  final turn's tool name.
- **AC-5**: a shell turn whose replayed outcome is unreadable → UNVERIFIED with the named
  cause; a shell turn that never replays → UNVERIFIED with the engine's cause; never PASS
  (property asserted across both surfaces: ledger bucket and `TurnVerdict.cause`).
- **AC-6**: `--shell-server` parses on the CLI and reaches `run_batch` (single-string +
  shlex-split pinned); absent flag → `shell_server_command=None`.
- **AC-7**: `verify_command()` emits the dual-server form for `filesystem+shell` and the
  byte-identical old form for `filesystem`.
- **AC-8**: deterministic, no network, CI-safe (fixture servers; the darwin-gated e2e stays
  darwin-gated; the live smoke stays `-m manual`).
- **AC-9 (manual, operator)**: the dual-server smoke runs end to end on live servers and its
  committed output reports PASS or a named finding class.

## Dependencies & sequencing

- Requires: v0.17.0 engine (relocation, composite, trajectory rule), `eval/servers/` install
  (operator step).
- Parallel-safe with aspect 2 (registries); the smoke and the freeze scripts need both.
- `_EVIDENCE_TOOL` import from `belay.verify.trajectory` is a read-only import (no cycle: turn
  already imports invariants, trajectory imports nothing from turn).
