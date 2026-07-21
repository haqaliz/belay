# Belay: Project Context for Claude Code

This file orients a coding agent working in this repository. Read it first.

> **Status: C1–C6 are built and merged; the Phase-0 corpus runner is built** (463 tests, 1 platform-skip; zero runtime dependencies).
> The full record → sandbox → snapshot/restore → replay → verdict spine exists: the byte-transparent
> stdio MCP proxy + trace format (C1), the Seatbelt sandbox with snapshot/restore (C2), deterministic
> replay with a real before/after delta (C3), and the grounded verdict — **A2** result-equivalence +
> effect-conformance (C4) and **A1** task-scoped invariants (C5, `src/belay/verify/invariants.py`).
> A1 catches a *cheating* agent A2 structurally cannot: `belay verify --invariants` (the `tests/`
> read-only default is on unless `--no-default-invariants`), grounded on the observed delta, zero LLM,
> UNVERIFIED-never-PASS. **C6 — the failure corpus** (`src/belay/corpus/`, moat #2): `belay corpus
> add/run/score` stores each caught failure as a self-contained, replayable, human-labeled case; the
> corpus is the regression suite, and precision/recall/coverage measures detection against human labels
> (UNVERIFIED excluded, the engine never labels its own cases). Cases live under gitignored `corpus/local/`.
> **The Phase-0 corpus runner is built** (`src/belay/phase0/`, `belay phase0 run/report`): it verifies a
> whole directory of captured runs, ingests every flagged turn into the corpus, and emits *the number* —
> the per-instance violation rate with its denominator, plus per-turn FAIL, UNVERIFIED-by-cause, and
> false-positive rates. It is a measurement, not a gate (exits 0 with violations present), and a mint that
> captured ~no verifiable turns reads as `INSTRUMENT SUSPECT`, never a clean 0% (the R6 false-zero defense).
> **The Phase-0 minting-driver is built** (`eval/minting_driver/`, eval-only — NOT a product surface,
> NOT the `belay` CLI): a thin, sequential, BYOK MCP agent loop that drives an LLM's file/shell actions
> through off-the-shelf MCP servers (`@modelcontextprotocol/server-filesystem`, `mcp-server-commands`)
> placed behind `python -m belay.proxy`, one `tools/call` in flight at a time (R7 by construction; all
> edits cross the MCP boundary, R6 by construction). The deterministic "never >1 in flight" control-flow
> test runs in CI; the single-instance live smoke is `manual`-marked and never in CI. See `eval/README.md`.
> **The Phase-0 batch mint harness is built** (`eval/minting_driver/{batch,bridge,checkpoint,workspace}.py`
> + `eval/instances/`, eval-only): a stratified instance registry (166 strict-eligible SWE-bench-lite
> instances vs the ≥50 needed; the draw balances the 83% django+sympy concentration so the number isn't a
> django/sympy number), per-instance workspace prep at `base_commit` via cached bare clones, and a
> sequential, resumable, error-contained `run_mint` that drives each instance through the gated proxy and
> **renames each capture into the layout the stock `belay phase0 run` resolves** (`bridge_capture` — a
> mis-wire here would read as `INSTRUMENT SUSPECT`, a fake PIVOT, so it is the aspect's load-bearing test).
> All deterministic and offline; the live mint stays `manual`. **A real defect was found and fixed by
> running the live smoke for the first time: `npx -y` cannot spawn a server behind the gated proxy** (the
> contained run denies network and `~/.npm` writes by design, so npx hangs); servers are now pre-installed
> into a gitignored `eval/servers/` and launched by absolute `node` path. See `eval/README.md`.
> **Next: run the live Phase-0 mint and publish the number.** The harness is built; the blocker is a valid
> model key (the smoke reached the model and got a 401 on the configured `ANTHROPIC_API_KEY`). Staged
> plan: Stage 1 (one instance, prove the bridge against a real capture) → Stage 2 (~10, measure attrition +
> cost, fix `selected.json`) → Stage 3 (~65–70 to land a denominator ≥50, incl. 3 clean control instances).
> Gate criteria are **pre-registered** in the PRD (`docs/planning/phase0-live-mint/prd.md`): PROCEED iff ≥3
> *independent* hand-audited TPs AND denominator ≥50 AND no INSTRUMENT SUSPECT; a FAILing control voids the
> mint. Then audit, fill `docs/technical/PHASE0_RESULTS.md`, fix the stale RUNBOOK; then C7 (live console —
> first UI). C8 (A3 claim re-derivation) and C9 (observability interop) are cuttable, last.
>
> [`docs/ROADMAP.md`](docs/ROADMAP.md) (phased plan + gates) and
> [`docs/technical/CAPABILITY_ROADMAP.md`](docs/technical/CAPABILITY_ROADMAP.md)
> (the C1–C9 engine backlog) are the operative plan. This file and `VISION.md` remain the
> strategic source of truth; the two roadmaps are authoritative on sequencing. Keep all four in
> sync. `README.md` states the **honest coverage limits** — read it before making any public
> claim about what Belay verifies.
>
> **Base branch is `master`** (not `main`). Remote: `git@github.com:haqaliz/belay.git`.

---

## What this project is

**Belay** is the **agent harness**: the runtime layer that makes *any* AI agent safe and
trustworthy to run unattended in production. It **sandboxes** what the agent does,
**verifies each step by replaying it against real state** (a grounded verdict, not an
LLM judging itself), records an exact **trace**, and can **deterministically replay** any
past run.

**The name.** In climbing, to *belay* is to manage the rope that **catches a climber when
they fall**. Belay catches an agent when it fails — contains the fall, proves what
happened, and lets you replay it. The harness holds; the climber takes risks.

---

## The wedge (read this before proposing any feature)

Three kinds of tools sit near agents. Know which one we are.

- **Agent frameworks** (LangGraph, CrewAI, AutoGPT, …) — they *build* the agent. CROWDED.
  **We do NOT build a framework.** We wrap whatever the user already uses.
- **Agent observability** (Langfuse, Arize Phoenix, LangSmith, Braintrust) — they *record*
  what the agent did, and at most bolt an LLM-judge on top for scoring. We sit **next to**
  them, not against them.
- **The harness** — sandbox the actions, **verify each step by re-execution**, guarantee a
  deterministic replay, and compound a failure corpus. Essentially UNSOLVED. **This IS
  the company.**

The question none of the others answer: **"was this step actually correct?"** — answered
by *replaying the tool call in a sandbox and diffing observed-vs-claimed state*, never by
an LLM's opinion of itself.

---

## Key strategic constraints (do not violate)

1. **Do not build an agent framework.** If a task drifts toward "Belay orchestrates/authors
   the agent" as the core value, stop and flag it. We are framework-agnostic infrastructure.
2. **The moat is replay + execution-grounded verification + the accumulated failure corpus,
   NOT prompting.** Favor work that hardens the sandbox/replay/verify engine and captures
   labeled failure data over work that tweaks prompts or wraps a judge.
3. **Build the part that gets BETTER as foundation models improve.** A stronger base model
   should write better checks and cleaner re-derivations, and make Belay *better* — never
   redundant. Deterministic replay is durable; a judge's guess is not.
4. **Complement observability, don't compete with it.** Plug in next to Langfuse/Phoenix
   (ingest their traces, or OpenTelemetry/OpenLLMetry-style spans); add the verdict they lack.
5. **Honest verdicts only.** Borrow the sibling project's contract: `PASS` / `WARN` / `FAIL`
   / `UNVERIFIED`, and **UNVERIFIED is never rendered as PASS**. Never claim a step is
   verified beyond what the replay actually checked.
6. **Runs on the user's infrastructure.** Self-hostable, privacy-preserving; traces and
   state stay on their box. This sidesteps the data-governance objection from day one.

---

## The four primitives (the product surface)

1. **Sandbox / execution boundaries** — the agent acts inside enforced limits (filesystem,
   network, tools); a bad action is contained, not catastrophic. **The sandbox is not only
   containment — it is a verdict axis** (see A1 below): the boundary that contains an action
   is the same machinery that judges it.
2. **Per-turn verification by replay** — re-execute each tool call in isolation and diff the
   *observed* post-state against what the agent *claimed*. This is the core primitive.
3. **Deterministic trace + replay** — capture every run exactly; re-run any past trajectory
   for debugging, regression, and audit.
4. **A compounding failure corpus** — every caught failure becomes a labeled case that
   sharpens detection over time (this is moat #2, and it must grow with each feature).

### The three verdict axes (deliberately unequal — read before touching the verdict)

| Axis | Grounding | May emit | Catches |
|------|-----------|----------|---------|
| **A1 · Invariant** | Sandbox policy, violated during replay | PASS / WARN / FAIL / UNVERIFIED | **Corrupt success** (the 27–78%) |
| **A2 · Replay** | Re-execution + state diff | PASS / WARN / FAIL / UNVERIFIED | **Trace infidelity** (fabricated/tampered results) |
| **A3 · Claim re-derivation** | A model writes a check; **execution** decides | WARN / FAIL / UNVERIFIED — **never PASS** | **Intent drift** |

Reduction: worst-status-wins across **A1 and A2 only**. A3 may downgrade, never promote, and
never turns UNVERIFIED into PASS. `belay --no-claim-axis` disables A3 and every PASS/FAIL
verdict must survive unchanged — that guarantee is enforced by a test, and it is the
one-command refutation of "isn't this an LLM judge with extra steps?"

**The axes are NOT redundant, and this is the easiest thing here to get wrong.** A2 cannot
catch a cheating agent, because a cheater's trace is perfectly *faithful* — it really did
delete the test. Replay restores the recorded pre-state (already containing the weakened
test), re-invokes, observes the same result, and returns **PASS, correctly**. Only a declared
invariant (A1) catches corrupt success. Building A2 and expecting it to catch cheating is the
single most likely way this project fails quietly.

---

## Tech direction (ingest surface LOCKED; rest proposed)

- **Core engine: Python.** Best fit for process/sandbox control, trace capture, replay, and
  the ML/verification layer. (Matches the founder's other engine work.)
- **Sandbox:** pluggable — containers / gVisor / firejail; start with one, abstract later.
- **Ingest: the MCP tool-call proxy — LOCKED.** Belay sits as a transparent proxy between any
  agent and its MCP servers. Chosen over LangGraph because MCP is the only tool-call surface
  that is *both* standardized *and* re-invocable without a framework runtime (LangGraph's
  calls are in-process Python callables — replaying them means re-entering LangGraph, which
  couples us to one framework and violates constraint #1). One adapter covers Claude Code,
  Cursor, OpenAI agents, and LangGraph itself. Bonus: MCP tool annotations (`readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`) are **self-declared** contracts, so a
  `readOnlyHint: true` tool that mutates state is a grounded FAIL with zero LLM involvement —
  **but read the next line before leaning on it.** The spec is explicit that annotations are
  *hints*: *"not guaranteed to provide a faithful description of tool behavior"*, and clients
  **MUST** treat them as untrusted from untrusted servers. So the verdict is **contract
  conformance** — *"the server's self-declared contract does not match observed behavior"* — not
  *"the tool violated the protocol."* Real, grounded, LLM-free, and zero-config; it catches
  **honest-but-buggy** servers, which is a large and valuable class. It catches **nothing
  adversarial**: a malicious server omits the annotation (inheriting fail-safe defaults) or lies
  in the safe direction. **User-declared invariants remain the load-bearing A1 mechanism;
  annotations are a free supplement.** Note also the defaults are *not* uniformly false —
  `destructiveHint` and `openWorldHint` default to **true** — and **a default is never a
  declaration**: absent must stay distinguishable from declared-false, or a default manufactures
  a false PASS.
  **Known cost:** an agent's *built-in* tools (Claude Code's `Bash`/`Edit`) do not traverse
  MCP — v0 verifies what crosses the MCP boundary and says so plainly. An
  OpenTelemetry/OpenLLMetry ingestion path (C9) lands so Belay sits beside existing
  observability.
- **Dashboard:** TypeScript + Next.js or Vue (founder's stack), local-first, streaming a live
  run feed + per-turn verdicts (a "watch and steer" surface).
- **Distribution:** OSS, self-hostable via Docker; BYOK / local-model friendly for any
  LLM-assisted verification (never a vendor key, nothing proxied).
- **License:** lean Apache-2.0 (permissive + explicit patent/trademark grant).

The **ingest surface is locked**; the rest is still open.
`docs/technical/ARCHITECTURE.md` (to be written) is authoritative once it exists.
Until then [`docs/technical/CAPABILITY_ROADMAP.md`](docs/technical/CAPABILITY_ROADMAP.md)
is authoritative on the engine's sequencing and verdict contract.

---

## The wedge → the company

Start as the OSS **per-turn "record & replay + verdict"** layer that plugs in next to
Langfuse/Phoenix, win developer trust and stars, then grow into the managed control plane
for running agents in production. Same playbook as the founder's other projects: free,
self-hostable, verifiable → monetize the managed / team / enterprise layer later.

---

## Founder profile

Solo / small-team. **Full-stack developer + ML engineer.** The moat is engineering —
sandboxing, deterministic replay, execution-grounded verification, and the evaluation
machinery — which is exactly the founder's edge. No dependency on proprietary data or
credentials the founder lacks.

---

## Quick facts for grounding (do not fabricate beyond these)

- **27–78% of benchmark-reported agent "successes" are "corrupt successes"** that hide
  procedural / integrity violations — right end-state via a broken/unsafe/cheating path
  (arXiv 2603.03116).
- **LLM-as-judge is unreliable where it matters:** "One Token to Fool LLM-as-a-Judge" shows
  up to **35% false positives** (arXiv 2507.08794); pairwise verdicts flip **10–30%** on
  trivial order swaps. → verification must be **execution-grounded**, not a judge.
- **Agents are the fastest-growing category on GitHub:** LLM-focused projects **+178% YoY**
  (Octoverse 2025); Browser-Use ~24× growth.
- **The direction is explicitly requested:** Conviction / Sarah Guo RFS 2026 — "the harness"
  (*"infrastructure that allows AI agents to operate reliably and autonomously in
  production"*); YC RFS Summer 2026 #13 "Software for Agents"; Karpathy (Sequoia Ascent 2026)
  "sensors and actuators."
- **Incumbents record but don't verify:** Langfuse / Phoenix / LangSmith / Braintrust trace
  and (optionally) LLM-judge score; none replay tool calls in a sandbox to check real state.

If you need a statistic that isn't here, do not invent one; say it's unverified. The
research base that seeded this project is in `~/dev/at/ideas/agent-trace-verifier.md` and
`~/dev/at/ideas/vc-attractive-ideas.md`.

---

## Non-goals / guardrails (restated so the project doesn't drift)

- **No agent framework / no Layer-1 authoring** as a product surface.
- **No bare LLM-judge scoring** dressed up as verification — the verdict must be grounded in
  re-execution.
- **No raw-data egress** — Belay runs on the user's infra; only traces/verdicts/hashes they
  choose to export ever leave.
- **No correctness over-claiming** — `UNVERIFIED` is never rendered as `PASS`.
- **The engine gets better as models improve** — reject work that would make a better base
  model make Belay redundant.

---

## Docs structure (to be created)

```
README.md                       # Repo front door (to write)
VISION.md                       # Narrative thesis, moat, non-goals (seeded — see file)
CLAUDE.md                       # This file
docs/
  ROADMAP.md                    # Phased plan + gates (WRITTEN)
  technical/CAPABILITY_ROADMAP.md  # C1–C9 engine backlog, test-first (WRITTEN)
  technical/ARCHITECTURE.md     # Sandbox / replay / verify engine design (to write)
  product/PRODUCT_SPEC.md       # Product surface and flows (to write)
```

The immediate next artifact is **code**: `C1 — MCP proxy trace capture`
(see the capability roadmap). Written test-first, on a branch off `master`.
