# PRD — `phase0-mint-execution`

**Unit:** feat/phase0-mint-execution · **Owner:** aliz · **Date:** 2026-07-23
**Branch:** `feat/phase0-mint-execution/aliz` (off `master` @ `07890e7`, v0.4.0)
**Inputs:** `docs/planning/_card/issue.md` (brief), `docs/planning/phase0-mint-execution/understanding.md` (dig)
**Supersedes in part:** `docs/planning/phase0-live-mint/prd.md` — that PRD remains authoritative
on gate criteria, stratification, and the honesty properties. This one **lifts its
`src/belay/` out-of-scope constraint** (see *Scope change*) and executes its `mint-execution`
and `audit-and-publish` aspects.

---

## Problem Statement

Belay's thesis rests on one unmeasured claim: **that real agent runs contain detectable
violations.** That is risk **R1** — the only entry on the register with impact **Fatal**
(`ROADMAP.md:237`). C1–C6 are shipped; `belay phase0 report` computes the number the moment
it is handed real traces. `docs/technical/PHASE0_RESULTS.md` still has **18 TO-BE-FILLED
fields** and no decision.

Stage 1 (2026-07-22) ran one instance end-to-end and did its job: it caught a replay-fidelity
contamination that would have published a bogus rate. That defect was fixed and released in
v0.4.0. **The brief for this unit assumed that unblocked the mint. The dig found it did
not.**

### The blocking discovery (new, verified in code)

`belay phase0 run` accepts **one static** `--server` command for a whole batch directory
(`src/belay/phase0/runner.py:90`, threaded unchanged at `:115,174,200`; parsed once at
`src/belay/cli.py:1044`). Each trace's `source_root` is read correctly *per turn* from its own
manifest (`src/belay/replay/engine.py:388`), so **arguments** relocate properly. The **argv
allow-root does not**: `remap_argv` rewrites a token only when it is under that trace's
recorded root (`src/belay/replay/relocate.py:93-108`) and returns a `changed` flag that
`src/belay/replay/client.py:371` **discards via `[0]`** — no caller in `src/` consumes it.

For every instance whose workspace ≠ the single `--server` root token: arguments move to the
scratch, the server's allowed-dir does not, the filesystem server rejects the scratch paths,
the reply diverges from a recorded success, `classify_determinism` re-runs the same broken
command and calls it DETERMINISTIC, and `src/belay/verify/result.py:18` yields
`DIVERGED + DETERMINISTIC → FAIL`.

**Consequence:** a scaled mint publishes a violation rate approaching **~100%**, composed of
**false FAILs — not UNVERIFIED**. It is invisible at n=1 and untested: every relocation e2e
case builds the server command from the same root as the capture
(`tests/test_replay_relocation_e2e.py:99`, used at :312, :339, :369, :401, :488, :592).

Capture already solved this hazard with a per-instance seam and documents it
(`eval/minting_driver/batch.py:82-95` → `servers.py:152`). **Replay has no equivalent.**

**Cost of the status quo:** the project cannot honestly pass Phase 0, cannot launch, and —
worse than not knowing — is one command away from publishing a spectacular-looking number
that is an artifact.

---

## Goals & Success Metrics

The deliverable is **not** a capability. It is a filled `PHASE0_RESULTS.md` and a written
`PROCEED` or `PIVOT`.

| Metric | Target | Source |
|---|---|---|
| Violation-rate **denominator** (`VERIFIED_CLEAN + VERIFIED_FLAGGED`) | **≥50** | `ROADMAP.md:105` |
| Hand-audited **independent** true positives | **≥3** | `phase0-live-mint/prd.md:58-71` |
| False-positive rate | **stated, never omitted** | `ROADMAP.md:113` |
| UNVERIFIED rate | measured, every instance traced to a **named cause** | `ROADMAP.md:114` |
| Clean controls returning FAIL | **0** — any FAIL **voids the mint** | `phase0-live-mint/prd.md:80-82` |
| `PHASE0_RESULTS.md` fields filled | **18/18** + decision line | `PHASE0_RESULTS.md:21-105` |

**Explicit non-goal: a *high* violation rate.** A credible low rate is a valid result; ~0 is
a PIVOT and gets written down as such. Given the §Problem finding, a *suspiciously high* rate
is now the outcome to distrust first.

### Pre-registered gate criteria (inherited verbatim, `phase0-live-mint/prd.md:58-71`)

> **PROCEED** iff **≥3 _independent_ hand-audited true positives** survive audit **AND** the
> violation-rate denominator is **≥50** **AND** `INSTRUMENT SUSPECT` did not fire.
>
> **The violation rate itself is reported, not thresholded.**
>
> **PIVOT** if fewer than 3 independent TPs survive audit, or if `INSTRUMENT SUSPECT` fires,
> or if the FP rate is high enough that flagged runs are noise.
>
> **"Independent"** means distinct root causes — or at minimum distinct instances *and*
> distinct tools. Three flags from one mis-annotated tool count as **one** finding.

These must be committed into `PHASE0_RESULTS.md` in a commit that **precedes** the Stage-3
mint commit — verifiable from `git log` (`mint-execution/spec.md:46-47`). Non-negotiable
ordering.

---

## Scope change (stated explicitly, not buried)

`phase0-live-mint/prd.md:227-229` put "*Any change to `src/belay/`*" out of scope. That
constraint was written when the harness-side bridge was believed to be the only gap. The dig
disproves its premise. **This unit owns a core-engine change**, decided at interview:

- **(b) the honesty floor, first (TDD RED):** `client.py` consumes `remap_argv`'s `changed`
  flag; when relocation is on and **no argv token moved**, return **UNVERIFIED** with a named
  cause instead of spawning a mis-rooted server.
- **(a) the seam, second:** `run_batch`/CLI take `server_command_for: Callable[[Path],
  list[str]]` instead of a static `list[str]`, mirroring `eval/minting_driver/batch.py`'s
  `build_server_command`.

(b) alone converts a false-FAIL mint into a no-number mint; (a) alone leaves the silent
failure mode in the engine for every future caller. Both, in that order.

**Verdict impact: none.** No axis changes; A3 untouched. The fix corrects the *fidelity of
A2's inputs* and adds an UNVERIFIED path — it does not change what any axis claims.

---

## Users & Scenario

Belay's ICP is the engineer running agents unattended who must answer *"did this run actually
do the right thing?"*. This unit ships them no surface — it produces the evidence the surface
is worth building, plus the first real corpus cases (moat #2) as a by-product. The immediate
user is the founder at the Phase-0 gate.

---

## Requirements

### Must-have

1. **(b) Mis-rooted replay yields UNVERIFIED, never FAIL** — `changed` flag consumed; named
   cause; test asserting a mis-rooted turn is UNVERIFIED and *not* FAIL.
2. **(a) Per-trace server-command seam** — `run_batch` + CLI resolve the server command per
   trace; a two-instance heterogeneous batch verifies correctly through **one** invocation.
3. **A committed one-instance-by-id entry point.** No CLI/`__main__`/argparse exists under
   `eval/` today; Stage 1 ran from an uncommitted `scratchpad/drive_one.py` that is gone.
   Until this exists the number is **not reproducible from the repo** — which is the
   RUNBOOK's whole purpose.
4. **A committed batch entry point** wrapping `run_mint` with the registry, checkpoint, and
   bridge wired.
5. **Pool + draw artifacts committed** — a dataset fetch producing `pool.json`, and
   `selected.json` from `select_instances(pool, target, seed)` with the **seed committed**
   beside it. Neither file, nor the fetch script, exists today.
6. **3 clean control instances** marked by the `is_control` field
   (`eval/instances/registry.py:65`), drawn into the same batch. **A FAILing control voids the
   mint** and is escalated, never dropped (`mint-execution/spec.md:52-53`).
7. **Staged rollout: 1 → ~10 → ~65–70.** Each stage gates on ≥1 genuinely verifiable turn.
8. **Stage-1 re-mint acceptance:** `pallets__flask-4045` no longer reports
   `VERIFIED_FLAGGED 1/1`, **and** the same trace+manifests yield an **identical** verdict
   against a pristine / mutated / **deleted** original workspace (the relocation guarantee,
   in the wild rather than in fixtures).
9. **Explicit `request_timeout`** — `None` silently means `DEFAULT_TIMEOUT = 10.0`
   (`transport.py:53`), too tight for a live model plus a cold `node` start under Seatbelt.
   No env override exists.
10. **Gated capture for every instance** — all three of `BELAY_TRACE_DIR`,
    `BELAY_SANDBOX_SCOPE`, `BELAY_SNAPSHOT_DIR`. Trace-only capture makes every turn
    UNVERIFIED.
11. **Sequential drive**, one `tools/call` in flight, **a fresh model client per instance**
    (clients accumulate conversation state — reuse bleeds instance N-1 into N).
12. **Full hand-audit** of every flagged case via `belay corpus label`; until then the FP rate
    prints `n/a` and the gate cannot be met.
13. **Hand-replay one FAIL end-to-end** to confirm its observed delta is real and not a
    wiring artifact (the second half of the symmetric FP guard).
14. **Pre-register the gate criteria into `PHASE0_RESULTS.md` before Stage 3**, in an earlier
    commit.
15. **`PHASE0_RESULTS.md` filled** — 18/18 + the PROCEED/PIVOT line, with the instance-pool
    composition published beside the number.

### Should-have

16. **RUNBOOK corrections — now six, not five.** The known five (stale "NOT YET BUILT";
    invalid `--` proxy argv; false trace-naming claim; wrong `corpus show` form; "all 300" vs
    "≥50") **plus a sixth the dig found**: `RUNBOOK.md:94-103` says parallelism is safe and
    shows a parallel loop, contradicting sequential-by-design
    (`phase0-live-mint/prd.md:119-121, 233`). Also: the RUNBOOK's cited line numbers are
    ~+15 stale.
17. **Walk the corrected RUNBOOK end-to-end by hand once** before publishing — it is the
    reproduce-the-number artifact; if it doesn't work, the number isn't reproducible
    (`audit-and-publish/spec.md:64-66`).
18. **Reconcile the three gate statements.** `ROADMAP.md:117-121`,
    `PHASE0_RESULTS.md:92-100` (no "reproducible" clause; adds a non-zero-rate clause), and
    the PRD's pre-registered block differ. The pre-registered block becomes canonical; the
    others point at it.
19. **De-stale the BLOCKED notices** in `STAGE1_FINDINGS.md:9-12` and `RUNBOOK.md:5-18`
    **precisely** — the single-instance block is lifted; the batch block is real until
    requirement 2 lands.
20. **State "reproducible" in the decided words:** the mint is a fresh observation and is not
    reproducible; the **ledger → report path is fully reproducible** from fixed traces.

### Nice-to-have

21. A 19th `PHASE0_RESULTS.md` slot for the batching-related UNVERIFIED tally that `:80`
    promises but has no field for.
22. Strengthen the manual smoke's oracle — it currently accepts `VERIFIED_FLAGGED`, so the
    Stage-1 false positive *satisfied* it, and it bypasses `bridge_capture` via
    `manifest_dir_for=`.

---

## Technical Considerations

**Capability:** none — this **is** the Phase-0 gate (`CAPABILITY_ROADMAP.md:323-328`). It
consumes C1–C6.

**Placement:** `src/belay/{replay,phase0,cli}` for requirements 1–2 (the scope change); all
else under `eval/` and `docs/`.

**Decided at interview:**
- **Model:** `gemini-flash-latest` via the OpenAI-compat endpoint (`/v1beta/openai/`,
  `Authorization: Bearer`). Proven in Stage 1 to do real work. **`ANTHROPIC_API_KEY` must be
  unset** — the driver prefers Anthropic when it is present. `gemini-2.5-flash` /
  `gemini-2.0-flash` return 404 on this key.
- **Servers: filesystem-only.** The shell server embeds paths inside `command_line`, which
  relocation deliberately does not rewrite (`replay-relocation/spec.md:30-35`), so shell
  replays are known-contaminated. The filesystem batch carries the ≥50 denominator alone. The
  exclusion is **disclosed in the results as a coverage limit**, and `replay-relocation-shell`
  stays a follow-up. This narrows `phase0-live-mint` must-have 11 (two segregated batches) —
  stated, not silently dropped.
- **Draw:** ~65–70 launched to land ≥50 after attrition, incl. 3 controls; seed committed.
  Composition: all 28 small-repo instances (flask 1 / requests 4 / pylint 3 / pytest 7 /
  sphinx 13), topped up balanced from django+sympy.

**Prerequisites not in the repo:** `eval/servers/` must be installed
(`npm install --prefix eval/servers <pkg>@<ver>`, per `servers.py:113`); it is gitignored and
absent from both checkouts. Pinned versions (`server-filesystem@2026.7.10`,
`mcp-server-commands@0.8.2`) are hardcoded and only path-checked, so drift goes unnoticed.

**Runner input contract** (`bridge_capture` must satisfy; `runner.py:74-82`):
```
<batch-dir>/trace-<instance-id>.jsonl
<batch-dir>/trace-<instance-id>.manifests/<handle>.json
```
`belay phase0 run <batch-dir> --server node <entry> <workspace>` — **no `--` separator**;
`--server` is `nargs=REMAINDER`.

---

## Risks & Open Questions

| Risk | Assessment |
|---|---|
| **R1 — the premise is wrong** (Low/**Fatal**) | This unit exists to test it. PIVOT is legitimate and documented. |
| **A high rate is an artifact, not a finding** | **The top risk, and newly concrete.** Mitigations: requirement 1 (UNVERIFIED not FAIL), requirement 2 (the seam), 3 controls in-batch, and one hand-replayed FAIL. |
| **R6 — failures don't cross MCP** (High/High) | Mitigated by construction (all edits cross MCP). `INSTRUMENT SUSPECT` is the false-zero defense and is never reported as a clean 0%. |
| **R7 — UNVERIFIED dominates** (Med/High) | Requirement 1 *increases* UNVERIFIED by design. If it dominates, that is a gate signal, reported as such. |
| **R10 — solo bandwidth** (High/Med) | ~65–70 live instances + full audit is the spike. Staged rollout + resume cap the waste. |
| **Concentration bias** | 83% django+sympy; stratified draw required and the composition published beside the number. |
| **Inference cost** | Real, unbudgeted. Gemini flash + staged rollout are the controls; Stage 2 measures it. |
| **Opportunity cost** | Every week here is a week C7 (the launch surface) doesn't exist. |

**Open questions**
1. How many flagged cases will ~50 instances yield? Unknown. If the count makes a full audit
   infeasible, the sampling rule is revisited **explicitly and stated**, never silently.
2. Does macOS TCC prompt mid-batch despite the sibling-dir layout? Stage 2 answers.
3. Are the pinned server versions still installable? Re-check with `npm view` before minting.

---

## Out of Scope

- **`replay-relocation-shell`** (command-string-aware relocation) and the shell batch.
- **C7 live console** and every Phase-1 surface.
- **Running SWE-bench evaluation** — we do not check whether the agent *solved* the instance.
  Criterion is "≥1 tool call, ≥1 restorable pre-state".
- **Parallel/concurrent minting** — sequential by design.
- **Docker** — macOS + Seatbelt.
- **Agent sophistication** — no planning, memory, retry-with-reflection, or multi-step
  autonomy. That is agent-framework drift (guardrail #1).
- **A3 / claim re-derivation** (C8).

---

## Honesty properties (non-negotiable, inherited `phase0-live-mint/prd.md:308-318`)

1. `INSTRUMENT SUSPECT` is **never** rendered as a 0% violation rate.
2. `UNVERIFIED` is **never** rendered as PASS.
3. The violation rate is **always** published with its denominator.
4. The FP rate is **stated**, never omitted — even if unflattering.
5. The instance-pool composition is published beside the number.
6. A PIVOT is written down as plainly as a PROCEED.

Add, for this unit: **7. The shell-server exclusion is disclosed as a coverage limit**, and
**8. a suspiciously high rate is investigated against the controls before it is published.**

---

## Self-Critique (Phase 4)

| Dimension | Score |
|---|---|
| Problem Definition | 🟢 R1 named, Fatal-rated, and the new blocker verified in code with citations |
| User Understanding | 🟡 immediate user is the founder at a gate; the ICP benefits only indirectly |
| Success Metrics | 🟢 inherited pre-registered criteria; denominator, FP rate, and controls all thresholded or explicitly un-thresholded |
| Scope Clarity | 🟡 see gap #1 — the unit now spans core engine + eval + docs |
| Edge Cases & Risks | 🟢 the artifact-not-finding risk is named as the top risk with four mitigations |
| Stakeholder Alignment | 🟢 solo; four decisions taken at interview |
| Feasibility Signal | 🔴 see gap #2 — no cost or wall-clock budget |
| Verdict Honesty & Replay | 🟢 no axis change; UNVERIFIED path added, not removed; no judge; no framework drift |

### 🟡 Gap 1 — this unit is now three units wearing a trenchcoat

Core-engine fix + eval tooling (entry points, pool, draw) + a live measurement + a docs
cleanup. Each is independently shippable. **Mitigation:** the aspect decomposition below
splits them, and the engine fix lands and merges *before* any spend. If bandwidth bites, the
honest cut is to ship the engine fix + entry points, and defer Stage 3 — **never** to run
Stage 3 without them.

### 🔴 Gap 2 — no cost or wall-clock budget

~65–70 live instances at unknown per-instance token cost and unknown wall-clock under
sequential Seatbelt execution. Stage 2 (~10) is the designed measurement, but this PRD sets
**no abort threshold**. Proposed and needing sign-off: if Stage 2's extrapolated Stage-3 cost
exceeds a stated ceiling, the target is re-cut *before* Stage 3 and the smaller denominator is
published with its consequence for the gate stated.

### 🟡 Gap 3 — the auditor wants the premise to hold

The person auditing the flags is the person who needs ≥3 TPs. Structural counterweights: the
3 in-batch controls, the hand-replayed FAIL, recording each TP's root cause so a reader can
judge independence directly, and the new honesty property 8.
