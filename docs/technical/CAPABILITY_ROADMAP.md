# Belay: Engine Capability Roadmap

The phased plan in [`docs/ROADMAP.md`](../ROADMAP.md) is *what we earn*. This document is
*how we earn it*: the sequenced, one-at-a-time backlog of engine capabilities. It exists so
we can go through the work one capability at a time, shipping something real each time.

Everything here stays on the harness side of the wedge (sandbox, verify-by-replay,
deterministic replay, corpus). Nothing here authors or orchestrates an agent, and nothing
here rests on a bare LLM judge. See the guardrails at the end.

---

## How to read this

- Capabilities are labelled **C1 … C9** in build order. Each is independently shippable and
  leaves the engine more capable than before.
- **Time windows** are guidance for sequencing, not commitments. Real demand-pull reorders
  this freely.
- Every capability is built **test-first** (the repo's standing discipline): each one lists
  its acceptance as a failing test we write before the code.
- Every capability names the **eval data it captures**, because the accumulating corpus of
  labeled failures is moat #2 and must compound with each feature.

### The single framing

The moat is the **execution-grounded verdict** and the **deterministic replay** that
produces it. Each capability either makes the verdict *more trustworthy* (replay-verify,
invariants), *more reproducible* (capture, replay, sandbox), *more useful* (console,
interop), or *compounds the corpus*. A better base model should make each of these
stronger, never redundant.

### The verdict contract (referenced throughout)

Three axes, deliberately unequal. `PASS` / `WARN` / `FAIL` / `UNVERIFIED`, and
**UNVERIFIED is never rendered as PASS.**

| Axis | Grounding | May emit |
|------|-----------|----------|
| **A1 · Invariant** | Sandbox-enforced policy, violation observed during replay | PASS / WARN / FAIL / UNVERIFIED |
| **A2 · Replay** | Re-execution + state diff | PASS / WARN / FAIL / UNVERIFIED |
| **A3 · Claim re-derivation** | A model writes an executable check; **execution** decides | WARN / FAIL / UNVERIFIED — **never PASS** |

Reduction: worst-status-wins across **A1 and A2 only**. A3 may downgrade, never promote.

### Why the axes are not redundant

The most important structural fact in this document, and the easiest to get wrong:

- **A2 catches trace infidelity** — fabricated, tampered, nondeterministic results.
- **A2 cannot catch cheating.** A cheating agent's trace is *faithful*. Replay restores the
  recorded pre-state (already containing the weakened test), re-invokes, observes the same
  result, and returns **PASS — correctly**.
- **A1 catches corrupt success** — the 27–78%. A declared invariant is violated at an exact
  turn, deterministically.
- **A3 catches intent drift** — faithful trace, in-policy actions, wrong meaning.

Building A2 and expecting it to catch the launch demo is the single most likely way this
engine quietly fails.

---

## C1. MCP proxy trace capture  ·  week 1

**Why it is moat.** Nothing else in this document exists without the trace. This is the
wedge itself: MCP `tools/call` is the only agent tool-call surface that is *both*
standardized *and* re-invocable without a framework runtime. One adapter covers Claude
Code, Cursor, OpenAI agents, and LangGraph. The trace is also the corpus's raw material —
every later capability reads what C1 writes.

**What we build:**
- A transparent MCP proxy: the agent points at Belay, Belay points at the real MCP servers.
  It speaks JSON-RPC on both sides and is **behavior-neutral** — an agent run through the
  proxy must behave exactly as it does without it.
- Capture per `tools/call`: server identity, tool name, arguments, result, `isError`,
  timing, ordering, and the tool's declared **annotations** (`readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`) snapshotted from `tools/list` at
  session start.
- Content-address everything (hash args, result, and the pre/post state handle from C2) so
  a trace is tamper-evident and comparable across runs.
- An append-only, self-describing trace format on disk. It is the interchange format for the
  whole engine, so it gets a versioned schema on day 1.
- Capture is **lossless and opinion-free**. C1 makes no judgements — it records.

**Acceptance (test-first):**
- A fake MCP server + a scripted client round-trip through the proxy; the client observes
  byte-identical responses to a direct connection (behavior-neutrality).
- Every `tools/call` appears in the trace with args, result, and annotations; hashes are
  stable across two identical runs.
- A malformed / non-conforming server yields a recorded, honest error, never a dropped turn.
- A trace written by version N is readable by version N (schema round-trip), deterministic,
  no network.

**Eval data captured:** every run is a trace. Tool-annotation distributions per server become
the reference for C4's effect-conformance. This is the corpus's substrate.

**Dependencies:** none. This is the first commit of the engine.

---

## C2. Sandbox + execution boundaries  ·  weeks 1–2

**Why it is moat.** Primitive #1, and the prerequisite for literally every verdict: you
cannot re-execute a turn without restoring the state it ran against. Containment and
verification are the same machinery here, which is why the sandbox is not "a feature" — it
is the engine's floor.

**⚠️ This is the schedule's critical path.** Snapshot/restore fidelity is the hardest
problem in the v0 engine, it lands in week 2, and C3/C4/C5 all block on it. Risk **R2** in
the roadmap. Start with the narrowest restorable substrate that carries the demo (a container
filesystem overlay + one tool family), and abstract *late*.

**What we build:**
- A pluggable sandbox seam (`sandbox/` with a `Sandbox` protocol) so containers / gVisor /
  firejail are swappable. **Ship exactly one** implementation first — the abstraction is
  earned by the second, not designed for it.
- Enforced boundaries: filesystem scope, network policy, and per-tool allow/deny. A denied
  action is contained and *recorded as denied*, never silently dropped.
- **Snapshot / restore**: a per-turn pre-state handle that can be restored byte-identically.
  This is what C3 replays against.
- An explicit, documented **unrestorable** signal. State we cannot restore is not guessed at
  — it propagates as `UNVERIFIED` all the way to the verdict. This is the first place the
  honesty contract becomes load-bearing code.
- A threat model doc: Belay executes untrusted agent actions, so Belay is itself an attack
  surface (risk R8). We never claim a boundary we don't enforce.

**Acceptance (test-first):**
- A turn's pre-state snapshot restores byte-identically; a hash of the restored tree equals
  the hash of the original.
- An escape attempt (write outside scope, disallowed network egress) is contained AND appears
  in the trace as a denial.
- An explicitly unrestorable substrate (e.g. a stateful remote service) yields the
  `unrestorable` signal, **never** a silent success.
- Deterministic, no network, runs in CI.

**Eval data captured:** restore-fidelity rate per tool family, and the taxonomy of
unrestorable substrates — which directly predicts the UNVERIFIED rate (risk R7).

**Dependencies:** C1 (needs a trace to snapshot against).

---

## C3. Deterministic replay  ·  week 2

**Why it is moat.** This is the durable core. A stronger base model writes better checks and
cleaner re-derivations, and makes Belay *sharper*; it never makes deterministic replay
redundant. A judge's guess gets cheaper to fool every year — a re-executed diff does not.
Replay is also what makes the trace *useful* rather than merely recorded, which is precisely
the line between us and Langfuse/Phoenix.

**What we build:**
- `belay replay <trace> [--turn N]`: restore the recorded pre-state (C2), re-invoke the exact
  recorded `tools/call` against the real MCP server, capture the observed result and the
  observed state delta.
- Replay is **side-effect-contained by construction** — it runs in the sandbox, against a
  restored copy, never against live state.
- Nondeterminism is *detected, not hidden*: replaying a turn N times and observing divergent
  results marks the tool nondeterministic in the trace. That marking is an input to C4, not
  an excuse.
- Whole-trajectory replay (`--from`, `--to`) for debugging, regression, and audit.

**Acceptance (test-first):**
- Replaying a clean recorded run reproduces every result with 100% result-equivalence.
- Replaying a turn whose pre-state is unrestorable yields `unverified`, never a result.
- A deliberately nondeterministic fake tool (clock/random) is detected as nondeterministic
  across repeated replays rather than reported as a divergence.
- Replay never mutates the original trace or live state (asserted, not assumed).
- Deterministic, no network (fake MCP servers), runs in CI.

**Eval data captured:** per-tool determinism classification — a reference distribution that
tells us which tools are verifiable at all, and feeds the UNVERIFIED-rate explanation.

**Dependencies:** C1, C2.

---

## C4. Replay-verify — axis A2  ·  weeks 2–3

**Why it is moat.** The first grounded verdict, and the answer to the question no incumbent
answers. Langfuse/Phoenix/LangSmith/Braintrust record and (optionally) LLM-judge score; none
re-execute a tool call in a sandbox to check real state. There is no LLM anywhere in this
capability — that is the point.

**What we build.** Two deterministic checks per turn:

- **Result equivalence.** Restore pre-state, re-invoke, diff observed result vs recorded
  result. Divergence = the trace does not reproduce = **FAIL** with a concrete diff
  (`kind="replay"`). A tool classified nondeterministic by C3 yields **UNVERIFIED**, never
  PASS and never a false FAIL.
- **Effect conformance.** Snapshot state before/after the replayed call, compute the real
  delta (files touched, network egress, exit codes), and check it against the tool's
  **declared MCP annotations** plus the sandbox policy. A tool declaring `readOnlyHint: true`
  that mutates the filesystem is a **grounded FAIL** with zero LLM involvement — a verdict
  axis that exists only because we chose the MCP wedge. A tool that declares *no* annotations
  yields `unverified` for this check (an absent contract is not a permissive one).
- A `Verdict` model (axis, kind, status, observed, expected, message) and the reduction rule
  (worst-status-wins across A1/A2).

**Acceptance (test-first):**
- A fake server injected with a fabricated result yields **FAIL** with the exact recorded-vs-
  observed diff in the message.
- A clean turn yields **PASS**.
- A nondeterministic tool yields **UNVERIFIED**, not FAIL and not PASS.
- A `readOnlyHint: true` tool that writes a file yields **FAIL** naming the annotation and the
  observed write.
- An un-annotated tool yields **UNVERIFIED** for effect-conformance while result-equivalence
  still decides independently.
- A turn with an unrestorable pre-state yields **UNVERIFIED** — asserted explicitly, because
  this is the "never a false pass" contract in code.
- Deterministic, no network.

**Eval data captured:** every divergence is a labeled **trace-infidelity** case in the corpus,
with its pre-state, recorded result, and observed result — a replayable regression forever.

**Dependencies:** C1, C2, C3.

---

## C5. Invariant verdict — axis A1  ·  week 3

**Why it is moat.** **This is the capability that earns the 27–78% statistic**, and the one
most likely to be under-built because A2 *looks* like it already covers verification. It does
not (see "Why the axes are not redundant"). A cheating agent's trace is faithful; only a
declared invariant catches it, and it catches it deterministically, at an exact turn, with no
LLM. No incumbent has this axis at all.

This capability also reframes primitive #1: **the sandbox is not just containment, it is a
verdict axis.** The boundary that contains an action is the same machinery that judges it.

**What we build:**
- An invariant declaration format: scoped, declarative, versioned with the trace (e.g.
  *"`tests/` is read-only for this task"*, *"no network egress to non-allowlisted hosts"*,
  *"no tool declaring `destructiveHint` outside `build/`"*).
- Evaluation of invariants against the **observed effects of replay** (from C4), not against
  the agent's prose and not against a static lint of the trace. Grounded by construction.
- **Annotation-inferred invariants** — the zero-friction default. Every MCP tool's declared
  annotations *are* an invariant we get for free, with no user authoring. This is the first
  mitigation of risk **R3** (nobody authors the invariant) and it must ship inside C5, not
  after it.
- A violation yields FAIL (`kind="invariant"`) naming the invariant, the turn, and the exact
  observed effect that broke it.
- An invariant that cannot be evaluated (effects unobservable for that substrate) yields
  `unverified` — never a silent pass.

**Acceptance (test-first):**
- **The launch demo, as a test.** A recorded trace in which the agent weakens a test file and
  reports success yields **FAIL at the exact turn**, naming the `tests/` read-only invariant
  and showing the diff — while A2 independently returns PASS on that same turn (asserting the
  axes are genuinely non-redundant, which is the whole thesis).
- A clean run yields PASS on A1.
- An annotation-inferred invariant fires with **zero user-authored config**.
- An unevaluable invariant yields **UNVERIFIED**, never PASS.
- Deterministic, no network.

**Eval data captured:** every violation is a labeled **corrupt-success** case — the highest-
value cases in the corpus, and the ones the Phase-0 number is made of.

**Dependencies:** C1, C2, C3, C4.

> ### 🚦 C1–C5 = the Phase 0 gate
> At this point the engine exists with no UI and no packaging. Run the minted corpus (≥50
> SWE-bench-lite runs through the proxy), hand-audit the flags, and publish the violation rate
> **with its false-positive rate**. If the rate is ~0, stop and pivot — the premise is wrong,
> and it is worth knowing in week 4.

---

## C6. Failure corpus  ·  week 5

**Why it is moat.** Moat #2, and the one that compounds. Every caught failure becomes a
labeled, replayable case that sharpens detection over time. This is the asset a competitor
cannot clone by reading our source, and the thing that makes a better base model make Belay
*better* rather than redundant — more cases, better checks.

**What we build:**
- A corpus format: each case = trace slice + pre-state handle + expected verdict + a
  human-audited label (true positive / false positive / unverifiable).
- `belay corpus add` from any flagged run; `belay corpus run` replays the whole corpus and
  asserts the expected verdicts — i.e. **the corpus is the regression suite**. Detection
  changes that break a past case fail CI.
- Precision/recall reporting against the audited labels, so "detection improved" is a measured
  claim rather than a vibe.
- Privacy by construction: cases store what the user's own infra already holds. Nothing is
  uploaded, ever. Sharing (Phase 2+) is opt-in and pattern-level, never raw state.
- **Every subsequent capability must add cases.** A capability that catches nothing new does
  not ship.

**Acceptance (test-first):**
- A Phase-0 flagged run round-trips into a corpus case and replays to the same verdict.
- A deliberately regressed detector fails `belay corpus run` with the exact case named.
- Precision/recall computed against a fixture corpus with known labels matches hand-computed
  values.
- Deterministic, no network.

**Eval data captured:** this capability *is* the eval data. It seeds from Phase 0's audited
corpus on day 1 rather than starting empty.

**Dependencies:** C1–C5.

---

## C7. Live console  ·  weeks 5–6

**Why it is moat.** Not the moat itself — the *surface* through which the moat is legible.
The streaming, steerable live-run feed is a proven shape (mirroring `contig watch`), and it
is what makes the launch demo land: a green Langfuse trace beside Belay's red turn-7 verdict.
It is also the "watch and steer" primitive the team/approval layer grows out of in Phase 2.

**What we build:**
- Local-first, self-hosted, TypeScript (Next.js or Vue). It talks to the local engine; nothing
  leaves the box.
- A streaming per-turn feed: tool call, args, verdict, and — where FAILed — the concrete diff
  that grounded it.
- **The verdict rendering is the honesty contract made visible.** UNVERIFIED gets its own
  distinct treatment and is never colored, grouped, or summarized as PASS. A3 verdicts (C8)
  are visually distinct from deterministic ones and always show the generated check's source
  plus its real exit code, so a reader can see that *execution* decided.
- Replay-from-here: any past turn re-runnable from the console.

**Acceptance (test-first):**
- A recorded trace renders every turn with its verdict; the FAILed turn shows its diff.
- An UNVERIFIED turn is asserted to render distinctly from PASS (a snapshot/DOM test — this is
  a correctness test, not a style test, because the whole product rests on it).
- The console works fully offline against a local trace.

**Eval data captured:** which turns a human clicks into, and which verdicts get overridden —
the first signal of where our verdicts are *unconvincing* rather than merely wrong.

**Dependencies:** C1–C6.

---

## C8. Claim re-derivation — axis A3  ·  week 7  ·  **cuttable**

**Why it is moat.** This is the axis that most directly satisfies "gets better as models
improve": a stronger base model writes a better executable check, and the check's **exit code**
— not the model's opinion — decides the verdict. The model is a *check author*, never a judge.
It catches the class the deterministic axes structurally cannot: faithful trace, in-policy
actions, wrong meaning.

**It is sequenced last on purpose.** If the calendar slips, this is what gets cut — never the
deterministic spine. It is the only capability in this document that may be dropped from v0
without invalidating the launch.

**What we build:**
- Extract the agent's asserted post-conditions from its output; synthesize an **executable**
  check; run it in the sandbox (C2) against the recorded final state; the exit code is the
  verdict.
- **Hard structural subordination**, enforced in code and by test:
  - A3 may emit only WARN / FAIL / UNVERIFIED. **It can never emit PASS.**
  - A3 may downgrade a reduced verdict, never promote one, and never turns UNVERIFIED into PASS.
  - A synthesized check that will not execute is **UNVERIFIED**, not a guess.
  - Every A3 verdict surfaces the generated check's **source** and its **real exit code**.
- `belay --no-claim-axis`: disables A3 entirely; every PASS/FAIL verdict survives unchanged.
- BYOK / local-model friendly. Never a vendor key, nothing proxied, no raw-state egress.

**Acceptance (test-first):**
- **The refutation guarantee, as a test:** run the full corpus with and without
  `--no-claim-axis`; assert every PASS and every FAIL verdict is **identical**. This test is
  the company's positioning encoded as CI, and it must never be weakened.
- A property test asserts A3 **cannot** produce PASS for any input (exhaustive over the status
  enum).
- A synthesized check that fails to execute yields UNVERIFIED, never a guess.
- The launch demo: "all tests pass" re-derived against the **original** suite yields exit 1 →
  FAIL, corroborating the A1 verdict on the same run from an independent axis.
- Model calls are behind an injectable seam and **never run in CI** (fake injected; a manual
  gate covers the live path).

**Eval data captured:** labeled **intent-drift** cases, plus — valuably — the synthesized
checks themselves. Which generated checks execute, which don't, and which agree with A1 is a
direct measurement of the "better models make us better" thesis.

**Dependencies:** C1–C6. (C7 for the demo rendering.)

---

## C9. Observability interop  ·  week 8

**Why it is moat.** It protects the moat rather than being it. "We complement Langfuse and
Phoenix, we don't compete" is *positioning* until this ships — after it, it's a fact. It makes
us additive to a tool a team already runs (near-zero adoption cost, we don't ask them to
switch), and it converts the incumbents from competitors into distribution.

**What we build:**
- Ingest OpenTelemetry / OpenLLMetry-style spans so Belay can attach verdicts to traces a team
  already collects.
- Export verdicts back as span attributes/events, so a Belay FAIL is visible inside the
  dashboard the team already watches.
- **An honest coverage statement**, in the docs and in the export: which spans Belay verified,
  which it could not, and why. An ingested span from a non-MCP surface is not replayable and is
  reported `UNVERIFIED` — the interop path is exactly where over-claiming would be easiest and
  most damaging (risk R5).

**Acceptance (test-first):**
- A fixture OTel span set ingests and correlates to the matching MCP turns.
- A non-replayable ingested span yields **UNVERIFIED**, never PASS — asserted explicitly.
- Exported verdicts round-trip into a fixture collector with the axis and status intact.
- Deterministic, no network.

**Eval data captured:** the correlation rate between third-party traces and MCP turns — i.e. a
direct measurement of risk **R6** (how much of a real agent's activity actually crosses the MCP
boundary). This number decides whether the Phase-2 second surface is needed.

**Dependencies:** C1–C4.

---

## Guardrails (restated so the engine doesn't drift)

Every capability above is checked against these. A proposal that violates one gets flagged, not
built.

1. **No agent framework.** We wrap what the user already chose. If a capability starts
   orchestrating or authoring the agent, stop.
2. **No bare LLM judge.** The verdict is grounded in re-execution. A model may *write a check*;
   only execution may *decide*. A3's subordination is enforced by test, not intent.
3. **UNVERIFIED is never PASS.** Every capability that can fail to evaluate must have an
   explicit UNVERIFIED path with a named cause, and a test asserting it.
4. **No raw-data egress.** Belay runs on the user's infra. Traces, state, and corpus stay on
   their box. BYOK / local-model for A3.
5. **The engine gets better as models improve.** Reject any capability that a stronger base
   model would make redundant.
6. **Test-first, always.** Each capability's acceptance is written as a failing test before the
   code.
7. **Never claim coverage we don't have.** v0 verifies what crosses the MCP boundary. Built-in
   agent tools (Claude Code's `Bash`/`Edit`) do not. Say so.

---

## Sequencing summary

| ID | Capability | Window | Phase | Cuttable? |
|----|-----------|--------|-------|-----------|
| C1 | MCP proxy trace capture | Wk 1 | 0 | No — the wedge |
| C2 | Sandbox + execution boundaries | Wk 1–2 | 0 | No — **critical path** |
| C3 | Deterministic replay | Wk 2 | 0 | No — the moat |
| C4 | Replay-verify (A2) | Wk 2–3 | 0 | No |
| C5 | Invariant verdict (A1) | Wk 3 | 0 | No — earns the stat |
| — | **Phase 0 gate: the number** | Wk 4 | 0 | — |
| C6 | Failure corpus | Wk 5 | 1 | No — moat #2 |
| C7 | Live console | Wk 5–6 | 1 | No — the launch surface |
| C8 | Claim re-derivation (A3) | Wk 7 | 1 | **Yes — cut first** |
| C9 | Observability interop | Wk 8 | 1 | Yes — cut second |
