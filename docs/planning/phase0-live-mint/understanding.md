# Understanding — `phase0-live-mint`

**Phase 2 output of `belay-begin-fast`.** Grounded in a four-agent read of the repo on
2026-07-21 (worktree `feat/phase0-live-mint/aliz`, branched from `d698e9d` / v0.3.0).
Baseline suite at branch point: **525 passed, 1 skipped, 1 deselected**.

---

## 1. What this work is really asking

Not "build a capability" — **run the experiment and publish the number.** Every engine
piece is built (C1–C6, the phase0 runner, the minting driver). What is missing is the
*connective tissue* to go from "one hand-driven instance" to "N instances, verified,
audited, and written down honestly."

The deliverable is `docs/technical/PHASE0_RESULTS.md` with **18 filled fields** and a
written `PROCEED` or `PIVOT`. That is the definition of done, not the harness code.

The harness code is a means to it, and per `minting-driver/spec.md:30-31` the batch loop
was explicitly scoped as *"a shell script / notes, not product code."* That framing is
now the main thing to pressure-test: the dig found enough sharp edges that a bare `for`
loop will silently produce a **wrong** number.

---

## 2. Affected areas

| Area | Status | Note |
|---|---|---|
| `eval/minting_driver/` | built, v0.3.0 | drives **one** session; fully parameterized on server argv / env / prompts / steps |
| `eval/instances.md` | 1 instance | `pallets__flask-4045`; prose, not machine-readable |
| `src/belay/phase0/` | built | `run_batch` + ledger + report; **must not be modified** — this work is eval-only |
| `belay phase0 run/report` | built | the CLI consumer; contract mapped below |
| `docs/planning/phase0-corpus-run/RUNBOOK.md` | **stale** | 4 concrete errors (below) |
| `docs/technical/PHASE0_RESULTS.md` | template | 18 TO-BE-FILLED fields |

**New code lands only under `eval/`.** Nothing in `src/belay/` needs to change — confirmed
by the runner-contract dig: the manifest mismatch is bridgeable by a rename in the harness.
This keeps the eval-only guardrail (`minting-driver/spec.md`) intact.

---

## 3. The feasibility question — RESOLVED, in our favor

The `/belay-next` handoff flagged instance-pool size as the thing to verify *before*
spending inference budget. Measured against the live HuggingFace datasets-server API
(`/size` + three `/rows` calls, all 200 OK, 300 rows):

| Filter (cumulative) | Pool |
|---|---|
| All SWE-bench-Lite test instances | 300 |
| Single-file patch | **300** — free; Lite is single-file by construction |
| Pure-Python repos only | **239** |
| + ≤15 changed lines | **204** |
| + problem statement ≤2000 chars | **166** |

Repo distribution (n=300): django 114, sympy 77, matplotlib 23, scikit-learn 23,
pytest 17, sphinx 16, astropy 6, requests 6, pylint 6, xarray 5, seaborn 4, flask 3.

**≥50 is reachable ~3× over at the strictest tier. No constraint needs relaxing.**

**The risk shifted from scarcity to concentration:** 138/166 (83%) of the strict pool is
django+sympy. A naive draw publishes a *django/sympy* violation rate and calls it a
general one. → **stratified draw** required (take all of flask 1 / requests 4 / pylint 3 /
pytest 7 / sphinx 13 = 28, top up with ~11 django + ~11 sympy).

Also worth stating plainly: **SWE-bench's official harness is Docker-based** and the
per-repo install specs are Debian (`apt-get`, `locale-gen`). We are *not* running
SWE-bench evaluation. The RUNBOOK's success criterion is *"≥1 tool call per instance, ≥1
restorable pre-state"* (`RUNBOOK.md:75`) — the agent needs an **editable checkout at
`base_commit`**, not a green test suite. The pure-Python constraint therefore only has to
hold for `pip install -e .` and whatever shell turns touch; keeping it strict costs
nothing at n=50 and keeps build errors from inflating UNVERIFIED.

---

## 4. The five landmines the dig found

These are the reason a bare shell loop is not sufficient.

### 4.1 Manifest resolution mismatch — **fails toward a fake PIVOT**
- `belay phase0 run` resolves manifests as `<trace-stem>.manifests` beside the trace
  (`phase0/runner.py:74-83`), and exposes **no `--manifest-dir` flag**.
- The gated proxy writes them to `<BELAY_SNAPSHOT_DIR>.manifests` (`sandbox/gate.py:330`),
  and names traces `trace-<UTC-stamp>-<8hex>.jsonl` (`trace.py:144-149`) — the stem is
  generated at proxy start and has no relation to the snapshot dir name.
- These coincide only by construction. Both the darwin e2e (`tests/test_phase0_e2e.py:167`)
  and the manual smoke (`tests/test_minting_driver_smoke.py:229-241`) bypass the CLI with an
  explicit `manifest_dir_for=`. **The RUNBOOK Step-2 CLI path has never been exercised
  against a real capture.**
- Unaddressed: every turn → "manifest not found" → UNVERIFIED → `INSTRUMENT SUSPECT`.
  It fails in exactly the direction that **fakes a PIVOT** — the most expensive possible
  wrong answer, since PIVOT means abandoning the premise.
- **Fix (harness-side, no `src/` change):** per instance, rename the trace to
  `trace-<instance-id>.jsonl` and the manifests dir to `trace-<instance-id>.manifests/`
  in a shared batch dir. Tree paths inside manifests are absolute
  (`replay/persist.py:109`), so the snapshot trees may stay where they are.

### 4.2 Trace files carry no instance id
`RUNBOOK.md:54` claims traces are written as `trace-<instance-id>.jsonl`. **False.** The
name is timestamp+uuid. With a shared `BELAY_TRACE_DIR` you cannot tell which trace is
which instance. → one private trace dir per instance, then rename into the batch dir,
plus a sidecar `instances.json` map. (`run_batch` uses the file stem as `trace_id`,
`runner.py:108-109`, so the rename *is* the mapping.)

### 4.3 One `--server` per batch
`run_batch` takes a single `server_command` for all traces (`runner.py:95`). A mint using
both the filesystem **and** shell servers produces traces needing different replay servers,
which one invocation cannot express — replay would re-invoke the wrong server. → either
one server per mint, or segregate into two batches with two ledgers. **Open decision.**

### 4.4 The 10s timeout is unreachable
`run_task` calls `transport.request(...)` with no timeout (`loop.py:87,89,104`), so the
hardcoded `DEFAULT_TIMEOUT = 10.0` (`transport.py:53`) applies to *every* call —
including `initialize` on a cold `npx -y` fetch and every shell turn. There is no way to
raise it through `run_session`. → thread a timeout `run_session → run_task →
transport.request` (or `StdioMcp(default_timeout=)`). This is `eval/`-local.

### 4.5 No error containment, no resume, stateful clients
- `run_session` propagates every exception (`session.py:63-66`); one `ServerExited` aborts
  a naive batch. `run_batch` already contains per-trace errors into `ERRORED`
  (`runner.py:123-135`) — the *capture* layer needs the same discipline.
- No checkpointing: nothing records which instances are captured, so a crash at instance 47
  restarts from zero. `ledger.to_json/from_json` exist, so resume is buildable.
- **Model clients accumulate per-session state** (`_seen`, `_anthropic_messages`,
  `_pending_tool_use_id` — `anthropic_client.py:84-87`). A batch **must** construct a fresh
  client per instance or instance 2's history bleeds into instance 1's.
- `StdioMcp` is explicitly not thread-safe (`transport.py:213-215`) → sequential. This also
  matches R7-by-construction and the `eval/README.md:155-160` warning that a mid-mint macOS
  TCC prompt "stalls (or silently blocks) a batch run with no clear error in the trace."

---

## 5. The runner contract the harness must satisfy

```
<batch-trace-dir>/
  trace-<instance-id>.jsonl          # renamed from trace-<ts>-<hex>.jsonl
  trace-<instance-id>.manifests/     # renamed from <SNAPSHOT_DIR>.manifests/
    <handle>.json
<anywhere>/<snapshot-dir>/turn-NNNN/ # trees; absolute paths in manifests
```

Then: `belay phase0 run <batch-trace-dir> --ledger runs/phase0.json --corpus-dir
corpus/local --server -- <mcp-server-command>`

Gated capture is **mandatory** for a turn to be verifiable — all three of
`BELAY_TRACE_DIR`, `BELAY_SANDBOX_SCOPE`, `BELAY_SNAPSHOT_DIR` (`proxy.py:535-554`).
Trace-only capture ⇒ `state_handle {"status":"absent"}` ⇒ every turn UNVERIFIED.
`BELAY_SNAPSHOT_DIR` must be a **sibling** of the scope, never inside it
(`gate.py:303-315`).

**Dispositions** (`runner.py:212-217`): any FAIL → `VERIFIED_FLAGGED`; else any non-UNVERIFIED
→ `VERIFIED_CLEAN`; else `NO_VERIFIABLE_TURNS`; exceptions → `ERRORED`.
**Denominator = VERIFIED_CLEAN + VERIFIED_FLAGGED only** (`ledger.py:41,91-93`).

**`INSTRUMENT SUSPECT`** (`report.py:65-87`) triggers when the denominator is 0, or when
`no_verifiable + errored >= 1.0 * len(instances)`, and then prints **no violation rate at all**.

**FP-rate requires human labels.** Ingest writes `human_label="pending"` unconditionally
(`runner.py:203`); `pending` is excluded from precision/recall (`corpus/metrics.py:126-156`),
so **FP-rate prints `n/a` until a human labels every case** via
`belay corpus label <case-id> --label {true-positive|false-positive|unverifiable}`. The
hand-audit is not bookkeeping — it is the only thing that makes the gate's required
false-positive rate exist.

---

## 6. Doc defects to fix as part of this work

`RUNBOOK.md` is the reproduce-the-number artifact and is currently **wrong in four places**:

1. `:35` — "minting driver … **NOT YET BUILT**" — stale; it shipped in v0.3.0.
2. `:60-71` — `python -m belay.proxy <server> -- <agent-runner>` — **invalid**. There is no
   `--` separator (`eval/README.md:97-100`), and the proxy does not launch an agent-runner.
3. `:54` — claims `trace-<instance-id>.jsonl` naming — false (§4.2).
4. `:183` — `belay corpus show corpus/local/<case-id>` — wrong form; `show` takes a bare
   `case_id` plus `--corpus-dir` (`cli.py:1418-1424`).
5. `:58` — "Before running all 300" contradicts `:79`'s "≥50" — 300 is the split size, not a target.

Also: **the two gate statements differ.** `ROADMAP.md:117-121` requires a *reproducible*
rate and PIVOTs on a noise-level FP rate; `PHASE0_RESULTS.md:92-100` drops both and adds
an instrument-suspect PIVOT. One must become canonical and the other point at it.

And **`PHASE0_RESULTS.md:80` promises a batching-related UNVERIFIED tally for which the
template has no field.**

---

## 7. Guardrail check (`CLAUDE.md`)

- **Not an agent framework.** The harness iterates instances and prepares workspaces; the
  agent loop stays the thin one-call-in-flight `run_task`. If it grows planning, memory, or
  retry-with-reflection, that is drift — flag it. Batch orchestration ≠ agent orchestration.
- **Not an LLM judge.** The LLM only *acts*; verdicts come from replay + invariants. No model
  is asked to score anything. A3 is untouched.
- **Eval-only.** New code under `eval/`, never `src/belay/`, never the `belay` CLI.
- **BYOK, no egress.** Keys from env; traces and corpus stay local under gitignored paths.
- **Verdict axes:** this work changes **no** axis. It *feeds* A1+A2 with real traces.
- **UNVERIFIED never PASS:** the `INSTRUMENT SUSPECT` guard is the load-bearing honesty
  property here, and §4.1 is the way it could silently produce a *wrong* PIVOT.

---

## 8. Open questions for the PRD

1. **Is ≥50 a launch count or a denominator count?** `NO_VERIFIABLE_TURNS` and `ERRORED` are
   excluded from the denominator, so 50 launched can yield a denominator well under 50. No
   doc resolves this (`RUNBOOK.md:83` hardcodes `{1..50}`, the bare floor, with no headroom).
2. **Server topology** — filesystem-only (single batch, simplest, but no shell turns), or
   filesystem+shell segregated into two batches with two ledgers? Shell turns are where
   nondeterminism (R7) and the more interesting violations live.
3. **What does "reproducible" mean** for a live-LLM mint? `RUNBOOK.md:282` and `prd.md:141-143`
   say the mint is non-deterministic, yet ROADMAP's PROCEED requires reproducibility. The only
   coherent reading is "the ledger→report path is reproducible from fixed traces" — that
   should be *stated*, not inferred.
4. **Staged pilot?** R6's own rule is "verify with ONE instance before scaling"
   (`prd.md:155-158`), and the manual smoke has **never been run** (no evidence in repo).
   Proposed: 1 → ~10 → full. Gate each stage on a real verifiable turn.
5. **Audit bandwidth (R10).** No doc estimates how many flagged cases a ≥50 mint yields, and
   every one needs a human label for the FP-rate to exist. If the count is large, a
   documented sampling rule is needed — stated openly, not silently.
6. **Task-string generation** — the curated instance has a hand-written task string
   (`eval/instances.md:56-71`). At n=50, are strings generated from `problem_statement`
   mechanically, and does that change what the agent is even attempting?
