# PRD — C4: Replay-verify (axis A2)

**Capability:** C4 · **Phase:** 0 · **Window:** weeks 2–3 · **Cuttable:** **No — the first grounded verdict**
**Dependencies:** C1 ✅ C2 ✅ C3 ✅ — all merged, 290 tests green
**Branch:** `feat/replay-verify-a2/aliz` · **Slug:** `replay-verify-a2`
**Inputs:** [`_card/issue.md`](../_card/issue.md) · [`understanding.md`](./understanding.md)

> Every API claim was read in source. **C4 emits a verdict; that is new. Zero LLM calls — that is the
> point.**

---

## Problem Statement

**The first grounded verdict, and the answer no incumbent gives.** Langfuse/Phoenix/LangSmith/
Braintrust record and (optionally) LLM-judge score; **none re-execute a tool call in a sandbox to
check real state.** C4 does — and there is no model anywhere in it.

**Who:** the whole thesis. Until C4, Belay records (C1), contains (C2), and replays (C3) — but has
**never rendered a verdict**. C4 is the capability that answers *"was this step actually correct?"* by
re-execution. It is also what the Phase-0 corpus number is *made of*.

**Evidence it's needed now:** C3 produces per-turn observations (result-equivalence, deltas, determinism
class) and a coverage report — but deliberately *"emits no PASS/FAIL... That is C4"* (`cli.py:393`). The
engine has been built for three capabilities anticipating this exact moment: `substrate.py:48` —
*"C2 emits the unrestorable fact with its cause. **C4 renders UNVERIFIED.**"*

---

## 🔴 What C4's verdict means — and what it must NEVER claim

**A2 catches trace infidelity: fabricated, tampered, or nondeterministic results.**
**A2 CANNOT catch a cheating agent** — a cheater's trace is *faithful*: it really did weaken the test.
Replay restores the recorded pre-state (already containing the weakened test), re-invokes, observes the
same result, and returns **PASS — correctly.** Only a declared invariant (A1/C5) catches corrupt
success.

> **C4's PASS means "the trace reproduces." It NEVER means "the agent did the right thing."**

This is not pedantry — `CLAUDE.md` calls building A2 and expecting it to catch cheating *"the single
most likely way this project fails quietly."* Every verdict message, docstring, `--help`, and README
line states exactly what PASS means and no more. The launch demo depends on it: **A2 returns PASS on the
cheat; A1 (C5) returns FAIL on the same turn** — proof the axes are non-redundant.

---

## Goals & Success Metrics

| Goal | Metric |
|---|---|
| Grounded FAIL on infidelity | A fabricated result → **FAIL** with the exact recorded-vs-observed diff |
| Clean turn passes | A faithful, deterministic turn → **PASS** |
| Nondeterminism never FAILs | A clock/random tool → **UNVERIFIED**, not FAIL and not PASS |
| The annotation FAIL | `readOnlyHint: true` + a filesystem write → **FAIL** naming the annotation + the write |
| Absent contract ≠ permissive | An un-annotated tool → **UNVERIFIED** for effect-conformance; result-equivalence still decides independently |
| Never a false pass | Unrestorable / un-snapshotted pre-state → **UNVERIFIED**, asserted in code |
| Zero LLM | No model call anywhere; `grep` proves it |
| Honest coverage | Network egress under allow-all is **not** claimed verified |
| Small and finished | ≤5 working days |

---

## Requirements

### Must-have

**M1 · The Verdict model.** `Verdict(axis, kind, status, observed, expected, message)`, and a
`Status` type = **PASS / WARN / FAIL / UNVERIFIED**. Nothing emits one today — C4 owns it. `axis="A2"`;
`kind` ∈ `"replay"` (result-equivalence) / `"effect"` (effect-conformance). `observed`/`expected`/
`message` carry the concrete grounding.
> **Shape it so A1 (C5) slots into the same worst-wins reduction later, and A3 (C8) as
> downgrade-only.** The model is the engine's verdict contract; get it right once.

**M2 · The reduction — worst-status-wins, UNVERIFIED never PASS.**
Ordering **FAIL > UNVERIFIED > WARN > PASS**. 🔴 **UNVERIFIED ranks ABOVE PASS/WARN** so worst-wins can
*never* turn an unverified check into a clean verdict. This is *"UNVERIFIED is never rendered as PASS"*
as a **structural property of the reduction**, not a convention — and it gets a dedicated test.
Today C4 reduces across A2's **two sub-checks**; the reduction must accept N axes so A1 joins unchanged.

**M3 · Result-equivalence check — gated on determinism.**
Read `engine.replay_turn`'s `TurnReply`: `result_equivalence` (EQUAL/DIVERGED/None), `recorded_reply`
+ `replayed_reply` (raw bytes, both present on REPLAYED → **build the concrete diff without recompute**).

🔴 **Run `determinism.classify_determinism` BEFORE promoting a divergence to FAIL:**

| result_equivalence | determinism | Verdict |
|---|---|---|
| EQUAL | DETERMINISTIC | **PASS** (`kind="replay"`) |
| DIVERGED | DETERMINISTIC | **FAIL** (`kind="replay"`, exact recorded-vs-observed diff in `message`) |
| DIVERGED | NONDETERMINISTIC | **UNVERIFIED** (carry the axis; `kind="replay"`) |
| None | — | **UNVERIFIED** (no reply to compare) |

> *"Never let a timestamp diff render as FAIL — that's how you train users to ignore the verifier."*
> **A DIVERGED-that-is-really-nondeterministic FAIL is the single most likely C4 defect.** The test
> suite asserts a clock tool is UNVERIFIED, not FAIL.
>
> **Cost, stated honestly:** this runs `replay_turn` once + `classify_determinism` (default N=3) — so a
> DIVERGED turn costs ~4 replays. **Only classify on DIVERGED** (an EQUAL turn is PASS without the
> N-replay cost); an EQUAL result from a nondeterministic tool that happened to match once is still a
> reproduction, so classifying it buys nothing. This keeps the common (PASS) path at one replay.
>
> **Distinguish a value mismatch from a malformed reply:** `_equivalence` returns DIVERGED both when
> the replayed reply is a genuinely different value AND when it fails to parse. The FAIL `message` must
> say which — a malformed/unparseable replayed reply is a distinct grounding from a value divergence,
> and a reader must be able to tell them apart.

**M4 · Effect-conformance check — filesystem delta vs the tri-state annotation.**
- Correlate the tool for the turn: name from the request-frame `params.name`; the most-recent
  `annotation_snapshot` with `source_seq < request_seq` (mirror `annotations.py:232`); look up by name.
  **No per-turn helper exists — C4 writes the correlation.**
- Read each hint's declared-state (`declared-true` / `declared-false` / `not-declared` /
  `declared-non-boolean`). **Spec defaults appear nowhere; absent stays `not-declared`.**
- The rule:
  - `readOnlyHint` **declared-true** + **non-empty delta** → **FAIL** (`kind="effect"`), naming the
    annotation *and* the observed `FieldDiff` paths.
  - **not-declared** / `annotation_gap` / **declared-non-boolean** → **UNVERIFIED** (*an absent contract
    is not a permissive one*).
  - `readOnlyHint` **declared-false** + mutation → **PASS**.
- **Result-equivalence and effect-conformance decide INDEPENDENTLY**, then reduce (M2). An un-annotated
  tool is UNVERIFIED for effect-conformance while result-equivalence still yields its own PASS/FAIL.

**M5 · Propagate every C3 status honestly — the NOT_VERIFIABLE hole.**
| C3 status | → Verdict |
|---|---|
| REPLAYED | PASS/FAIL/UNVERIFIED per M3+M4 |
| UNVERIFIED (any cause incl. `UNANSWERED_TARGET`, `UNRESTORABLE_SNAPSHOT_FAILED`) | **UNVERIFIED**, cause verbatim |
| NOT_VERIFIABLE (absent handle) | **UNVERIFIED**, **distinct cause** |
| determinism NOT_REPLAYABLE | **UNVERIFIED** |

🔴 **`NOT_VERIFIABLE` (un-snapshotted turn) must NOT fall through as PASS.** A2 has no PASS/FAIL for a
turn it never snapshotted. **Reuse `report.canonical_cause`** (total, never-empty) for UNVERIFIED causes
so failure-corpus buckets stay consistent. **Never `UnrestorableCause(cause_string)`** — the gate's
`UNRESTORABLE_SNAPSHOT_FAILED` is not an enum member and it throws.

**M6 · `belay verify <trace>` CLI + the verdict report.**
Add `belay verify` (distinct from `belay replay`, which stays coverage-only and honest). Reuse
`read_trace` / replay plumbing / `--manifest-dir` / `--server` / `--replays` / `--turn`. Report per
turn: the reduced Status, the `kind` that drove it, and the concrete grounding (the diff, or the
annotation+paths). Aggregate: PASS/FAIL/UNVERIFIED counts and the FAIL list with causes.
> **Show BOTH sub-verdicts, not just the reduced one.** When result-equivalence is PASS but
> effect-conformance is FAIL (a `readOnlyHint: true` tool that *did* return the recorded reply), the
> reduced status is FAIL — but *"why did this FAIL?"* is only answerable if the report shows the two
> sub-checks and which one drove the reduction. A reduced status with no visible sub-verdicts is a
> verdict a user cannot act on.
> **`--no-claim-axis`** (A3's refutation, lands with C8) is **not wired now** — but shape verdict
> aggregation as a clean per-axis toggle so it slots in without reshaping.

**M7 · Zero LLM, provable.** No model import, no model call, anywhere in C4. A test greps the C4 modules
for any model/inference reference and asserts none. *This is the capability's whole positioning.*

**M8 · Honest coverage statement.** The verdict report and README state plainly: **C4 verifies what
re-execution can observe** — filesystem effects, result-equivalence, protocol errors. It does **not**
verify successful network egress under allow-all (see S1), and its PASS means the trace reproduces,
not that the agent was correct.

### Should-have

**S1 · `openWorldHint` via denials under deny-all.** Un-`DEVNULL` the replay server's stderr
(`client.py:328`) and run `DenialCapture`, so a tool attempting egress during a **deny-all** replay
produces a denial → a grounded `openWorldHint` conformance signal (`kind="effect"`):
- `openWorldHint` **declared-false** + an observed egress **denial** → **FAIL** (it touched the network).
- **not-declared** → **UNVERIFIED** for this dimension.
> **This catches DENIED egress only** (deny-all replay). **Successful egress under allow-all is NOT
> observed and must never be claimed verified** (M8). If the stderr plumbing proves fiddly or flaky,
> **fall back to an honest UNVERIFIED for the network dimension** — never fake it. *A decision at the
> Phase-6 checkpoint, not a blocker for M1–M6.*

**S2 · Trace-infidelity corpus cases.** Every FAIL is a labeled case (pre-state handle, recorded
result, observed result) — the C6 corpus seed. Emit them in a shape C6 can ingest; do not build the
corpus store (C6).

**S3 · `incoherence` surfaced.** `annotations.py` already flags a tool declaring `destructiveHint`/
`idempotentHint` alongside `readOnlyHint: true`. Surface it as a fact on the effect-conformance verdict;
do not resolve it.

### Nice-to-have

**N1 · Whole-trace verify** (default) vs `--turn N`. Recommend default whole-trace, reusing C3's
per-turn loop.

---

## Technical Considerations

**Composes (verified in source):** `engine.replay_turn` (result-equivalence + delta),
`determinism.classify_determinism` (the FAIL gate), `reader.read_trace`, `persist.load_snapshot`,
`annotations.derive_annotations` (+ C4's own per-turn correlation), `bth1.FieldDiff` (the delta),
`report.canonical_cause` (cause buckets), `launch.DenialCapture` (S1), `declared.*` (the tri-state),
`cli` (the `belay verify` surface).

**Verdict axis: this IS A2.** C4 is the first code on any axis. It changes what Belay *claims*: a PASS
is now on the record. The honesty contract stops being documentation and becomes the reduction (M2) and
the coverage statement (M8).

**Guardrails.** No framework (verifies a recorded call). **No LLM — M7 proves it.** No egress (replay is
sandboxed, deny-all default). UNVERIFIED-never-PASS is structural (M2). Never-claim-coverage is M8+S1's
honest bound. Test-first. ✅

---

## Risks & Open Questions

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| **R-C4-1** | **A nondeterministic divergence rendered as FAIL.** The single most likely C4 defect — it trains users to ignore the verifier. | **High (trust)** | M3's mandatory determinism gate; a test asserts clock→UNVERIFIED, and a positive control asserts a real infidelity→FAIL so the gate isn't vacuously passing everything. |
| **R5** | *Roadmap.* **Over-claiming what A2 proves.** A2 verifies fidelity, not correctness; the network gap invites implying egress coverage we lack. | **Fatal (trust)** | The "what PASS means" statement (top), M8's coverage statement, S1's explicit deny-all-only bound. **The demo's A2-PASS-on-the-cheat is the proof we understand this.** |
| **R-C4-2** | **NOT_VERIFIABLE / absent handle falls through to PASS.** The false-pass hole. | **Fatal** | M5; a test asserts an un-snapshotted turn is UNVERIFIED, never counted as passed. |
| **R-C4-3** | **The Verdict model can't hold A1/A3 later**, forcing a reshape. | Med | M1/M2 designed for N-axis worst-wins now; a placeholder A1 verdict in a reduction test proves it composes. |
| **R7** | *Roadmap.* UNVERIFIED dominates. C3 already measures the rate; C4 turns each into a verdict. | High | The verdict report keeps UNVERIFIED a first-class outcome with a named cause — never hidden, never spun as PASS. |
| **R-C4-4** | **S1's stderr capture is flaky** (denial parsing from child stderr is timing/format sensitive — C2 already marks denials `inferred`). | Med | S1 is a SHOULD with an honest-UNVERIFIED fallback. Do not let a flaky egress check destabilize the deterministic M1–M6 core. |

**Open questions:**
1. **`belay verify` vs `belay replay --verify`?** Recommend **`belay verify`** — the verb is the
   capability; `belay replay` stays coverage-only and honest.
2. **Does A2 ever emit WARN in v0?** Recommend **model WARN in the type** (A1/A3 need it) but **A2 v0
   emits only PASS/FAIL/UNVERIFIED** unless a concrete case appears (`bth1`'s sparse-file inflation is a
   candidate but not required by the acceptance list).
3. **S1 in v0 or deferred?** Recommend **attempt it** (modest, real `openWorldHint` signal) with the
   honest-UNVERIFIED fallback decided at the Phase-6 checkpoint.

---

## Out of Scope

- **A1 / invariants (C5)** — the axis that catches *cheating*. C4 is A2 only. The reduction is shaped
  for A1 but A1 is not built here.
- **A3 / claim re-derivation (C8)** and **`--no-claim-axis`** — the model toggles cleanly for it; not
  wired now.
- **The failure corpus store (C6)** — C4 emits ingestable FAIL cases (S2); it does not persist them.
- **Successful network egress under allow-all** — **not observable; explicitly not verified** (M8).
- **OS-process exit codes** — an MCP tool's error is `isError`/`error` in the reply (covered by
  result-equivalence); the server process exit is C3's `UNANSWERED_TARGET`.
- **Any LLM-assisted check** — that is A3, and it can never emit PASS regardless.
- **Non-macOS, non-stdio.**

---

## Acceptance Criteria (test-first)

From `CAPABILITY_ROADMAP.md` C4, plus the traps the map surfaced:

| # | Criterion |
|---|---|
| **A1** | A fake server injected with a **fabricated result** → **FAIL** with the exact recorded-vs-observed diff in the message. |
| **A2** | A **clean, deterministic** turn → **PASS**. |
| **A3** | A **nondeterministic** tool (clock/random) → **UNVERIFIED**, not FAIL and not PASS. |
| **A4** | A **`readOnlyHint: true`** tool that writes a file → **FAIL** naming the annotation and the observed write. |
| **A5** | An **un-annotated** tool → **UNVERIFIED** for effect-conformance, while result-equivalence decides independently (a clean reply still yields its own PASS). |
| **A6** | An **unrestorable / un-snapshotted** pre-state → **UNVERIFIED**, asserted explicitly — never PASS. |
| **A7** | 🔴 **The reduction never turns UNVERIFIED into PASS** — a turn with one UNVERIFIED sub-check and one PASS sub-check reduces to **UNVERIFIED** (structural test). |
| **A8** | 🔴 **Zero LLM** — a test greps C4's modules and asserts no model/inference import or call. |
| **A9** | **PASS-on-the-cheat, made visible:** the fixture's **restored pre-state visibly contains the tampering** — e.g. a `tests/` file the agent weakened is *in the snapshot* — and the recorded tool reply ("3 passed") reproduces on replay against that weakened state. A2 returns **PASS**, correctly, because the weakened state *is* its ground truth. The test asserts PASS **and** documents that only A1 (C5) catches this. *(The non-redundancy proof, in code, before C5 exists. A test that passes any clean turn does NOT satisfy A9 — the pre-state must encode the cheat.)* |
| **A10** | C1+C2+C3 suites pass **untouched** (290). |
| **A11** *(S1)* | `openWorldHint: false` + an observed egress denial under deny-all → **FAIL**; not-declared → UNVERIFIED. *(Or, if S1 falls back: the network dimension is honestly UNVERIFIED and a test asserts we do not claim it.)* |

All: **deterministic, no network** (fake MCP servers), CI-runnable (macOS).

> **Explicitly NOT asserted (would over-claim):** that a PASS means the agent behaved correctly; that
> successful egress under allow-all is verified; that A2 catches cheating.
