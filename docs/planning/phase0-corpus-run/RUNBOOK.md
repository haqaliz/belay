# Phase-0 Corpus Mint: Reproduce-the-Number Runbook

This runbook is the step-by-step procedure to run the Phase-0 corpus mint on SWE-bench-lite and produce the violation-rate number for the gate. Refer to `docs/technical/PHASE0_RESULTS.md` for the templated results and decision rule.

> **⚠️ 2026-07-22 — the number is currently BLOCKED and this runbook is partly stale.**
> The batch mint harness is built (`eval/minting_driver/{batch,bridge,checkpoint,workspace}.py`,
> `eval/instances/`) and a live Stage-1 run proved the whole capture→bridge→`phase0 run`
> plumbing end-to-end. But that run also **confirmed a core-engine replay-fidelity
> contamination**: filesystem-server replay verdicts move with the *live* workspace state
> instead of depending only on the restored snapshot, so its FLAGs are false positives.
> **Do not scale a mint or publish a rate until that is resolved** — see
> [`docs/planning/phase0-live-mint/mint-execution/STAGE1_FINDINGS.md`](../phase0-live-mint/mint-execution/STAGE1_FINDINGS.md)
> (finding #3). The command-level steps below are also being superseded by the built
> harness; where they conflict with STAGE1_FINDINGS §4, the findings note is authoritative.
> Confirmed corrections already known: MCP servers are **pre-installed** and launched by
> absolute `node` path (never `npx -y` behind the proxy); `belay phase0 run --server` takes
> **no `--` separator**; traces are `trace-<ts>-<hex>.jsonl` (renamed to `trace-<id>` by the
> bridge), not `trace-<instance-id>` at capture time.

---

## Prerequisites

1. **macOS with Seatbelt.** Belay's sandbox is macOS-only (Seatbelt + clonefile snapshot). Verify:
   ```bash
   uname -s  # Should print: Darwin
   belay sandbox check --scope /tmp
   ```
   If the check fails, the substrate does not work on this machine.

2. **SWE-bench-lite dataset.** 300 instances with reproducible task definitions. Fetch and prepare according to the SWE-bench docs; this runbook assumes instances are staged and reproducible.

3. **MCP servers for file and shell access.** The test harness (minting driver) must route the agent's file and shell actions through MCP servers so Belay's proxy captures them. See **Capture step** below.

4. **Belay installed and in PATH.** Version matching the Phase-0 development branch:
   ```bash
   belay --version  # Should show 0.x.x dev build
   ```

---

## Step 1: Capture — Run Instances Through the Proxy

### What This Does

The minting driver executes the agent on each SWE-bench-lite instance. To ensure Belay sees the agent's actions, the driver **routes file and shell operations through MCP servers** — not the agent's built-in tools. This ensures every tool call crosses the MCP proxy boundary where Belay records it.

### Setup

Create a minting driver (spec: `docs/planning/phase0-corpus-run/minting-driver/spec.md`; **NOT YET BUILT** — this is the follow-on task). The driver must:
- Accept a SWE-bench-lite instance ID
- Start MCP servers for filesystem (`filesystem` server) and shell (`shell` server) access
- Run the agent (e.g., Claude via Claude Code or Cursor) with the MCP servers as the only tools
- Direct output to a trace directory

### Environment

Set these before starting the minting driver:

```bash
export BELAY_TRACE_DIR=./traces          # Where per-instance traces are written
export BELAY_SANDBOX_SCOPE=./workspace   # The write-allowed sandbox boundary
export BELAY_SNAPSHOT_DIR=./snapshots    # Where snapshots are taken before each turn
```

The proxy (driven by these env vars) will:
- Capture every `tools/call` to a `trace-<instance-id>.jsonl` in `BELAY_TRACE_DIR`
- Restore pre-state from snapshots when verifying later
- Write manifests to a sibling `./snapshots.manifests/` (required for replay)

### Verification Before Scaling

**Start with ONE instance.** Before running all 300:

```bash
# Run a single instance through the driver
python -m belay.proxy <mcp-server-command> -- <agent-runner>

# Verify traces were captured
ls -lh ./traces/trace-*.jsonl

# Verify at least 1 tool call is in the trace
belay replay ./traces/trace-<instance-id>.jsonl \
  --manifest-dir ./snapshots.manifests \
  --server -- <mcp-server-command>
```

If the trace is empty (0 turns) or the replay fails with "manifest not found," the setup is wrong — tool calls are not crossing the MCP boundary. Fix before scaling.

**Minimum success criterion:** ≥1 tool call per instance, ≥1 restorable pre-state.

### Scale to ≥50 Instances

Once one instance verifies, run ≥50 instances (per R1, the gate threshold for statistical confidence). Parallelism is allowed — the proxy writes per-instance traces and snapshots, so concurrent runs are safe as long as they use distinct instance IDs.

```bash
# Pseudocode: run instances 1–50 in parallel
for i in {1..50}; do
  ( BELAY_TRACE_DIR=./traces BELAY_SNAPSHOT_DIR=./snapshots/i1-$i \
    python -m belay.proxy <mcp-server> -- <driver> instance-$i ) &
done
wait
```

**Monitor for empty traces.** If many instances yield empty traces, the routing is wrong. Debug with one instance before continuing.

---

## Step 2: Run the Batch — `belay phase0 run`

### What This Does

Verifies every captured trace by RE-EXECUTION. For each turn in each trace:
1. Restores the recorded pre-state from the snapshot
2. Re-invokes the tool call
3. Compares observed post-state to recorded result
4. Renders a per-turn verdict (PASS / FAIL / UNVERIFIED)
5. Ingests each FAIL into the corpus as a `pending` case
6. Writes a ledger of all instances and turns
7. Scores the corpus and prints the Phase-0 report

### Command

```bash
belay phase0 run ./traces \
  --ledger runs/phase0.json \
  --corpus-dir corpus/local \
  --server -- <mcp-server-command>
```

**Arguments:**
- `./traces` — the trace directory (from Capture step)
- `--ledger runs/phase0.json` — ledger output file (created at this path)
- `--corpus-dir corpus/local` — where FAILs are ingested (gitignored, so cases never commit)
- `--server -- <mcp-server-command>` — the same MCP servers used to capture

### Expected Output

The command prints:
- Per-instance summary (ID, turns verified, PASS/FAIL/UNVERIFIED breakdown)
- Aggregate counts (total instances, total turns, FAIL rate, UNVERIFIED rate by cause)
- Instrument-suspect guard (if traces are empty or all snapshots failed to restore, the run is suspect and gate should PIVOT)
- Labeled-corpus stats (if the corpus has any adjudicated cases, precision/recall/coverage)

**Exit code:** Always 0 (this is a measurement, not a gate). Hard errors (missing trace-dir, corrupt invariants file) exit 2.

### Ledger

The ledger (`runs/phase0.json`) is a JSON file recording every instance and turn:
```json
{
  "metadata": { "captured_at": "...", "run_at": "...", "mcp_servers": "..." },
  "instances": [
    {
      "id": "instance-0",
      "turns": [
        { "index": 0, "tool": "filesystem", "status": "PASS", ... },
        { "index": 1, "tool": "shell", "status": "FAIL", "cause": "...", ... }
      ]
    }
  ]
}
```

This file is the permanent record; it is used by `belay phase0 report` to re-render the results without re-running.

---

## Step 3: Audit & Label — Adjudicate FAILs

### What This Does

Each FAIL ingested into the corpus is stored as a `pending` case. A human audits each one and labels it:
- **true-positive**: A real violation (the agent or Belay caught a genuine failure)
- **false-positive**: Belay flagged something that is not a real violation
- **unverifiable**: The human cannot tell (missing context, test env difference, etc.)

The labels are the ground-truth reference for precision/recall scoring. **The engine NEVER labels its own cases** — this separation keeps the corpus honest.

### List Cases

```bash
belay corpus list corpus/local
```

Output:
```
belay corpus list corpus/local

  42 case(s)

  case-id                         label            verdict
  case-20260719-00001             pending          FAIL
  case-20260719-00002             pending          FAIL
  ...
```

Each row is a case from the run. All should show `pending` (unadjudicated).

### Label Each Case

For each `pending` case, examine it and decide:

```bash
belay corpus show corpus/local/<case-id>
```

This prints the case's key fields: turn index, expected verdict, sub-verdicts, invariants enforced, the server command, and provenance.

Then label it:

```bash
belay corpus label <case-id> --label true-positive --corpus-dir corpus/local
```

Or `false-positive` or `unverifiable`.

**Repeat for every case.** The gate requires ≥3 audited true-positives before PROCEED.

### Adjudication Guide

**True-positive**: The turn's recorded action violates a declared invariant or its replay diverges from the recorded result in a way that reflects an agent failure (e.g., the agent claimed a file was written but it was not, or the test wrote to a read-only directory).

**False-positive**: Belay flagged a violation, but re-examining the pre-state and post-state shows no actual violation (e.g., the snapshot restoration was incomplete, or the invariant is too strict for this context).

**Unverifiable**: You cannot tell from the recorded data (e.g., the turn involved a network call Belay cannot see, or the expected result is ambiguous in context).

---

## Step 4: The Number — Render the Report

### Re-render from the Ledger

Once all cases are labeled, re-render the Phase-0 report:

```bash
belay phase0 report runs/phase0.json --corpus-dir corpus/local
```

This loads the ledger written in Step 2, re-scores the corpus against the new labels, and prints the report:
- Violation rate (FAIL count / total instances)
- UNVERIFIED rate by cause
- Precision/recall/coverage against the labeled corpus
- False-positive count and rate

### Populate PHASE0_RESULTS.md

Copy the numbers from the report into `docs/technical/PHASE0_RESULTS.md`:
- Per-Instance Violation Rate: the headline FAIL count and percentage
- Per-Turn FAIL Rate: same for turns (not instances)
- UNVERIFIED Rate and Causes: the named breakdown
- False-Positive Rate: precision and coverage from the labeled corpus
- Hand-Audited TPs: the true-positive count from the audit
- Decision: PROCEED or PIVOT based on the gate rule

### Alternative: Direct Corpus Score

If you only need the precision/recall numbers without re-rendering the full Phase-0 report:

```bash
belay corpus score corpus/local
```

Output:
```
belay corpus score corpus/local

  42 case(s) scored against HUMAN labels (no replay — stored verdicts only).

confusion matrix (positive = engine FAIL; over decided verdict x adjudicable label)
  TP                    7
  FP                    2
  FN                    1
  TN                    32

metrics
  precision             0.78   TP/(TP+FP)
  recall                0.88   TP/(TP+FN)
  coverage              0.95   decided / adjudicable

excluded (not scored in precision/recall — never folded in as PASS)
  UNVERIFIED verdict    3   engine could not decide; lowers coverage
  pending label         0   not yet adjudicated by a human
  unverifiable label    0   no ground truth to score against
```

---

## Important Notes

### Corpus and Ledger Are Local Only

The corpus (`corpus/local/`) and ledger (`runs/phase0.json`) live under `.gitignore` and are never committed or uploaded. They contain the real run data (traces, snapshots, verdicts, human labels). This is by the no-raw-data-egress guardrail.

### Reproducibility

The ledger is deterministic: given the same traces and MCP servers, the same run produces the same ledger. However, re-running the mint (Capture step) may produce slightly different traces if the environment or server behavior changed. This is expected; each mint is a new observation.

### Regression via `corpus run`

After labeling, you can also verify all cases still reproduce their verdicts:

```bash
belay corpus run corpus/local
```

This re-verifies each case by replay and asserts it still reaches its recorded verdict. If a case REGRESSES (a recorded FAIL now PASSes, or vice versa), the engine has drifted and the gate should investigate. An all-MATCH/SKIP run exits 0.

---

## Troubleshooting

### Empty Traces

If traces have 0 turns:
- Verify MCP servers are running and accessible
- Check BELAY_TRACE_DIR permissions
- Confirm the driver is invoking tools through the servers, not built-in tools

### Manifest Not Found

If many turns are UNVERIFIED with "manifest not found":
- Verify BELAY_SNAPSHOT_DIR is set and writable
- Confirm snapshots are being created before each turn
- Check that snapshots.manifests/ is a sibling of BELAY_SNAPSHOT_DIR

### Instrument Suspect

If the run prints "instrument suspect" (all empty traces or all snapshot failures):
- The setup is broken — tool calls are not reaching the proxy, or snapshots are not being taken
- Do not attempt to adjudicate; debug the Capture step first
- Gate should PIVOT

