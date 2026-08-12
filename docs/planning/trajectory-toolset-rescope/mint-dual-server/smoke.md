# Dual-server mint smoke — runbook and status

Aspect `mint-dual-server` · Phase 4 · 2026-08-12 · live-run record for
`tests/test_minting_driver_dual_server_smoke.py` (committed in this unit).

## What the smoke proves

One mint instance driven end to end with `--toolset filesystem+shell`, then verified:

1. Both pinned servers resolve and launch (filesystem + shell).
2. The merged tool list reaches the trace's `tools/list` — `run_process` present,
   **verbatim and un-prefixed** (the trajectory evidence gate matches that exact name).
3. A `run_process` turn crossed the gated boundary.
4. **Per-instance shell cwd, on live evidence** — the steered probe
   (`touch BELAY_PROBE.txt`, no path prefix) must land at the instance workspace root,
   proving the shell server spawned with `cwd=layout.work_dir`.
5. The captured `run_process` turn replays verifiably against the rootless pinned
   shell server command: verdict **PASS or UNVERIFIED-with-cause** — never the
   no-snapshot `NOT_VERIFIABLE` shape (a silent miss), never FAIL (a finding to
   record and stop, per the plan's Phase 4: *"if the shell server misbehaves on the
   smoke instance, record the finding (it is a finding, not a defect) and stop — do
   not iterate the pinned server"*).
6. The stock `belay phase0 run` resolves the capture (exit 0, no `INSTRUMENT
   SUSPECT`); its per-turn rows are echoed, never asserted away — shell-turn rows
   replayed through the single `--server` filesystem command are not expected to
   reproduce, and any such rows are a recorded finding for the successor mint's
   verify composition.

## Runbook (operator)

Prerequisites: macOS (Seatbelt), Node 20/22, the `claude` CLI logged in on your own
subscription (`--provider claude-cli` — the path the successor mint freezes), and
**both pinned servers installed**:

```bash
npm install --prefix eval/servers \
  @modelcontextprotocol/server-filesystem@2026.7.10 mcp-server-commands@0.8.2
```

(Outside the sandbox, from the repo root — the exact command `MissingServerError`
prints if you skip this. If you keep the install elsewhere, e.g.
`~/dev/at/holder/belay/servers`, export `BELAY_EVAL_SERVER_ROOT` instead.)

Then, with `BELAY_EVAL_LIVE=1`:

```bash
export BELAY_EVAL_LIVE=1

uv run pytest tests/test_minting_driver_dual_server_smoke.py -m manual -v
```

The smoke itself mints into `eval/mint/live-smoke-dual-server/` (override the root with
`BELAY_EVAL_MINT_ROOT`), refuses to re-drive an instance the checkpoint already
records (anti-re-roll — re-running after a *setup* failure is a fresh root, never a
checkpoint edit), and fails fast with the `npm install` command if either server is
missing. `BELAY_EVAL_MODEL` overrides the oracle model id.

Freeze-able CLI form (the same run, as the runbook documents it in `eval/README.md`):

```bash
uv run python -m eval.minting_driver one pytest-dev__pytest-7432 \
  --root eval/mint/live-smoke-dual-server \
  --registry eval/instances/pool.json \
  --provider claude-cli --model claude-opus-5 \
  --toolset filesystem+shell
```

## Status

**NOT RUN — no result exists.**

The live run is an **operator step** that happens only once `eval/servers/` is
installed (the worktree in which this aspect shipped does not have it — `eval/servers/`
is gitignored and absent, so the smoke cannot run there by construction). This file was
committed together with the smoke test, **before** any run, under the freeze protocol:
the tooling is frozen first so the output cannot be fitted to it.

**This unit therefore records no smoke outcome of any kind.** There is no passed smoke,
no failed smoke, no verdict, no rate, and no evidence that the dual composition works on
live servers yet — the deterministic composite/`cwd`/`--toolset` tests are green, and
that is all. When the operator runs the smoke, this file is updated with what it showed
(its echoed facts, findings included), exactly as a smoke record should read — n=1,
not a base rate, and never a published number.

## Findings to record if the smoke trips

- The oracle never ran the probe (`BELAY_PROBE.txt` absent) — a **model** finding:
  the boundary offered `run_process` but the model chose not to use it; inspect the
  trace's calls before concluding anything about the wiring.
- The probe landed outside the workspace — a **wiring** finding: the shell session's
  cwd was not the instance workspace.
- The `run_process` turn's replay verdict was FAIL, or UNVERIFIED without a cause, or
  the no-snapshot `NOT_VERIFIABLE` shape — an **instrument** finding, to be
  adjudicated on the committed capture before anything else happens.
- The stock `belay phase0 run` reports `INSTRUMENT SUSPECT` — a **wiring** report (the
  same class as `bridge_capture`), never a result.

## Guard mechanics

Same three as every live smoke, all required: `sys.platform == "darwin"` (gated
capture is Seatbelt-only), `BELAY_EVAL_LIVE=1` (the human opt-in), and the `manual`
marker — registered in `pyproject.toml`, excluded from the default run by
`addopts = "-m 'not manual'"`, selected explicitly with `-m manual`. The test can never
run in CI.
