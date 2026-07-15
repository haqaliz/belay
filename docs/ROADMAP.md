# Belay: Product Roadmap

> **Belay** is the agent harness. It sandboxes what an agent does, verifies each step by **replaying it against real state**, records a deterministic trace, and can replay any past run. Around *any* agent, on the user's own infra.

---

## Why this roadmap looks the way it does

**The wedge.** Building the agent (LangGraph, CrewAI, AutoGPT) is crowded and commoditizing, so we avoid it. Recording what the agent did (Langfuse, Phoenix, LangSmith, Braintrust) is a live, healthy category — we sit *beside* it, not against it. The unsolved question neither answers is **"was this step actually correct?"**, answered by re-executing the tool call in a sandbox and diffing observed-vs-claimed state. That is the company.

**The evidence we're building on:**
- The failure is measured, not hypothetical. **27–78% of benchmark-reported agent "successes" are "corrupt successes"** — right end-state via a broken, unsafe, or cheating path (arXiv 2603.03116). Outcome-only scoring is structurally blind to it.
- The usual fix is itself unreliable. LLM-as-judge shows up to **35% false positives** (arXiv 2507.08794), and pairwise verdicts flip **10–30%** on trivial order swaps. The only trustworthy signal is **re-execution against real state**.
- The market is the hottest in open source. LLM projects **+178% YoY** on GitHub (Octoverse 2025); agents that *act* are the fastest sub-category, and every one needs a harness.
- The direction is explicitly requested: Conviction / Sarah Guo RFS 2026 ("the harness"), YC RFS Summer 2026 #13 ("Software for Agents"), Karpathy at Sequoia Ascent 2026 ("sensors and actuators").

---

## Guiding Principles

1. **Ground the verdict in execution, never in an opinion.** Anyone can bolt an LLM judge onto a trace. We win by *re-running the step and diffing real state*. Every phase must harden the sandbox / replay / verify engine.
2. **Narrow, then expand.** ONE ingest surface (MCP), run flawlessly, beats five adapters that mostly work. Depth is the moat; breadth is a later optimization.
3. **Prove the premise before building the product.** If the engine finds no real violations in a corpus of real agent runs, the company is wrong — and Phase 0 exists to learn that in week 4, not month 6.
4. **Honest verdicts only.** `PASS` / `WARN` / `FAIL` / `UNVERIFIED`, and **UNVERIFIED is never rendered as PASS**. Never claim a step is verified beyond what the replay actually checked.
5. **Runs on the user's infrastructure.** Self-hostable, privacy-preserving; traces and state stay on their box. Sidesteps the data-governance objection from day one.
6. **Do not become an agent framework.** We wrap whatever the user already chose. If a task drifts toward "Belay orchestrates the agent," stop and flag it.
7. **Complement observability, don't compete with it.** Plug in next to Langfuse/Phoenix; add the verdict they lack.

---

## The launch wedge (locked)

**Ingest surface: the MCP tool-call proxy.** Belay sits as a transparent proxy between any agent and its MCP servers.

Chosen over a LangGraph trace adapter for three reasons:

- **It is the only surface that is both standardized and re-invocable.** MCP `tools/call` is JSON-RPC with a declared schema. LangGraph's tool calls are in-process Python callables — replaying them means re-entering the LangGraph runtime, which couples the engine to one framework and violates principle #6.
- **One adapter covers every framework** that speaks MCP: Claude Code, Cursor, OpenAI agents, LangGraph itself.
- **MCP tool annotations are a free verdict axis.** `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` are *declared contracts*. A tool that declares `readOnlyHint: true` and mutates the filesystem during replay is a grounded FAIL with zero LLM involvement — a verdict axis no incumbent has.

**Known cost of this choice:** an agent's *built-in* tools (Claude Code's `Bash`/`Edit`) do not traverse MCP. Belay v0 verifies what crosses the MCP boundary, and says so plainly rather than implying total coverage. Demos and the Phase 0 corpus therefore use MCP filesystem + shell servers. Broadening past the MCP boundary is a Phase 2 question, driven by demand-pull.

---

## What "Belay verified a step" means (the verdict contract)

Three axes, deliberately **unequal**:

| Axis | Grounding | May emit |
|------|-----------|----------|
| **A1 · Invariant** | Sandbox-enforced policy; violation observed during replay | PASS / WARN / FAIL / UNVERIFIED |
| **A2 · Replay** | Re-execution + state diff (result-equivalence, effect-conformance) | PASS / WARN / FAIL / UNVERIFIED |
| **A3 · Claim re-derivation** | A model writes an executable check; **execution** decides | WARN / FAIL / UNVERIFIED — **never PASS** |

**Reduction rule.** Worst-status-wins across **A1 and A2 only**. A3 may *downgrade* a verdict, never promote one, and never turns UNVERIFIED into PASS. If no deterministic axis could run, the turn is **UNVERIFIED**.

**The refutation guarantee.** `belay --no-claim-axis` disables A3 entirely and every PASS/FAIL verdict survives unchanged. This is the one-command answer to "isn't this an LLM judge with extra steps?" — it must remain true at every commit, and it is enforced by a test, not by intent.

### The axes are not redundant — they catch different things

This distinction is load-bearing and easy to get wrong:

- **A2 (replay) catches *trace infidelity*** — fabricated, tampered, or nondeterministic results. It **cannot** catch a cheating agent, because a cheater's trace is perfectly *faithful*: it really did delete the test. Replay restores the recorded pre-state (which already contains the weakened test), re-invokes, and observes the same "3 passed". A2 returns PASS. Correctly.
- **A1 (invariant) catches *corrupt success*** — the 27–78%. A declared invariant (*"the test suite is the oracle; `tests/` is read-only for this task"*) is violated at the exact turn, deterministically, with no LLM. **A1 is the axis that earns the headline statistic.**
- **A3 (claim) catches *intent drift*** — faithful trace, in-policy actions, wrong meaning. It is the axis that sharpens as base models improve (principle: a stronger model writes better checks), and it is the axis that gets cut if the calendar slips.

Building A2 alone and expecting it to catch cheating is the single most likely way this roadmap fails quietly.

---

## Phase Overview

| Phase | Theme | Duration | Exit Gate |
|-------|-------|----------|-----------|
| **0** | Corpus proof: does the engine catch anything real? | Weeks 1–4 | Quantified violation rate + ≥3 hand-audited true positives + a **stated false-positive rate** |
| **1** | MVP hardening + OSS / Product Hunt launch | Weeks 5–8 | ≥3 external parties self-host and catch a real failure on **their** agent |
| **2** | Team layer: CI regression gate, shared corpus, approval gate | Months 3–6 | First credible willingness-to-pay + demand-pull for a second surface |
| **3** | Managed control plane | Months 6+ | Repeatable managed motion + corpus measurably improving detection |

---

## Phase 0: Corpus Proof (Weeks 1–4)

**Objective:** Prove the engine detects real violations in real agent runs at a rate worth building a company on — and publish the number.

**Decision philosophy:** This phase is an experiment, not a product launch. Optimize for *learning whether to continue*, not for code quality or coverage. There is no dashboard, no packaging, and no launch in this phase.

### The corpus: minted, not scavenged

An honesty note that must not be papered over: **public MCP trace archives do not meaningfully exist.** We cannot "audit traces found in the wild" — that framing would be a lie.

Instead Phase 0 **mints** its corpus: run an open MCP-speaking agent against open tasks (SWE-bench-lite instances) through the Belay proxy, using off-the-shelf MCP filesystem + shell servers. We give up "found in the wild." We keep the property that actually matters: **anyone can re-run the harness and reproduce the number.** Reproducibility, not provenance, is what makes the number credible.

### Milestones

| Week | Milestone | Deliverable | Success Signal |
|------|-----------|-------------|----------------|
| 1 | MCP proxy captures a trace (C1) | Every `tools/call` recorded with args, result, timing, content hashes | A real agent run round-trips through the proxy with zero behavior change |
| 1–2 | Sandbox + snapshot/restore (C2) | Boundaries enforced; pre-state restorable per turn | A turn's pre-state restores byte-identically; escape attempts are contained |
| 2 | Deterministic replay (C3) | Any recorded turn re-invoked against its restored pre-state | Replaying a clean run reproduces every result |
| 2–3 | Replay-verify — axis A2 (C4) | Result-equivalence + effect-conformance vs MCP annotations | An injected fabricated result yields FAIL with a concrete diff; a nondeterministic tool yields UNVERIFIED, never PASS |
| 3 | Invariant verdict — axis A1 (C5) | Declared invariants evaluated against observed replay effects | An injected cheat (weakened test) yields FAIL at the exact turn |
| 3–4 | Run the corpus | ≥50 agent runs through the harness on SWE-bench-lite | Verdicts emitted for every turn; UNVERIFIED rate measured and explainable |
| 4 | **Hand-audit + the number** | Violation-rate report + false-positive analysis | Every flagged run manually adjudicated |
| 4 | **DECISION GATE** | Go/no-go memo | See gate below |

### Phase 0 Success Metrics

- **Violation rate:** measured and reported with its denominator (not a headline percentage without one).
- **True positives:** ≥3 flagged violations hand-audited and confirmed as genuine.
- **False-positive rate:** **stated, not hidden.** A high FP rate is a fixable engineering problem; an unstated one is a credibility problem we never recover from.
- **UNVERIFIED rate:** measured and *explained* — every UNVERIFIED must trace to a named cause (nondeterministic tool, unrestorable state, missing pre-state).
- **Replay fidelity:** a clean run replays with 100% result-equivalence.

### 🚦 Phase 0 → Phase 1 Gate

- **PROCEED** if the harness produces a **reproducible, quantified violation rate** with **≥3 hand-audited true positives** and a **stated false-positive rate** we're willing to publish.
- **PIVOT** if the violation rate is ~0 on real runs. That is not a bug — it is the premise failing, and it is worth finding out in week 4. Re-examine: wrong task set (too easy to cheat-proof)? wrong surface (the interesting failures don't cross MCP)? are the failures real but *unverifiable* by replay?
- **PIVOT** if the false-positive rate is so high that flagged runs are noise. Do **not** launch and hope.

---

## Phase 1: MVP Hardening + OSS Launch (Weeks 5–8)

**Objective:** Turn the Phase-0 engine into something a stranger can `docker run` against their own agent, and launch it publicly on the strength of the Phase-0 number.

**Scope discipline:** Still ONE ingest surface. We are deepening and packaging, not widening.

### The launch demo (locked)

One repo, one failing test, an agent told *"make the tests pass."* It weakens the test and reports success — a real, documented behavior, not a staged trick. Belay flags **turn 7**: invariant `tests/ is read-only` violated, with the exact diff. The A3 claim axis independently corroborates ("all tests pass" re-derived against the **original** suite → exit 1). Shown side-by-side with a green Langfuse trace of the same run.

*"Your agent lied. Your dashboard didn't notice. Mine did."*

The headline verdict is deterministic. A3 corroborates; it never carries the demo.

### Key Deliverables

| Area | Deliverable |
|------|-------------|
| Corpus | Every caught failure becomes a labeled, replayable case (C6) |
| Console | Local-first live run feed + per-turn verdicts, streaming (C7) |
| Claim axis | A3 shipped, subordinated, and refutable via `--no-claim-axis` (C8) |
| Interop | Ingest OTel/OpenLLMetry spans; sit beside Langfuse/Phoenix (C9) |
| Packaging | `docker run` self-host; BYOK / local-model friendly for A3; never a vendor key |
| License | Apache-2.0 (permissive + explicit patent/trademark grant) |
| Docs | Honest coverage statement: what Belay verifies, and what it does **not** |

### Success Metrics

- **External self-hosts:** ≥3 parties run Belay on their own agent.
- **Real catches:** ≥3 externally-reported failures Belay surfaced that the team didn't already know about.
- **Time-to-first-verdict** for a new user: under 15 minutes from `docker run`.
- **False-positive reports:** tracked openly as issues; each becomes a corpus case.
- **Corpus growth:** every Phase-1 catch lands in the corpus (moat #2 must compound with each feature).

### 🚦 Phase 1 → Phase 2 Gate

- ≥3 external parties self-host **and** catch a real failure on their own agent, **and**
- The deterministic spine holds: no shipped PASS is ever produced by A3, verified by test, **and**
- ≥2 users explicitly ask for a shared/CI surface (demand-pull, not our guess).

---

## Phase 2: Team Layer (Months 3–6)

**Objective:** Prove the verdict is worth *money* to a team, and that the corpus is a shared asset rather than a private log.

### Goals

- **CI regression gate:** a past run replays in CI; a new agent version that breaks a previously-passing trajectory fails the build. This is the first surface with obvious budget attached.
- **Approval gate:** hold a risky action (destructive, `openWorldHint`) pending human approval — the "watch and steer" surface.
- **Shared corpus:** the team's failure corpus as a queryable, growing asset.
- **The invariant-authoring problem** (the known Phase-1 friction): who writes the invariant for a stranger's agent? Candidate answers to test — inferred from MCP annotations (free), inferred from the task spec, a library of common invariants, or authored by the user. This is a real adoption risk and gets a real experiment, not an assumption.
- **Second surface, only by demand-pull** (likely a coding-agent actuator hook, to reach past the MCP boundary).

### Success Metrics

- **WTP:** first teams paying, from a named budget.
- **CI gate adoption:** ≥40% of active teams wire the regression gate.
- **Invariant friction:** median invariants hand-authored per repo trending toward zero.
- **Detection improving from the corpus** on a held-out internal benchmark.

### 🚦 Phase 2 → Phase 3 Gate

- Credible recurring revenue from the team layer, **and**
- The corpus measurably improves detection (not just grows), **and**
- At least one team runs Belay unattended in a production path.

---

## Phase 3: Managed Control Plane (Months 6+)

**Objective:** Become the default harness for production agents; compound the corpus into a durable data advantage.

### Goals

- **Control plane:** the managed layer that runs agents in production reliably — the business.
- **Flywheel:** every consented run (failures, verdicts, replays) improves detection. Our edge is *learned from real failures*, not from a static model.
- **Enterprise:** SSO, VPC/on-prem, audit logs, data residency, SLAs. (Note: "runs on your infra" has been the architecture since day 1, so this is packaging, not a rewrite.)
- **Trust:** publish our detection accuracy against the Phase-0 corpus, independently reproducible.

### Success Metrics

- **Detection accuracy** improving quarter-over-quarter against a held-out benchmark.
- **Enterprise logos** with a repeatable motion and shrinking cycle time.
- **Published, reproducible benchmark** — the Phase-0 number, grown up.

---

## Engine capability track

The phases above are *what we earn*. The sequenced, one-at-a-time backlog of *how we earn it* lives in [`docs/technical/CAPABILITY_ROADMAP.md`](technical/CAPABILITY_ROADMAP.md):

| ID | Capability | Window | Why |
|----|-----------|--------|-----|
| **C1** | MCP proxy trace capture | Week 1 | Nothing exists without the trace; the wedge itself |
| **C2** | Sandbox + execution boundaries | Weeks 1–2 | Primitive #1, and the prerequisite for all replay |
| **C3** | Deterministic replay | Week 2 | The durable moat; the thing a better model never makes redundant |
| **C4** | Replay-verify — axis A2 | Weeks 2–3 | The grounded verdict; catches trace infidelity |
| **C5** | Invariant verdict — axis A1 | Week 3 | Catches corrupt success; earns the 27–78% stat |
| **C6** | Failure corpus | Week 5 | Moat #2; must compound with every feature |
| **C7** | Live console | Weeks 5–6 | The launch surface; "watch and steer" |
| **C8** | Claim re-derivation — axis A3 | Week 7 | Gets better as models improve; **cuttable if the calendar slips** |
| **C9** | Observability interop | Week 8 | Makes "we complement Langfuse/Phoenix" shipped, not rhetorical |

**C1–C5 is the engine and the Phase-0 gate. C6–C7 is the launch. C8 is deliberately last** — a slipped month must cut the LLM axis, never the deterministic spine.

---

## Risks & Assumptions Register

| # | Risk / Assumption | Tied to | Likelihood | Impact | Mitigation / Test |
|---|-------------------|---------|-----------|--------|-------------------|
| R1 | **The premise is wrong** — real agent runs contain ~no detectable violations | Phase 0 gate | Low | Fatal | The entire Phase 0 corpus proof; pivot rule baked into the gate |
| R2 | **C2 (snapshot/restore) is harder than budgeted** — it's week 2 and everything blocks on it | Phase 0, Wk 1–2 | **High** | **High** | Start with the narrowest restorable substrate (container FS overlay, one tool family); abstract late; if it slips, the whole calendar slips — treat as the schedule's critical path |
| R3 | **Nobody authors the invariant** — A1 works but only if someone declares the policy | Phase 1 adoption | **High** | **High** | Infer from MCP annotations first (free, zero-friction); ship a library of common invariants; explicit Phase-2 experiment. **Named now, not discovered at launch** |
| R4 | **"LLM judge with extra steps"** becomes the top launch comment | Phase 1 launch | Med | High | A3 structurally subordinated; `--no-claim-axis` refutation enforced by test; deterministic spine ships first and leads every demo |
| R5 | **Replay verifies fidelity, not correctness** — we over-claim what A2 proves | All phases | Med | **Fatal (trust)** | The axis-separation is documented in the roadmap itself; UNVERIFIED never rendered as PASS; honest coverage statement in the docs |
| R6 | **The interesting failures don't cross the MCP boundary** (built-in Bash/Edit bypass the proxy) | Wedge choice | **High** | High | Stated openly as v0 coverage; corpus + demos use MCP FS/shell servers; a coding-agent actuator hook is the demand-pulled Phase-2 surface |
| R7 | **Nondeterministic tools make UNVERIFIED the default verdict** — the product says "shrug" | Phase 0 metric | Med | High | Measure UNVERIFIED rate in Phase 0 and require every instance trace to a named cause; if it dominates, that's a gate signal |
| R8 | **Sandbox escape / Belay itself is the vulnerability** — we run untrusted agent actions | Phase 0 onward | Med | High | Containment is primitive #1, not a feature; threat-model C2 explicitly; never claim boundaries we don't enforce |
| R9 | **Observability incumbents add replay** | All phases | Med | High | Move fast on the engine + corpus; interop (C9) makes us complementary, not a target; community trust as defensive moat |
| R10 | **Solo-founder bandwidth** — engine + console + launch in 8 weeks | Phases 0–1 | **High** | Med | C8/C9 are explicitly cuttable; Phase 0 ships no UI at all; narrow-then-expand enforced by the gates |
| R11 | **OSS adoption ≠ revenue** — everyone self-hosts, nobody pays | Phase 2 gate | Med | High | CI gate is the first surface with a named budget; WTP tested at the Phase-2 gate, not assumed |
| R12 | **Corpus needs consent users won't give** | Phase 3 flywheel | Med | Med | Opt-in; share failure patterns/metadata, never raw state; runs on user infra by design |

---

## One-line phase mantra

**Phase 0:** earn the number. **Phase 1:** earn the stars. **Phase 2:** earn the budget. **Phase 3:** make every run make the next one smarter.
