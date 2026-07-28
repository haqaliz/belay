# Phase-0 Corpus Mint: Reproduce-the-Number Runbook

This runbook is the step-by-step procedure to run the Phase-0 corpus mint on SWE-bench-lite and produce the violation-rate number for the gate. Refer to `docs/technical/PHASE0_RESULTS.md` for the templated results and decision rule.

> **The mint was BLOCKED twice on replay fidelity. Both blocks are lifted — in this order.**
> The history is kept rather than deleted, because it is the evidence that the guards work.
>
> 1. **2026-07-22 — the single-instance block.** The live Stage-1 run proved the whole
>    capture→bridge→`phase0 run` plumbing end-to-end, and in doing so confirmed a core-engine
>    **replay-fidelity contamination**: filesystem-server replay verdicts moved with the
>    *live* workspace state instead of depending only on the restored snapshot, so its FLAGs
>    were false positives
>    ([`STAGE1_FINDINGS.md`](../phase0-live-mint/mint-execution/STAGE1_FINDINGS.md), finding
>    #3). **Lifted by `replay-absolute-path-fidelity`, released in v0.4.0** (2026-07-22): the
>    gate records the workspace root in each snapshot manifest (`source_root`) and replay
>    relocates it into the scratch.
> 2. **Then the *batch* block, which was still real.** `belay phase0 run` takes ONE static
>    `--server` command for a whole directory, but a Phase-0 batch is heterogeneous — its
>    traces come from different workspaces. A server rooted at the wrong workspace rejects the
>    scratch paths and the divergence reads as a **FAIL**. **Lifted by
>    `replay-batch-server-rooting`** (merged 2026-07-23, shipped in v0.5.0): the `'{workspace}'`
>    placeholder resolves per trace, and a replay that cannot be correctly rooted is
>    **UNVERIFIED**, never a fabricated FAIL. Its spec is
>    [`phase0-mint-execution/replay-batch-server-rooting/spec.md`](../phase0-mint-execution/replay-batch-server-rooting/spec.md).
>
> **Neither block is outstanding.** The three Stage-1 captures re-verified against the current
> tree discriminate correctly (clean captures `VERIFIED_CLEAN` with 0 FAIL; the planted corrupt
> success `VERIFIED_FLAGGED`), with 0 UNVERIFIED. The steps below have been corrected against
> the built harness and the real CLI; where a step here conflicts with
> [`eval/README.md`](../../../eval/README.md), **`eval/README.md` is authoritative** — it lives
> next to the code it describes.

---

## Prerequisites

1. **macOS with Seatbelt.** Belay's sandbox is macOS-only (Seatbelt + clonefile snapshot). Verify:
   ```bash
   uname -s  # Should print: Darwin
   belay sandbox check --scope /tmp
   ```
   If the check fails, the substrate does not work on this machine.

2. **SWE-bench-lite instance registry.** SWE-bench-lite's test split is **300 instances**; that
   is the *source pool*, not the mint. `eval/instances/pool.json` holds the **166** that survive
   the strict eligibility filters, and `eval/instances/selected.json` is the committed,
   seeded draw from it — **65 real instances + 3 controls = 68**. The number the gate needs is a
   denominator of **≥50** (see "Scale to ≥50 Instances"); 300 is never the target. The pool is
   already fetched and committed, so nothing needs to be downloaded to run a mint.

3. **MCP servers, pre-installed.** The minting driver routes the agent's file actions through an
   MCP server so Belay's proxy captures them. The servers are **pinned and pre-installed** into
   a gitignored `eval/servers/`, then launched by **absolute entrypoint path** — run once, from
   the repo root, outside the sandbox:
   ```bash
   npm install --prefix eval/servers \
     @modelcontextprotocol/server-filesystem@2026.7.10 mcp-server-commands@0.8.2
   ```
   **Never `npx -y` behind the gated proxy.** A gated run denies network and `~/.npm` writes by
   design, so `npx` *hangs* rather than failing loudly (and npm misattributes it to a
   root-owned-cache bug — a red herring). `eval/README.md` records the measurement.

4. **A BYOK model endpoint.** The driver is BYOK and never proxies through Belay:
   ```bash
   uv sync --group eval
   export OPENAI_BASE_URL=...   # the OpenAI-compatible endpoint
   export OPENAI_API_KEY=...    # required, never substituted
   ```

5. **Belay installed and in PATH.** Version matching the Phase-0 development branch:
   ```bash
   belay --version  # Should show 0.x.x dev build
   ```

---

## Step 1: Capture — Run Instances Through the Proxy

### What This Does

The minting driver executes the agent on each SWE-bench-lite instance. To ensure Belay sees the agent's actions, the driver **routes file operations through an MCP server** — not the agent's built-in tools. This ensures every tool call crosses the MCP proxy boundary where Belay records it.

### Setup

**The minting driver is built** — it shipped in **v0.3.0** and lives at `eval/minting_driver/`
(`eval/README.md` is its documentation). It is **eval-only**: not a product surface, and never
`belay mint ...`; the entry point is a plain module invocation. It already does everything this
step needs:

- takes a SWE-bench-lite instance id from `eval/instances/`, and prepares that instance's
  workspace at its `base_commit` from a cached bare clone;
- spawns the pinned filesystem MCP server **behind** `python -m belay.proxy`, with the gated
  capture environment set;
- drives one `tools/call` at a time — **sequential by construction** (see the warning below);
- renames each capture into the layout the stock `belay phase0 run` resolves (`bridge_capture`).

**Coverage limit, stated plainly:** the entrypoint drives the **filesystem server only**
(`preflight_servers` resolves `"filesystem"`). The pinned shell server (`mcp-server-commands`)
exists and is supported by the harness, but the minted denominator covers file actions. Say so
wherever the number is published.

### Environment

The driver sets these itself (`capture.gated_env`); they are listed here because they are what
makes a turn *verifiable*, and because a hand-run capture must set the same three:

```bash
BELAY_TRACE_DIR=<root>/<instance-id>/traces        # Where the trace is written
BELAY_SANDBOX_SCOPE=<root>/<instance-id>/workspace # The write-allowed sandbox boundary
BELAY_SNAPSHOT_DIR=<root>/<instance-id>/snapshots  # Snapshots taken before each turn
```

`BELAY_SNAPSHOT_DIR` must be a **sibling** of the workspace, never inside it. Setting
`BELAY_SANDBOX_SCOPE` without `BELAY_SNAPSHOT_DIR` is a hard refusal, not a downgrade.

The proxy (driven by these env vars) will:
- Capture every `tools/call` to **`trace-<UTC-timestamp>-<8hex>.jsonl`** in `BELAY_TRACE_DIR`.
  **The proxy does NOT name traces after the instance** — it does not know the instance id. The
  **bridge** (`eval/minting_driver/bridge.py`) is what moves that file to
  `<root>/batch/trace-<instance-id>.jsonl`, alongside its
  `<root>/batch/trace-<instance-id>.manifests/`. That rename is what makes the batch resolvable
  by the stock `belay phase0 run`; a mis-wire here reads as `INSTRUMENT SUSPECT`, i.e. a *fake*
  PIVOT.
- Restore pre-state from snapshots when verifying later
- Write manifests to a sibling `<...>/snapshots.manifests/` (required for replay)

### Verification Before Scaling

**Start with ONE instance.** Never open a batch against an unproven setup:

```bash
# Run a single instance through the driver
uv run python -m eval.minting_driver one pallets__flask-4045 \
  --root eval/mint/stage1 --registry eval/instances/stage1.json

# Verify a trace was captured and bridged into the batch layout
ls -lh eval/mint/stage1/batch/trace-*.jsonl

# Verify at least 1 tool call replays against its restored pre-state
belay replay eval/mint/stage1/batch/trace-pallets__flask-4045.jsonl \
  --manifest-dir eval/mint/stage1/batch/trace-pallets__flask-4045.manifests \
  --server node eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js '{workspace}'
```

> **No `--` separator after `--server`.** It is `nargs=REMAINDER`, so *everything* after
> `--server` already **is** the server command; a `--` would be handed to `node` as its first
> argument and the server would fail to start. This applies to `belay replay`, `belay verify`,
> `belay corpus add` and `belay phase0 run` alike. The same rule holds for
> `python -m belay.proxy <server-command>`: the entire argv after `-m belay.proxy` is the
> downstream server command, with no separator (`eval/minting_driver/capture.py:29-37`).

`'{workspace}'` is quoted and passed as **one whole argument**: replay substitutes each trace's
own recorded `source_root` before relocating it into the scratch, which is what makes a single
static `--server` command correct for a batch captured from many workspaces.

If the trace is empty (0 turns) or the replay fails with "manifest not found," the setup is wrong — tool calls are not crossing the MCP boundary. Fix before scaling.

**Minimum success criterion:** ≥1 tool call per instance, ≥1 restorable pre-state.

### Scale to ≥50 Instances

Once one instance verifies, run the committed selection. The pre-registered gate needs a
denominator of **≥50** captured instances (not 300 — see Prerequisite 2); `selected.json` draws
65 real instances plus 3 controls so there is headroom for attrition.

```bash
uv run python -m eval.minting_driver batch \
  --root eval/mint/stage3 --registry eval/instances/selected.json
```

> ### 🛑 The mint is SEQUENTIAL BY DESIGN. Do not parallelise it.
>
> An earlier revision of this runbook said *"parallelism is allowed"* and offered a
> `for … &` shell loop. **That was wrong, and following it corrupts the instrument.** Three
> independent reasons, each sufficient on its own:
>
> 1. **`StdioMcp` is not thread-safe** and is explicitly not meant to have two `request` calls
>    in flight at once (`eval/minting_driver/transport.py:212-213`). Two concurrent requests on
>    one stdio transport interleave newline-JSON frames.
> 2. **One `tools/call` in flight is R7 by construction.** The driver's guarantee that it never
>    has more than one call outstanding is what makes the recorded turn order mean anything —
>    it is enforced by a deterministic control-flow test in CI, and a wrapper loop launched
>    outside the driver silently voids it.
> 3. **Concurrency breaks per-turn snapshot/restore**, which is *the* thing that makes a turn
>    verifiable. The pre-state snapshot is taken between the request being observed and it
>    reaching the server; overlapping turns mean the restored "pre-state" is some other turn's
>    post-state, and the resulting verdict is grounded in nothing.
>
> The way to run more instances is to let `run_mint` walk the registry. It is sequential,
> resumable and error-contained: that is the supported scale mechanism, and there is no
> supported parallel one.

**Monitor for empty traces.** If many instances yield empty traces, the routing is wrong. Debug with one instance before continuing.

### Resuming, and the quota circuit breaker

A batch is **resumable through its checkpoint**, and the resume rule is also the honesty rule:

- `captured` and `failed` count as **done** — re-running the same `--root` never re-drives them.
  There is deliberately **no `--force`**: silently re-rolling until the number looks good is
  precisely the dishonesty this project exists to prevent.
- **`no_observation`** is the third disposition, and it is **re-armed** by a resume. It means
  the instance was never actually driven — no session ran, no trace exists, nothing was
  observed — so re-driving it re-rolls nothing.

**A provider quota cap stops the batch rather than burning the queue.** `resilience.classify_error`
sorts a provider exception into `quota` (a daily/period cap — 429 + `RESOURCE_EXHAUSTED`, or a
retry hint > 600s → record `no_observation` and **stop**), `transient` (bounded retry with
backoff), or `terminal` (record `failed`, continue). Instances *after* the stopping one stay
**absent** from the checkpoint entirely — visibly missing and still eligible. Re-run the same
`--root` once the cap resets.

This exists because it was measured, not theorised: on 2026-07-24 a Stage-3 mint hit a
250-requests-per-day cap on instance 3 of 68 and fed the remaining **56 instances into the same
wall in 3m48s**, every one recorded as `failed` and therefore permanently skipped by any resume.
The provider's own `retryDelay` was ≈10h50m — no backoff could have reached it. A shrunken
denominator is the R6 false-zero failure mode one layer up.

For a checkpoint written *before* `no_observation` existed, `eval/scripts/rearm_checkpoint.py`
is the one-off migration — it rewrites a `failed` entry to `no_observation` **only** if its
recorded reason classifies `quota` under that same classifier, and never touches a `captured`
entry:

```bash
# always look first — this rewrites the only record of a live, unrepeatable mint
uv run python -m eval.scripts.rearm_checkpoint --checkpoint eval/mint/s3/checkpoint.json --dry-run
uv run python -m eval.scripts.rearm_checkpoint --checkpoint eval/mint/s3/checkpoint.json
```

---

## Step 2: Run the Batch — `belay phase0 run`

### What This Does

Verifies every captured trace by RE-EXECUTION. For each turn in each trace:
1. Restores the recorded pre-state from the snapshot
2. Re-invokes the tool call
3. Compares observed post-state to recorded result
4. Renders a per-turn verdict (PASS / WARN / FAIL / UNVERIFIED), reduced worst-status-wins from
   its per-axis sub-verdicts. `NOT_COVERED` is **sub-verdict-only** — it marks a dimension Belay
   has no instrument for (today, a tool's `openWorldHint: false` network promise) and is dropped
   before ranking, so it can never be a turn's reduced status. A `PASS` therefore means *"passed
   on the dimensions Belay checks"*, and **the coverage line must travel with the status**
   anywhere the number is quoted
5. Ingests each FAIL into the corpus as a `pending` case
6. Writes a ledger of all instances and turns
7. Scores the corpus and prints the Phase-0 report

### Command

```bash
belay phase0 run eval/mint/stage3/batch \
  --ledger runs/phase0.json \
  --corpus-dir corpus/local \
  --server node eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js '{workspace}'
```

The mint **prints this exact line when it finishes** (`entrypoint.verify_command`), with the
absolute server entrypoint filled in — prefer the printed line over retyping this one.

**Arguments:**
- `eval/mint/<root>/batch` — the bridged trace directory (from the Capture step); each file in
  it is `trace-<instance-id>.jsonl` beside its `trace-<instance-id>.manifests/`
- `--ledger runs/phase0.json` — ledger output file (created at this path; its parent directory
  is created for you)
- `--corpus-dir corpus/local` — where FAILs are ingested (gitignored, so cases never commit)
- `--server node <abs-entrypoint> '{workspace}'` — the same MCP server used to capture.
  **No `--` separator** (`nargs=REMAINDER`), and `'{workspace}'` quoted as one whole argument so
  replay resolves each trace's own recorded `source_root`. A trace that recorded no root is
  `UNVERIFIED`, never rooted at a guess; a command that cannot be rooted at the recorded
  workspace is `UNVERIFIED` too. Both appear by name in the UNVERIFIED-by-cause table rather
  than as a fabricated FAIL.

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
belay corpus show <case-id> --corpus-dir corpus/local
```

The case id is a **positional argument** and the corpus directory is the `--corpus-dir` option
(default `corpus/local`) — not a single joined path. Note the asymmetry with `corpus list`,
`corpus run` and `corpus score`, which take the corpus directory positionally; `corpus show`
and `corpus label` both take `<case-id> --corpus-dir <dir>`.

This prints the case's key fields: turn index, the expected reduced status **and** its per-axis
sub-verdict set with each message, the human label, invariants enforced, the server command, and
provenance. Read the sub-verdict messages, not only the reduced status: a `NOT_COVERED`
dimension (today, a tool's `openWorldHint: false` network promise) is a dimension Belay has no
instrument for, and it is distinct from `UNVERIFIED`.

Then label it:

```bash
belay corpus label <case-id> --label true-positive --corpus-dir corpus/local
```

Or `false-positive` or `unverifiable`.

**Repeat for every case.** The gate rule is **pre-registered**, and the canonical statement of
it lives in `docs/technical/PHASE0_RESULTS.md` (transcribed verbatim from
`docs/planning/phase0-live-mint/prd.md`). Read it there rather than from a paraphrase; in
outline it is **PROCEED** iff ≥3 *independent* hand-audited true positives survive audit **AND**
the violation-rate denominator is ≥50 **AND** `INSTRUMENT SUSPECT` did not fire. "Independent"
means distinct root causes — three flags from one mis-annotated tool count as **one** finding.
**A FAILing control voids the mint** and is escalated, never quietly excluded. The violation rate
itself is reported, never thresholded.

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
- Hand-Audited TPs: the true-positive count from the audit, each with its root cause recorded
  beside it so a reader can judge independence directly
- Decision: PROCEED or PIVOT based on the pre-registered gate rule

Two rules on how those numbers are written down:

- **The violation rate never appears without its denominator**, anywhere in the document.
- **The UNVERIFIED rate is NOT comparable across the `NOT_COVERED` release.** Turns that were
  UNVERIFIED only because of an unobservable network promise are now PASS with a `NOT_COVERED`
  sub-verdict. Any write-up quoting a drop must say so — it is a reclassification, **not**
  improved detection.

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

Say it in two halves, because they are not equally reproducible:

- **The mint (Step 1) is a fresh observation and is NOT reproducible.** Re-running it drives a
  live model again and produces different traces. That is expected, and it is why a mint is
  never re-rolled to improve a number.
- **The ledger → report path (Steps 2 and 4) is fully reproducible.** Given the same fixed trace
  set and the same MCP server command, `belay phase0 run` produces the same ledger, and
  `belay phase0 report` is a pure re-render of it — no replay, no re-verification, not even a
  clock read. **Anyone given the trace set reproduces the identical number.**

### Regression via `corpus run`

After labeling, you can also verify all cases still reproduce their verdicts:

```bash
belay corpus run corpus/local
```

This re-verifies each case by replay and asserts it still reaches its recorded per-sub-verdict **set**, not merely its reduced status. If a case REGRESSES (a recorded FAIL now PASSes, or vice versa), the engine has drifted and the gate should investigate. A SKIP is kept distinct from a REGRESSION and is never a pass; an all-MATCH/SKIP run exits 0.

**One REGRESSION class is expected, and only one:** cases stored *before* the `NOT_COVERED`
release recompute their network sub-verdict from `UNVERIFIED` to `NOT_COVERED`. Confirm any diff
is confined to the `A2 / effect:network` entry. **A REGRESSION touching any other axis is a real
one.**

---

## Troubleshooting

### Empty Traces

If traces have 0 turns:
- Verify MCP servers are running and accessible
- Check BELAY_TRACE_DIR permissions
- Confirm the driver is invoking tools through the servers, not built-in tools

### The Server Never Starts (a hang, not an error)

If the client times out on `initialize` and the proxy emits nothing:
- **You are launching the server with `npx`.** Behind the gated proxy it cannot work — network
  and `~/.npm` writes are denied by design, and `npx` hangs instead of failing. Pre-install into
  `eval/servers/` and launch by absolute entrypoint path (Prerequisite 3).
- Ignore npm's *"Your cache folder contains root-owned files"* — it is a misattribution of the
  write denial, and a red herring.
- **Check for a stray `--` after `--server`.** It is `nargs=REMAINDER`, so the separator becomes
  `node`'s first argument and the server dies on startup.

### The Batch Stopped Early

If `run_mint` stops partway with a quota message:
- That is the **circuit breaker working**, not a crash. The stopping instance is recorded
  `no_observation`; the ones after it are left absent from the checkpoint and stay eligible.
- Re-run the **same `--root`** after the cap resets. Do not start a fresh root and do not look
  for a `--force` — neither exists, by design.
- If the checkpoint predates the breaker, re-arm it with `eval/scripts/rearm_checkpoint.py`
  (`--dry-run` first). See "Resuming, and the quota circuit breaker".

### Manifest Not Found

If many turns are UNVERIFIED with "manifest not found":
- Verify BELAY_SNAPSHOT_DIR is set and writable
- Confirm snapshots are being created before each turn
- Check that snapshots.manifests/ is a sibling of BELAY_SNAPSHOT_DIR

### Instrument Suspect

If the run prints "instrument suspect" (all empty traces or all snapshot failures):
- The setup is broken — tool calls are not reaching the proxy, or snapshots are not being taken
- **Suspect the bridge first.** If the trace directory you pointed at is not the `<root>/batch`
  layout of `trace-<instance-id>.jsonl` + `trace-<instance-id>.manifests/`, `belay phase0 run`
  resolves nothing and reports a *fake* PIVOT caused by operator setup rather than by the agents
  being measured
- Do not attempt to adjudicate; debug the Capture step first
- Gate should PIVOT — and it must be reported as UNVERIFIED-of-the-experiment, never as a clean 0%

