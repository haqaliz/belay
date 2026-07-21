# PRD — `phase0-live-mint`

**Unit:** feat/phase0-live-mint · **Owner:** aliz · **Date:** 2026-07-21
**Branch:** `feat/phase0-live-mint/aliz` (off `d698e9d`, v0.3.0)
**Inputs:** `docs/planning/_card/issue.md` (brief), `docs/planning/phase0-live-mint/understanding.md` (dig)

---

## Problem Statement

Belay's entire thesis rests on one unmeasured claim: **that real agent runs contain
detectable violations.** That is risk **R1** — the only entry on the register with impact
**Fatal** (`docs/ROADMAP.md:237`).

Every engine piece needed to measure it is built and merged: the MCP proxy + trace format
(C1), Seatbelt sandbox with snapshot/restore (C2), deterministic replay (C3), the A2 and A1
verdicts (C4/C5), the failure corpus (C6), the phase0 corpus runner, and — as of v0.3.0 —
the minting driver that drives one instance through the proxy. `belay phase0 report` will
compute the number the moment it is handed real traces.

Nobody has handed it real traces. `docs/technical/PHASE0_RESULTS.md` has **18 TO-BE-FILLED
fields** and no decision. The manual smoke that would prove one instance end-to-end has,
by all evidence in the repo, **never been run**.

**Who has this problem:** the founder, at the Phase-0 → Phase-1 gate. Downstream, every
engineer who would evaluate Belay on the strength of a published, reproducible number
rather than an argument.

**Cost of the status quo:** the project cannot honestly proceed past the gate, cannot
launch (Phase 1 depends on it), and cannot know whether its premise holds. The roadmap is
explicit that finding out the premise is wrong *in week 4* is a success, not a failure
(`ROADMAP.md:118`).

---

## Goals & Success Metrics

The deliverable is **not** a capability. It is a filled `PHASE0_RESULTS.md` and a written
`PROCEED` or `PIVOT`.

| Metric | Target | Source |
|---|---|---|
| Violation-rate **denominator** (`VERIFIED_CLEAN + VERIFIED_FLAGGED`) | **≥50** | decided; `ROADMAP.md:105` |
| Hand-audited true positives | **≥3** | `ROADMAP.md:112` (gate requirement) |
| False-positive rate | **stated, never omitted** | `ROADMAP.md:113` |
| UNVERIFIED rate | measured, **every instance traced to a named cause** | `ROADMAP.md:114` |
| `PHASE0_RESULTS.md` fields filled | **18/18** + decision line | `PHASE0_RESULTS.md:21-105` |

**Explicit non-goal:** a *high* violation rate. A credible low rate is a valid result; a
~0 rate is a PIVOT and is written down as such. This PRD must not create pressure toward a
particular number — the honesty properties below exist to prevent exactly that.

### Pre-registered gate criteria (fixed 2026-07-21, BEFORE any live mint)

Recorded here, and to be copied into `PHASE0_RESULTS.md` **before Stage 3 runs**, so the
gate cannot be decided with the result already visible.

> **PROCEED** iff **≥3 _independent_ hand-audited true positives** survive audit **AND**
> the violation-rate denominator is **≥50** **AND** `INSTRUMENT SUSPECT` did not fire.
>
> **The violation rate itself is reported, not thresholded.** With ≥3 confirmed genuine
> violations the premise is demonstrated whether the rate is 6% or 26%; inventing a
> percentage cutoff would manufacture precision that n=50 does not support.
>
> **PIVOT** if fewer than 3 independent TPs survive audit, or if `INSTRUMENT SUSPECT`
> fires, or if the FP rate is high enough that flagged runs are noise
> (`ROADMAP.md:121` — judged and *stated*, not silently dropped).
>
> **"Independent"** means distinct root causes — or at minimum distinct instances *and*
> distinct tools. Three flags from one mis-annotated tool count as **one** finding. Each
> TP's root cause is recorded beside it so a reader can judge independence directly.

### Symmetric false-positive guard

`INSTRUMENT SUSPECT` protects against a false *zero*. Nothing in the engine protects
against a false *positive rate* — a systematic bug manufacturing plausible violations,
audited by the person who wants the premise to hold. Two controls, both required:

1. **Clean control instances.** 2–3 instances where the agent is directed to make a
   trivially-correct edit that violates nothing. **If a control comes back FAIL, the
   instrument is manufacturing violations and the mint is void** — the same standing as
   INSTRUMENT SUSPECT, and reported as such rather than quietly excluded.
2. **Hand-replay one FAIL end-to-end** to confirm its observed state delta is real and not
   an artifact of the rename/manifest wiring. Documented in the results.

---

## Users & Scenario

Belay's ICP is the engineer running agents unattended who must answer *"did this run
actually do the right thing?"* and today cannot. This unit does not ship them a surface —
it produces the evidence that the surface is worth building, and the first real corpus
cases (moat #2) as a by-product.

---

## Requirements

### Must-have

1. **A machine-readable instance registry** — `instance_id → (repo, base_commit,
   problem_statement, task_string)` for the selected pool. Today `eval/instances.md` is
   prose with one entry.
2. **Stratified instance selection.** The strict-constraint pool is 166 instances but
   **83% is django+sympy**. A naive draw publishes a django/sympy rate and calls it
   general. Take all of flask/requests/pylint/pytest/sphinx (28), top up with django+sympy
   to the launch target.
3. **Per-instance workspace prep** — clone/checkout at `base_commit`, laid out so
   `BELAY_SNAPSHOT_DIR` is a **sibling** of `BELAY_SANDBOX_SCOPE`, never inside it
   (`gate.py:303-315`).
4. **Gated capture for every instance** — all three of `BELAY_TRACE_DIR`,
   `BELAY_SANDBOX_SCOPE`, `BELAY_SNAPSHOT_DIR` (`proxy.py:535-554`). Trace-only capture
   makes every turn UNVERIFIED.
5. **The rename bridge.** Per instance, rename the proxy's `trace-<ts>-<hex>.jsonl` to
   `trace-<instance-id>.jsonl` and its `<snapshot-dir>.manifests/` to
   `trace-<instance-id>.manifests/` in a shared batch dir, so the stock
   `belay phase0 run` CLI resolves manifests correctly. **This is the single highest-risk
   path in the unit** — see Risks.
6. **Sequential drive, one instance at a time**, one `tools/call` in flight
   (`StdioMcp` is not thread-safe, `transport.py:213-215`; also R7-by-construction and it
   avoids the macOS TCC-prompt stall, `eval/README.md:155-160`).
7. **A fresh model client per instance.** Clients accumulate conversation state
   (`anthropic_client.py:84-87`); reuse bleeds instance N-1's history into instance N.
8. **Per-instance error containment** — one `ServerExited` must not abort the batch;
   record a reason and continue, mirroring `run_batch`'s `ERRORED` discipline
   (`runner.py:123-135`).
9. **Resume after failure** — a checkpoint recording which instances are captured, so a
   crash at instance 47 does not restart from zero after real inference spend.
10. **A configurable request timeout**, threaded `run_session → run_task →
    transport.request`. The hardcoded `DEFAULT_TIMEOUT = 10.0` (`transport.py:53`) is
    currently unreachable and will not survive a cold `npx -y` fetch.
11. **Two segregated batches** — filesystem and shell servers each with their own trace
    dir and ledger, verified separately, combined only in the write-up.
12. **Full hand-audit** — every flagged case labeled via `belay corpus label`. Until then
    FP-rate prints `n/a` (`corpus/metrics.py:126-156`) and the gate cannot be met.
13. **`PHASE0_RESULTS.md` filled** — all 18 fields plus the PROCEED/PIVOT line.
14. **Pre-register the gate criteria** into `PHASE0_RESULTS.md` before Stage 3 runs
    (see *Pre-registered gate criteria*). Non-negotiable ordering: written down first,
    mint second.
15. **2–3 clean control instances** in the mint, and **one hand-replayed FAIL**
    (see *Symmetric false-positive guard*). A FAILing control voids the mint.
16. **Record each TP's root cause** beside it, so the ≥3 independence requirement is
    auditable by a reader rather than asserted.

### Should-have

17. **Staged rollout: 1 → ~10 → full.** R6's own rule is "verify with ONE instance before
    scaling" (`prd.md:155-158`). Stage 1 is running the existing manual smoke, which has
    never been run. Each stage gates on ≥1 genuinely verifiable turn.
18. **RUNBOOK corrections** — it is the reproduce-the-number artifact and is wrong in five
    places (stale "NOT YET BUILT", invalid `--` proxy argv, false trace-naming claim, wrong
    `corpus show` form, "all 300" vs "≥50").
19. **Reconcile the two gate statements** — `ROADMAP.md:117-121` vs
    `PHASE0_RESULTS.md:92-100` differ on "reproducible" and on the FP-noise PIVOT. One
    becomes canonical; the other points at it.

### Nice-to-have

20. A slot in `PHASE0_RESULTS.md` for the batching-related UNVERIFIED tally its own
    line `:80` promises but has no field for.
21. A one-instance-by-id entry script (`phase0-minting-driver/prd.md:97`, never built).

---

## Technical Considerations

**Capability:** none — this is the **Phase-0 gate itself** (`CAPABILITY_ROADMAP.md:309-313`,
"C1–C5 = the Phase 0 gate"). It consumes C1–C6; it adds no engine capability.

**Placement:** all new code under `eval/`. **`src/belay/` is not modified.** The dig
confirmed the manifest mismatch is bridgeable by a harness-side rename, so the eval-only
guardrail (`minting-driver/spec.md`) holds without exception.

**Verdict impact: none.** No axis changes. The LLM only *acts*; A1 (invariants) and A2
(replay) decide, unchanged. A3 is untouched. This unit *feeds* the axes real traces — it
does not alter what a verdict claims.

**Runner input contract** the harness must produce:

```
<batch-trace-dir>/
  trace-<instance-id>.jsonl
  trace-<instance-id>.manifests/<handle>.json
```
then `belay phase0 run <batch-trace-dir> --ledger <l> --corpus-dir corpus/local --server -- <cmd>`

**"Reproducible" — decided.** The ROADMAP's PROCEED condition requires a *reproducible*
rate; `RUNBOOK.md:282` and `prd.md:141-143` say a live-LLM mint is non-deterministic. These
reconcile in exactly one way, and the PRD states it rather than leaving it inferred:

> The **mint** is a fresh observation each time and is not reproducible. The
> **ledger → report path is fully reproducible** from fixed traces: anyone given the trace
> set reproduces the identical number. That is what "reproducible" means at this gate, and
> `PHASE0_RESULTS.md` must say so in those words.

**Task strings** are generated mechanically from each instance's `problem_statement`
(truncated), not hand-written. The curated flask instance's hand-written string
(`eval/instances.md:56-71`) does not scale to 50. This is stated as a coverage caveat: the
agent attempts what the problem statement says, not a human-optimized version of it.

---

## Risks & Open Questions

| Risk | Assessment |
|---|---|
| **R1 — the premise is wrong** (Low/**Fatal**) | This unit exists to test it. PIVOT is a legitimate, documented outcome. |
| **Manifest-rename defect → fake PIVOT** | **The top risk of this unit.** Mis-wiring makes every turn UNVERIFIED → `INSTRUMENT SUSPECT`, indistinguishable from a real premise failure. Mitigation: a deterministic test on the rename/resolution path, plus the stage-1 single-instance verification before any spend. |
| **R6 — failures don't cross MCP** (High/High) | Mitigated by construction: all edits go through MCP servers. The `INSTRUMENT SUSPECT` guard is the false-zero defense and must never be reported as a clean 0%. |
| **R7 — UNVERIFIED dominates** (Med/High) | Measured, not hidden. Every UNVERIFIED traces to a named cause. If it dominates, that is a **gate signal**, reported as such. |
| **R10 — solo bandwidth** (High/Med) | ≥50 live instances + full audit is the spike. Staged rollout caps wasted spend; resume prevents re-running after a crash. |
| **Concentration bias** | 83% of the eligible pool is django+sympy. Stratified draw required, and the composition is published beside the number. |
| **Inference cost** | Real, unbudgeted. Staged rollout is the control. |

**Open questions**
1. How many flagged cases will 50 instances yield? Unknown — no doc estimates it. If the
   count makes a full audit infeasible (R10), the sampling rule is revisited **explicitly
   and stated in the results**, never silently.
2. Are `npx`-fetched MCP servers stable enough across ~50 sequential sessions, or does the
   harness need a pre-warmed server install? Stage 2 answers this.
3. Does macOS TCC prompt mid-batch despite the sibling-dir layout? Stage 2 answers this.

---

## Out of Scope

- **Any change to `src/belay/`** — including adding a `--manifest-dir` flag to
  `phase0 run`. The rename bridge lives in the harness.
- **C7 live console** and every Phase-1 surface.
- **Running SWE-bench evaluation.** We do not check whether the agent *solved* the
  instance; the criterion is "≥1 tool call, ≥1 restorable pre-state"
  (`RUNBOOK.md:75`). No test-suite execution, no resolution scoring.
- **Parallel/concurrent minting** — sequential by design.
- **Docker.** The mint is macOS + Seatbelt; the pure-Python instance pool makes Docker
  unnecessary.
- **Agent sophistication** — no planning, memory, retry-with-reflection, or multi-step
  autonomy in the driver. That is agent-framework drift (guardrail #1).
- **A3 / claim re-derivation** (C8) — untouched.

---

## Self-Critique (Phase 4)

Scored against the `prd-generator` dimensions. Recorded here so the gaps travel with the
document rather than living only in a chat message.

| Dimension | Score |
|---|---|
| Problem Definition | 🟢 R1 is named, Fatal-rated, and file-cited |
| User Understanding | 🟡 the immediate user is the founder at a gate; the ICP benefits only indirectly |
| Success Metrics | 🔴 see gap #1 — the PIVOT threshold is not a number |
| Scope Clarity | 🟢 out-of-scope is explicit, including the tempting `--manifest-dir` shortcut |
| Edge Cases & Risks | 🟡 see gap #2 — TP independence is unaddressed |
| Stakeholder Alignment | 🟢 solo; no ambiguity |
| Feasibility Signal | 🟡 see gap #3 — no cost or wall-clock budget |
| Verdict Honesty & Replay | 🟢 no axis change, UNVERIFIED paths named, INSTRUMENT SUSPECT load-bearing, no judge, no framework drift |

### 🔴 Gap 1 — "violation rate ~0" is not a number, and it must be fixed *before* the run

The gate PIVOTs "if the violation rate is ~0" (`ROADMAP.md:118`). `~0` is undefined. If the
mint returns **1/50 (2%)**, is that PROCEED or PIVOT? Deciding *after* seeing the result is
post-hoc rationalization — precisely the bias this project exists to eliminate. A verdict
engine that refuses to let an LLM grade itself cannot let its own founder grade the gate
after the fact.

**Fix:** pre-register the threshold in `PHASE0_RESULTS.md` **before** the full mint runs,
along with the ≥3-TP requirement. Proposed: **PROCEED requires ≥3 independent hand-audited
TPs AND a violation-rate denominator ≥50**; the rate itself is reported, not thresholded —
because with ≥3 confirmed genuine violations the premise is demonstrated regardless of
whether the rate is 6% or 26%. PIVOT if <3 independent TPs survive audit, or if
INSTRUMENT SUSPECT fires. **Needs the founder's sign-off before Stage 3.**

### 🔴 Gap 2 — three true positives from one root cause is *one* finding

The gate says "≥3 flagged violations hand-audited and confirmed as genuine"
(`ROADMAP.md:112`). It does not say *independent*. If all three flags trace to a single
mis-annotated MCP server tool, that is one detection replicated three times, and
publishing it as "3 true positives" would overstate the evidence — a credibility failure of
exactly the kind `ROADMAP.md:113` warns about for the FP rate.

**Fix:** require the ≥3 TPs to be **independent** — distinct root causes, or at minimum
distinct instances *and* distinct tools. Record the root cause beside each TP in the
results doc so a reader can judge independence themselves.

### 🟡 Gap 3 — no cost or wall-clock budget

R10 (solo bandwidth, High) is named but unquantified: no estimate of inference spend, no
per-instance wall-clock, no total audit hours. The staged rollout is the control, but
Stage 2 should *measure* per-instance cost and time and extrapolate before Stage 3
commits. An abandoned half-finished mint is a worse outcome than a deliberately smaller one.

**Fix:** make "record cost + wall-clock per instance" an explicit Stage-2 output, and set a
stop-loss the founder agrees to in advance.

### The question I'd want answered before greenlighting

**If the mint comes back at exactly the rate that best serves the project's narrative, what
would convince you the instrument is lying rather than that the premise is confirmed?**
The `INSTRUMENT SUSPECT` guard protects against a false *zero*. Nothing in this PRD
protects against a false *positive* rate — a systematic bug that manufactures plausible
violations would sail through, and the hand-audit is performed by the same person who wants
the premise to hold. Consider naming, in advance, one adversarial check on a *flagged*
result (e.g. hand-replaying one FAIL to confirm the delta is real, or verifying a
deliberately-clean control instance comes back PASS).

---

## Honesty Properties (non-negotiable)

These exist because this unit produces *the* number the project rests on.

1. `INSTRUMENT SUSPECT` is **never** rendered as a 0% violation rate.
2. `UNVERIFIED` is **never** rendered as PASS.
3. The violation rate is **always** published with its denominator.
4. The FP rate is **stated**, never omitted — even if unflattering.
5. The instance-pool composition is published beside the number.
6. A PIVOT is written down as plainly as a PROCEED.
