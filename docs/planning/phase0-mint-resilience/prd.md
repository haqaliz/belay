# PRD — `phase0-mint-resilience`

**Unit:** `feat/phase0-mint-resilience/aliz` · **Owner:** aliz · **Date:** 2026-07-28
**Branch:** `feat/phase0-mint-resilience/aliz` (off `91913a0`, v0.7.0)
**Inputs:** `docs/planning/_card/issue.md` (brief),
`docs/planning/phase0-mint-resilience/understanding.md` (dig)

---

## Problem Statement

The Phase-0 live mint is stalled at a denominator of **16**, against a pre-registered
requirement of **≥50**. It stalled for a reason that is fixable, and it stalled in a way
that made the damage far worse than it needed to be.

On 2026-07-24 at `16:35:31`, Stage 3 hit a Gemini **daily** request cap
(`GenerateRequestsPerDayPerProjectPerModel, limit: 250, model: gemini-3.1-pro`,
`retryDelay: 39043s` ≈ 10h50m). The minting driver has no notion of a quota-class error, so
it did the worst available thing: it **fed the remaining 56 instances into the wall in 3m48s**,
one wasted request each, recording every one as `failed`. Because `checkpoint.is_done` counts
`failed` as *done* (`checkpoint.py:82-88`), all 56 are now permanently skipped on resume. A
provider condition that should have paused the run instead destroyed the queue.

Three further facts make this more than a retry bug:

1. **Nothing records what a mint costs.** `response.usage` is present on both SDK responses
   and silently discarded; `batch.py:201` throws away `run_session`'s return value entirely.
   `phase0-live-mint/prd.md:285-293` (Gap 3) required per-instance cost and wall-clock as a
   Stage-2 output. It was never built, and no stop-loss was ever agreed.
2. **The provider is being changed.** The owner is switching off metered API keys to a
   Claude subscription (decided 2026-07-28). The driver has no client that can use it.
3. **Work that needs no quota at all is sitting undone** — 7 captured instances have never
   been verified, the gate criteria were never pre-registered into the document that will
   publish them, and the RUNBOOK still tells a reader to run the mint **in parallel**.

**Who has this problem:** the founder, blocked at the Phase-0 gate. Downstream, anyone who
would evaluate Belay on a published, reproducible number.

**Cost of the status quo:** the gate cannot be reached; each resumption attempt risks
burning the remaining queue again; and the eventual write-up cannot state what the number
cost to produce.

### What this PRD explicitly does **not** claim to fix

**The binding constraint on the gate is the audit, not the quota.** All 6 corpus cases are
`human_label: "pending"` — **0 hand-audited TPs** against a requirement of **≥3 independent** —
and all 6 share one root cause (`A1/invariant FAIL` on the default `tests/` read-only
invariant, with A2 PASS). Under the pre-registered independence rule they collapse toward
**1–2 findings, not 3**. `phase0-gate-readiness/prd.md:209` already names benign-flag skew
*"the likeliest failure"*.

Minting 34 more instances under the same blunt invariant does not fix that. This unit
therefore **sequences the audit ahead of the mint** (below) rather than pretending more
instances are the answer.

---

## Goals & Success Metrics

| Metric | Target | Source |
|---|---|---|
| Instances lost to a single quota event | **0** — the batch stops, remaining instances stay unrecorded | this unit |
| Instances re-spent by a resume | **0** — `captured` is never re-driven | `eval/README.md:303-311` |
| Per-instance accounting recorded | **100%** of driven instances (wall-clock, requests, tokens where available) | `phase0-live-mint/prd.md:285-293` |
| Mint path usable without a metered API key | **yes** | owner decision, 2026-07-28 |
| s3 instances verified | **12/12** (7 currently unverified) | `runs/s3-partial.json` covers 5 |
| Gate criteria pre-registered in `PHASE0_RESULTS.md` | **committed, `git log`-verifiable** | `phase0-live-mint/prd.md:137-139` |
| RUNBOOK defects fixed | **6/6**, incl. the parallelism claim | `audit-and-publish/spec.md:33-42` |
| Gate statements reconciled | **3 → 1 canonical**, others point at it | `phase0-mint-execution/prd.md:176-179` |
| Suite | green, `manual` still excluded from CI | `pyproject.toml:83` |

**Explicit non-goal:** a higher violation rate. Nothing here may make a flag more likely.

---

## Users & Scenario

Belay's ICP is the engineer running agents unattended who must answer *"did this run
actually do the right thing?"*. This unit ships them no surface. It produces the evidence
that the surface is worth building, and — via the subscription client — makes the mint
runnable by someone who does not hold a metered API key, which is the same BYOK/local-model
posture the product claims (`CLAUDE.md` guardrail: *"BYOK / local-model friendly … never a
vendor key, nothing proxied"*).

---

## Requirements

### Must-have

**A · Quota-class circuit breaker**

1. **Classify errors** raised from the model call into at least: `quota` (a daily/period cap
   — retry is hours away), `transient` (rate-limit or transport blip — retry is seconds
   away), and `terminal` (everything else). Classification must be duck-typed
   (`getattr(exc, "status_code", None)`, message shape), **not** by importing an SDK at
   module scope — that would break the import-isolation contract pinned by
   `tests/test_minting_driver_clients_import.py`.
2. **On a `quota` error, stop the batch.** Remaining instances are left **unrecorded** in
   the checkpoint, so they stay eligible. The stop is reported with the instance it happened
   on and the provider's own retry hint where available.
3. **The instance that hit the quota is recorded as a distinguishable disposition**, not as
   an ordinary `failed` — it produced no observation, and a resume must be able to tell that
   apart from a genuine failure.
4. **Bounded retry-with-backoff for `transient` only**, with an injected `sleep` seam.
   Backoff is asserted on the **sequence of requested delays**, never on elapsed wall time.
5. **A `terminal` error keeps today's behavior exactly**: record `failed`, continue the
   batch. The existing containment test (`test_batch_error_containment_is_not_weakened`)
   must still pass unmodified.
6. **Retry a transient `git clone --bare` failure** in `prepare_workspace`
   (`STAGE2_FINDINGS.md:44-52`: the one Stage-2 attrition case, and *"the same clone
   succeeded on retry"*).

**B · Narrow re-arm on resume**

7. A resume may re-drive an instance **only** if it produced **no observation at all**
   (quota-stopped, or a transient failure that exhausted its retries). It may **never**
   re-drive a `captured` instance.
8. **The prior failure record is preserved, not overwritten.** `eval/README.md:303-311`
   bans `--force` precisely because it *"lose[s] the record of what already ran"*; the
   re-arm must be strictly narrower than a force and must keep the history.
9. **This is not a re-roll.** `mint-execution/spec.md:52` puts *"retrying instances to
   improve the number"* out of scope, and `:90-92` explains why: *"silently re-rolling until
   the number looks good is precisely the dishonesty this project exists to prevent."* An
   instance that produced an observation someone dislikes is **never** re-armable. Enforced
   in code, not documented and hoped for.

**C · Run accounting**

10. Record per instance: **wall-clock duration**, **model request count**, **retry count**,
    and **token usage where the client exposes it**. Written durably beside the checkpoint.
11. **Under a subscription there is no per-token dollar cost**, so "cost" is redefined
    honestly as *requests + tokens + wall-clock*, and the write-up says so rather than
    printing a fabricated dollar figure.
12. Timing goes in the **batch layer behind an injected clock** — `entrypoint.py`'s design
    rule is *"No clock, no randomness"* (`mint-entrypoints/plan_20260723.md:503`), and the
    same seam serves requirement 4's determinism.

**D · Subscription-backed model client (Option B — "completion oracle")**

13. A new `Model` implementation driving the **locally-authenticated Claude Code CLI**
    headlessly (`claude -p --output-format json`), granted **no tools at all**, receiving the
    conversation plus the MCP tool schemas and returning exactly one `ToolCall | Done`.
    Verified feasible: with `ANTHROPIC_API_KEY` unset for the subprocess, `claude -p`
    authenticated and returned a result.
14. **R6 and R7 stay true by construction.** Because Claude Code is given no tools, it never
    touches the filesystem: the harness still owns the loop, every edit still crosses the MCP
    boundary, and there is still nowhere a second `tools/call` could be issued. `loop.py` and
    `batch.py` are **unchanged**. This is the entire reason Option B was chosen over letting
    Claude Code be the agent.
15. **Subprocess, parse, and schema failures are honest errors**, classified per requirement
    1 — never a silently-dropped turn and never a fabricated `Done`.
16. **The model is named in the record.** Per-instance provenance must be durable, because
    the 12 banked instances were minted on `gemini-3.1-pro-preview` and the remainder will
    not be (`STAGE2_FINDINGS.md:37-39`: *"the published number must name the model"*).

**E · Unblocked gate work (needs no quota, and de-risks the tail)**

17. **Verify the 7 unverified s3 captures.** `runs/s3-partial.json` covers only the 5 day-1
    instances; the 7 from 2026-07-24 have no ledger. Offline, free, immediate.
18. **Pre-register the gate criteria into `PHASE0_RESULTS.md`** in a commit that precedes any
    further mint, publishing the **commit hash and timestamp** so the timing claim is
    checkable rather than trusted (`phase0-gate-readiness/prd.md:130-136`). It must also state
    plainly that pre-registration is a **timing control, not an independence control** — the
    same person writes, runs, and audits.
19. **State the process debt honestly:** pre-registration did not precede Stage 3. The
    criteria were fixed in `prd.md` on 2026-07-21, before any live mint, so the timing claim
    holds — but of `prd.md`, not of the publishing document. Recorded, not quietly repaired.
20. **Fix the RUNBOOK's six defects** (`audit-and-publish/spec.md:33-42`), prioritising
    `RUNBOOK.md:94-103` — *"**Parallelism is allowed**"* plus a `for … &` loop — which
    contradicts sequential-by-design and `StdioMcp` thread-unsafety and **would corrupt a
    resumed mint if followed**. Also de-stale the `:5-18` BLOCKED banner.
21. **Reconcile the three gate statements.** The pre-registered block becomes canonical;
    `ROADMAP.md:119-121` and `PHASE0_RESULTS.md:97-107` point at it. Today
    `PHASE0_RESULTS.md` carries a non-zero-rate PROCEED clause the pre-registered block
    deliberately removed, and **omits** both the ≥50 denominator and the independence rule.

### Should-have

22. Document the `.mint_key` / `resume_mint.sh` operator convention in `eval/README.md`, or
    delete it — today it exists only as two `.gitignore` lines and is referenced by no code.
23. Stop `resume_mint.sh` `rm -rf`-ing non-captured instance dirs; it destroyed run A's
    diagnostics and is why we cannot say why that run stopped.
24. Confirm or fix the `runs/` `FileNotFoundError` (`STAGE1_REMINT_FINDINGS.md:104-105`),
    which discards a **completed** verification run when `runs/` is absent. On a resumed
    Stage-3 verify pass that is hours of replay lost.
25. Replace the known-bad CLI default `gemini-flash-latest` (`entrypoint.py:69-70`), which
    `STAGE2_FINDINGS.md:25-39` proved yields *"a 0% violation rate that means 'the agent did
    nothing'"*. Preferred: **require an explicit `--model`**, matching how `--provider` is
    already an explicit choice that is never sniffed.

### Nice-to-have

26. A `--dry-run` that reports what a resume *would* drive, without spending.
27. Surface accounting totals in `MintReport.render()`.

---

## Sequencing (deliberate, and it is a requirement)

**Audit before mint.** Hand-labeling the 6 banked corpus cases costs zero quota and is the
cheapest available predictor of whether the ≥3-independent-TP criterion is reachable at all.
Committing days of wall-clock before knowing that is the expensive ordering.

```
1. Land A–D (code, TDD)  ──┐
2. Land E (docs, verify)  ─┴─► both unblocked, no quota
3. Hand-audit the 6 banked cases        ◀── GATE: is independence reachable?
4. Only then resume the live mint (follow-on unit)
```

Step 3 is the founder's judgement call, not code. If it lands at 1–2 independent findings
with no plausible path to a third, that is a **signal about the invariant**, and
`invariant-test-mutation-shape` gets reconsidered — **before** spending, not after.

**The blunt `tests/` invariant is NOT changed by this unit.** Changing it mid-mint would make
the 12 banked instances incomparable with the rest (`STAGE2_FINDINGS.md:94-104`).

---

## Technical Considerations

**Capability:** none. This is Phase-0 gate infrastructure (`CAPABILITY_ROADMAP.md:371-376`),
consuming C1–C6 and adding no engine capability.

**Placement:** all code under `eval/`. **`src/belay/` is not modified.** Note this is a
per-unit re-imposition, not a project invariant — `phase0-mint-execution/prd.md:93-111`
lifted it once, explicitly. Everything in scope here lives in `eval/`, so it costs nothing.

**Verdict impact: NONE.** No axis changes. The LLM only *acts*; A1 (invariants) and A2
(replay) decide, unchanged. A3 untouched. No new `UNVERIFIED` path is created in the engine —
the driver's failures are *capture* failures, which manifest as an instance never entering
the denominator, never as a turn that reads as verified.

**Guardrail #1 — why retry here is not agent-framework drift.** Every *"no retry"* statement
in the codebase is scoped to the **agent loop**: `loop.py:11-12`, `eval/README.md:22-29`,
`clients/__init__.py:5-6` (*"no **agentic** retry loop"*), and the four PRD *"Agent
sophistication — no planning, memory, retry-with-reflection"* lines. Two documents
**pre-authorize** exactly this work: `batch-harness/spec.md:52-53` — *"Retrying a **failed
instance** is fine; making the **agent** smarter is not"* — and `batch.py:20-21` — *"a later,
explicit choice"*. **This unit is that explicit choice.** Structurally, `run_task` stays
retry-free so `loop.py:11-12` remains literally true; resilience lives in the model-call
layer.

**Seams (from the call-path map):**
- `Model` is a bare `typing.Protocol` with one method (`model.py:46-54`);
  `ModelFactory = Callable[[list[dict]], Model]` (`batch.py:75`) is called once per instance.
  Wrapping the factory's product is the narrowest seam that stays in `eval/`, **structurally
  cannot** retry a `tools/call` (that is a different object at `loop.py:117`), and is
  trivially fakeable.
- Containment is one bare `except Exception` at `batch.py:219-225` recording only `str(exc)`.
  The ledger schema is exactly `{status, reason, trace_path}` and `_validate_entry`
  (`checkpoint.py:166-170`) **drops unknown keys on load** — both `record` and `_validate_entry`
  must change together for accounting/disposition fields.
- **No clock or sleep seam exists anywhere in `eval/`**; no `time.sleep` at all. Introduce
  `sleep: Callable[[float], None] = time.sleep` as a kwarg, mirroring how
  `TimeoutRecordingTransport` asserts the *value* of `request_timeout`.
- **Retry hazard to pin:** `propose_next` calls `_ingest_new_messages` — which mutates
  `self._seen` and the message list — *before* the API call. A retry is safe only because
  that mutation strictly precedes the throwing call. Assert a retried `propose_next` sends a
  request **identical** to the first; `FakeOpenAIClient.calls` already snapshots requests.
- **`ScriptedModel` (`fakes.py:22`) cannot raise a provider error.** A fault-injecting fake
  and a recording `sleep` double are new scaffolding.

**Sequential execution is preserved.** A blocking `sleep` on the single thread is safe; a
threaded or async retry is not (`StdioMcp` is not thread-safe, `transport.py:212-213`, and
one-call-in-flight is R7-by-construction).

**Testing posture.** Everything above is deterministic and offline with fakes. The live
subscription path is `manual`-marked and never in CI (`pyproject.toml:83`), matching
`tests/test_minting_driver_smoke.py:111-117`'s triple guard.

---

## Risks & Open Questions

| Risk | Assessment |
|---|---|
| **Benign-flag skew → PIVOT on an untested premise** | **The top risk, and this unit cannot fix it.** 0 audited TPs today; 6 cases, ~1–2 independent. Mitigation is the *sequencing*: audit before spending. `phase0-gate-readiness/prd.md:209`. |
| **ToS — subscription for unattended batch automation** | **Open, and accepted-and-noted by the owner (2026-07-28).** Agent SDK docs bar third parties *offering* claude.ai login for their products; the docs are silent on running one's own eval on one's own subscription. Recorded as a stated assumption, not a settled fact. |
| **Population split across models** | 12 instances on `gemini-3.1-pro-preview`, the rest on Claude. Per-instance model provenance is must-have 16, and the write-up must present it. See open question 1. |
| **Prompted tool-calls are more brittle than native tool-use** | Option B asks for a structured tool call in the prompt rather than using native tool-use. Mitigated by strict parsing + honest classification (must-have 15) and pinned by tests; a parse failure is an error, never a fabricated `Done`. |
| **Subscription rate limits are undocumented** | Their error shape is unknown, so the `quota` classifier may not recognise them on first contact. Mitigation: classification is duck-typed and data-driven; the first live run is a single instance, and an unrecognised error falls back to `terminal` (records `failed`, does not burn the queue silently) — **conservative in the safe direction**. |
| **R10 — solo bandwidth** | Scope grew from "add retry" to five workstreams. Aspect decomposition keeps each independently shippable; E is pure docs/verification and can land first. |
| **R1 — the premise is wrong** | Unchanged. PIVOT remains a legitimate documented outcome. |

**Open questions**

1. **Re-mint all 68 on one model?** A subscription has no marginal per-token cost, so
   re-minting the 12 banked instances on Claude would give **one clean population** instead of
   a split. Cost is wall-clock (~68 instances × ~10 min ≈ 11h) and subscription rate limits.
   *Recommendation: decide after the audit gate* — if the audit suggests a PIVOT, do not spend
   11 hours first.
2. **`finding_kind` is specified but unbuilt** (`phase0-gate-readiness/prd.md:109-124`;
   `grep` on `src/belay/corpus/` is empty), so `STAGE2_FINDINGS.md:89-92`'s requirement to
   report the corrupt-success subset **separately** is mechanically unsatisfiable. It touches
   `src/belay/`, so it is out of scope here. Separate unit, or done by hand in the write-up?
3. **What is the subscription's actual instance/day ceiling?** Unknown until measured. The
   accounting from requirement C is what will answer it.

---

## Out of Scope

- **Running the live mint.** Follow-on, gated on the audit.
- **The hand-audit itself** — human judgement, not code.
- **Any change to `src/belay/`**, including `finding_kind` and the `--manifest-dir` shortcut.
- **`invariant-test-mutation-shape`** — deferred by `STAGE2_FINDINGS.md:94-104`; changing the
  invariant mid-mint breaks comparability with the 12 banked instances.
- **Letting Claude Code be the agent (Option A)** — rejected: it forfeits R6 and R7 as
  structural properties.
- **Agent sophistication** — no planning, memory, reflection, or multi-step autonomy.
- **Parallel/concurrent minting** — sequential by design.
- **Docker / non-macOS** — the mint is macOS + Seatbelt.
- **A3 / claim re-derivation.**

---

## Self-Critique (Phase 4)

| Dimension | Score |
|---|---|
| Problem Definition | 🟢 grounded in parsed checkpoint data, not recollection |
| User Understanding | 🟡 immediate user is the founder at a gate; ICP benefits indirectly |
| Success Metrics | 🟢 every metric has a source and a denominator |
| Scope Clarity | 🟡 see gap #1 — five workstreams in one unit |
| Edge Cases & Risks | 🟢 quota/transient/terminal split named; unknown errors fail conservative |
| Feasibility Signal | 🟡 see gap #2 — subscription limits unmeasured |
| Verdict Honesty & Replay | 🟢 no axis change; R6/R7 preserved *by construction*, and that is why Option B won |

### 🟡 Gap 1 — this is really five units wearing one coat

A (breaker), B (re-arm), C (accounting), D (subscription client), E (docs/verify) share a
goal but almost no code. D in particular is a new provider integration, not resilience work.
**Mitigation:** aspect decomposition, each independently shippable and independently
revertable. **E should land first** — it is pure docs + offline verification, needs no
quota, and `audit-and-publish/spec.md:87-88` explicitly says the doc corrections *"are not
blocked by the mint and can land early — doing so de-risks the tail."*

### 🟡 Gap 2 — we are trading a measured limit for an unmeasured one

The Gemini cap was at least *known*: 250 requests/day, an explicit `retryDelay`, a
machine-readable `RESOURCE_EXHAUSTED` status. Subscription limits are undocumented, and their
error shape is unknown — so the circuit breaker is being built against a failure mode we
have never observed. It could fire late, or not at all.

**Fix:** the first live run after this lands is **one instance**, not a batch — the same
"verify with ONE instance before scaling" rule that Stage 1 followed. And an unrecognised
error must classify as `terminal`, which records `failed` and continues, rather than as
`transient`, which would retry into a wall. Conservative in the safe direction.

### 🔴 The question I would want answered before greenlighting

**If the audit of the 6 banked cases returns 1 independent finding, does this unit still make
sense?** Partly — the accounting, the breaker, and the doc corrections are worth having
regardless. But the subscription client (D) exists to fund a mint that would then be the
wrong thing to run. The sequencing puts the audit *after* the code lands, which is the wrong
way round for D specifically.

**Honest resolution:** D is the most deferrable aspect and should be sequenced **last**, so
that if the audit gate says "the invariant is the problem, not the sample size", D can be
dropped before it is built rather than after.

---

## Honesty Properties (non-negotiable)

1. An instance that produced **no observation** is never conflated with one that failed.
2. A resume **never** re-drives an instance that produced an observation — no re-rolling.
3. The prior failure record is **preserved**, never overwritten.
4. Accounting reports **requests + tokens + wall-clock**, never a fabricated dollar figure.
5. Per-instance **model provenance** is durable; the published number names the model(s).
6. The pre-registration **commit hash and timestamp** are published, and it is described as a
   **timing control, not an independence control**.
7. The fact that pre-registration did **not** precede Stage 3 is stated, not repaired away.
8. An unrecognised provider error is `terminal`, never optimistically `transient`.
