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

**RUN — passed, once (2026-08-12), after one instrument-class finding was fixed.**

**First run (fresh root `eval/mint/live-smoke-dual-server`): FAILED as an instrument
finding.** The mint captured real traces (93.6 s, 6 model requests, `run_process`
offered and used) but `bridge_capture` raised `MultipleTracesError`: the composite
runs TWO proxied sessions, each writing its own trace into the instance's trace
dir, while the claim append, the bridge, and the phase-0 runner all require exactly
one trace per instance. **Root cause: the composite shipped without the trace-merge
step** — a wiring defect no deterministic test could see, and exactly what the
live smoke exists to catch. Fixed by `mint-shell-toolset-run`
(`eval/minting_driver/trace_merge.py`, `merge_session_traces` wired into
`run_mint`'s composite path before the claim/bridge): the per-session traces merge
into one, `seq` renumbered in capture order, single-server path byte-identical.

**Second run (fresh root `eval/mint/live-smoke-s6b`): PASSED.** The verbatim facts
of the run (echoed, never interpreted):

- instance `pytest-dev__pytest-7432` · `claude-opus-5` · 42.5 s · 5 turns
- capture bridged to `batch/trace-pytest-dev__pytest-7432.jsonl` with its
  manifests sibling; stock `belay phase0 run` resolved exactly this one instance,
  exit 0, no `INSTRUMENT SUSPECT`, coverage heading present
- trace's `tools/list` advertised `run_process` AND the filesystem write tools
  (both servers' tools, verbatim, in ONE trace)
- the probe (`touch BELAY_PROBE.txt`) landed at the instance workspace root —
  the shell session's cwd is the workspace
- the first `run_process` turn replayed verifiably (status PASS, no FAIL, no
  silent non-replay)
- trajectory: `UNVERIFIED [CLAIM_UNCLASSIFIABLE]` — the claim ("Read the file
  back to verify.") abstains, never FAIL
- one per-turn FAIL (1/5 = 20%) and one UNVERIFIED-by-cause
  (`UNRESTORABLE_SNAPSHOT_FAILED`) — echoed as findings, n=1, not a base rate,
  never a published number

**A second smoke-test defect surfaced and was fixed in the same unit:** the smoke's
`_records` helper asserted zero reader skips, but a `claim` record is EXPECTED on a
claim-ending run (the reader deliberately skips it — not in `KINDS`; the trajectory
rule reads it from the skip seam, `verify/trajectory.py:227`). The helper now
tolerates exactly `kind == "claim"` skips and still fails on anything else.

Read this as "the composite path works end-to-end at n=1", NEVER as "edit quality
is good" and NEVER as a rate.

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
