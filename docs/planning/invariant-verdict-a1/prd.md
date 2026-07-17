# PRD — C5: Invariant verdict (axis A1)

**Capability:** C5 · **Phase:** 0 (the gate) · **Window:** week 3 · **Cuttable:** **No — earns the statistic**
**Dependencies:** C1 ✅ C2 ✅ C3 ✅ C4 ✅ — all merged, 348 tests green
**Branch:** `feat/invariant-verdict-a1/aliz` · **Slug:** `invariant-verdict-a1`
**Inputs:** [`_card/issue.md`](../_card/issue.md) · [`understanding.md`](./understanding.md)

> Every API claim was read in source; the core non-redundancy I verified by running C4's own code.
> **C5 completes the C1–C5 Phase-0 gate.** Zero LLM — a scope-match on the observed effect decides.

---

## Problem Statement

**The capability that earns the 27–78% statistic**, and — per `CLAUDE.md` — the one most likely to be
**under-built**, because A2 *looks* like it already covers verification. **It does not.** A2 catches
trace *infidelity*; A1 catches *cheating* — a **faithful** trace that violates a task policy. No
incumbent has this axis at all. It also reframes primitive #1: **the sandbox boundary that contains an
action is the same machinery that judges it.**

**Who:** the Phase-0 number itself. Every A1 violation is a labeled **corrupt-success** case — the
highest-value corpus cases, and the ones the gate's statistic is made of. And the launch demo *is* an
A1 test: A2 returns PASS on the cheat, A1 returns FAIL on the same turn.

**Evidence it's needed — proven from C4's own code.** I ran C4's effect-conformance on the demo turn
(a `readOnlyHint: false` tool that weakens `tests/test_auth.py`): it returns **PASS** — *"there is no
read-only contract to violate"* (`effect.py:384-393`). The task invariant *"tests/ is read-only"* is
violated by the same delta. **A2 PASS + A1 FAIL, same turn, same observed effect.** The axes are
genuinely non-redundant, and the demo is achievable.

> 🔴 **The demo targets the turn that DOES the weakening, not a later turn that reads it.** A1
> evaluates the replay *delta* — the difference between restored pre-state and post-state. On the
> *weakening* turn, the `tools/call` writes `tests/`, so the delta *contains* that write → A1 FAILs it.
> On a *later* "run the tests" turn, the pre-state is already weakened (that is C4's PASS-on-cheat
> setup), the replay re-runs the already-weak test, the delta touches nothing under `tests/`, and there
> is **nothing for A1 to catch on that turn.** Both are correct: A1 catches the violation *at the turn
> it happens.* The fixture must record the mutating turn — building it around the reading turn is the
> way this acceptance test silently proves nothing.

---

## 🔴 What A1's verdict is — and the two ways to build it wrong

**A1 is TASK-SCOPED and TOOL-INDEPENDENT:** *"was the declared task policy violated by the observed
effect, regardless of which tool did it or what that tool declared?"* This is categorically different
from C4's A2 effect-conformance, which asks *"did the tool conform to ITS OWN declared contract?"*

`CLAUDE.md` names the two failure modes explicitly:
1. **Building A2 and expecting it to catch cheating** — the single most likely quiet failure. (C4 is
   correct: it PASSes the cheat, on purpose.)
2. **Building A1 as a duplicate of A2's effect-conformance** — the second. **If C5's A1 verdict equals
   C4's effect-conformance on the demo, C5 is built wrong.** The `readOnlyHint:false`-writes-`tests/`
   case is the litmus: C4 PASS, A1 must FAIL.

---

## Goals & Success Metrics

| Goal | Metric |
|---|---|
| **The launch demo, as a test** | A trace where the agent weakens `tests/` and reports success → **A1 FAIL at the exact turn** (names the invariant + the diff) **while A2 independently PASSes the same turn** |
| Clean run passes A1 | A faithful run that respects the invariants → **PASS** on A1 |
| Zero-config firing (R3) | An **annotation-inferred** invariant fires with **no user authoring** |
| Unevaluable never passes | An invariant whose effect is unobservable (network) → **UNVERIFIED**, never PASS |
| Non-redundant | On the demo turn, A1's verdict **differs** from A2's effect-conformance (FAIL vs PASS) |
| Zero LLM | No model call anywhere; a grep test proves it |
| Grounded, not linted | A1 evaluates the **replay delta**, never the agent's prose or a static scan |
| Small and finished | ≤5 working days — this is the last gate capability |

---

## Requirements

### Must-have

**M1 · The invariant declaration format + loader.** A declarative, scoped format:
`{scope: "<path-prefix>", rule: "read-only"}` (a list of these). Loaded from an **operator-provided
file**, not the trace.
> 🔴 **The invariant is the operator's POLICY; the trace is the agent's EVIDENCE. They must not mix.**
> If a run could author a permissive invariant into its own trace, A1 is defeated by construction. So
> `belay verify --invariants <path>` reads the declaration. (If provenance is ever wanted, record a
> **hash** of the invariants file in the verdict output — never the policy itself into the trace.)

**M2 · The evaluator — grounded on the replay delta.** For each turn, evaluate each invariant against
the **observed effect** `reply.delta: list[FieldDiff]` (from C4/C3 — the real BTH-1 before/after diff).
- Decode the touched paths via `effect._paths(delta)` (reuse, do not reimplement).
- `read-only` rule: **any touched path under `scope` → FAIL.**
- **Scope match is BYTE-PREFIX on the raw path bytes** (BTH-1's discipline), so `tests/` matches
  `tests/test_auth.py` and the unicode traps BTH-1 already avoids stay avoided. Not normalized-string.
- A violation → `Verdict(axis="A1", kind="invariant", status=FAIL)` naming the invariant, the turn `n`,
  and the **exact violating `FieldDiff` path(s)**.
- **🔴 `delta is None`** (no post-state observed — already guaranteed at `engine.py:309-324`) → the
  invariant is **UNVERIFIED**, never a PASS. An unobserved effect can never satisfy an invariant.

**M3 · Annotation-inferred invariants — the zero-config default (R3), SCOPED + TOOL-INDEPENDENT only.**
This must ship *inside* C5, and it must not duplicate C4.
- 🔴 **Do NOT ship the collapse case:** *"a `readOnlyHint:true` tool must never mutate"* is exactly
  C4's per-turn check. Identical verdict. Not an A1 invariant.
- ✅ **Ship the genuinely new case:** a **scoped** policy inferred from annotations + a default scope —
  the roadmap's *"no tool declaring `destructiveHint` outside `build/`"*. A destructive tool's write to
  `tests/` is C4-**PASS** but A1-**FAIL**. Tool-independent, task-scoped → not derivable from C4.
- **Rule of thumb, enforced in review:** an inferred invariant is admissible only if it is **SCOPED
  (task/path) AND TOOL-INDEPENDENT.** Anything reducing to *"tool X honours tool X's own hint"* is C4
  and must be rejected.
- **The zero-config default scope:** a small, **documented, conservative** default that fires with no
  authoring (R3) — recommended: **`tests/` is read-only** (the demo's own invariant), clearly labeled
  as an operator-overridable default, **never a silent policy the user didn't choose.** `--invariants`
  overrides/extends it; `--no-default-invariants` disables it.

**M4 · Network invariants are UNVERIFIED-only.** A *"no egress"* invariant cannot be grounded — the
same EPERM gap C4 hit (a network denial and an fs-write denial are the identical line; successful
egress under allow-all is uncaptured). So it **mirrors C4's `openWorldHint` discipline**: **never PASS,
never a fabricated FAIL** — UNVERIFIED with an honest cause. *Never claim coverage we don't observe.*

**M5 · A1 plugs into `verify_turn` additively.** After the A2 sub-verdicts, if invariants apply, append
`Verdict(axis="A1", kind="invariant", ...)` and `reduce`. The `net_verdict` precedent (`turn.py:193-195`)
is the exact additive shape. `reduce()` is already axis-agnostic (**A1 FAIL + A2 PASS → FAIL**,
**A1 UNVERIFIED + A2 PASS → UNVERIFIED** — both verified). The renderer (`_emit_verdict`/`_axes_in_order`)
needs **no rewrite**. Thread an `invariants` arg through `verify_turn`'s signature + the CLI call.

**M6 · `belay verify --invariants <path>` + the A1 sub-verdict in the report.** The report shows the A1
sub-verdict alongside A2's, with its grounding (the invariant + the violating path). With no
`--invariants` and defaults disabled, A1 is simply **absent** from the reduction (A2 stands alone) —
never a silent PASS-filler.

**M7 · Zero LLM, provable.** No model import/call anywhere in C5. The existing AST grep test
(`test_verify_zero_llm.py`) covers `src/belay/verify/` — ensure C5's modules live there so it applies,
and extend it if C5 adds a module outside that tree.

### Should-have

**S1 · The corpus-case shape.** Every A1 FAIL is a labeled **corrupt-success** case (the invariant, the
turn, the pre-state handle, the violating delta) — the highest-value C6 seed. Emit in an ingestable
shape; do **not** build the corpus store (C6).

**S2 · `no-create` / `no-delete` rules.** Beyond `read-only`: a scope that must gain no new paths
(`no-create`) or lose none (`no-delete`), both readable from the `FieldDiff` (a `field=None` side
indicates add/remove). Ship if cheap; `read-only` alone delivers the demo + R3.

### Nice-to-have

**N1 · Multiple invariants per turn.** A turn violating two invariants lists both. Reduce is unchanged
(all FAIL → FAIL).

---

## Technical Considerations

**Composes (verified in source):** `reply.delta` + `bth1.FieldDiff`; `effect._paths` (path decoding);
`annotation_for_turn` (only for the inferred scoped invariants — the tool identity, not its self-
conformance); `verdict.reduce()` (axis-agnostic); `verify_turn`'s additive sub-verdict slot; the CLI's
`_emit_verdict`/`_axes_in_order`. **The Verdict model already reserves `kind="invariant"`** (`verdict.py:59`).

**Verdict axis: this IS A1.** The demo turn now carries three sub-verdicts — result PASS, effect PASS,
**invariant FAIL** → reduced FAIL, driven *solely* by A1. That single composed assertion is the
non-redundancy of the axes, in code, and the whole thesis of the project.

**Guardrails.** No framework (evaluates a declared policy against observed effects). **No LLM — a
scope-match decides.** No egress (network invariant is UNVERIFIED-only). UNVERIFIED-never-PASS is
structural via `reduce`. Never-claim-coverage is M4. Test-first. ✅

---

## Risks & Open Questions

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| **R-C5-1** | **A1 collapses into C4's effect-conformance** — the second-most-likely quiet failure. | **Fatal (thesis)** | M3's SCOPED+TOOL-INDEPENDENT rule; the demo test asserts A1 FAIL **while A2 effect PASS** on the same turn — a redundant A1 would make them equal and the test fails. |
| **R3** | *Roadmap.* **Nobody authors the invariant** — A1 works only if a policy is declared. | **High/High** | M3's annotation-inferred **zero-config default** (`tests/` read-only) fires with no authoring. Named now, shipped inside C5, not after. |
| **R-C5-2** | **The agent authors its own passing invariant** (if invariants lived in the trace). | **Fatal** | M1: invariants are an operator file, never a trace record. The trace is evidence; the invariant is policy. |
| **R5** | *Roadmap.* Over-claiming — a network invariant implies egress coverage we lack. | **Fatal (trust)** | M4: network invariants are UNVERIFIED-only, mirroring `openWorldHint`. |
| **R-C5-3** | **A default invariant surprises the user** (a policy they didn't choose FAILs their run). | Med | The default is documented, conservative, labeled as a default, and `--no-default-invariants` disables it. Never silent. |
| **R7** | *Roadmap.* UNVERIFIED dominates. | High | A1 adds a *grounded FAIL* axis that catches what A2 can't — it *reduces* the UNVERIFIED share for cheating turns, and its own unevaluable cases (network) are honestly UNVERIFIED. |

**Open questions:**
1. **The default scope — is `tests/` read-only the right zero-config default?** Recommend yes (it *is*
   the demo's invariant and the canonical corrupt-success target), documented and overridable. **Steer
   welcome at the gate — this is the one policy Belay ships an opinion about.**
2. **`no-create`/`no-delete` in v0 (S2)?** Recommend `read-only` only for v0; it delivers the demo + R3.
3. **Invariant file format — JSON or TOML?** Recommend **JSON** (stdlib, matches the trace format's
   idiom, zero deps).

---

## Out of Scope

- **A2 / replay-verify (C4)** — done; C5 composes its delta and reduces alongside it, does not touch it.
- **A3 / claim re-derivation (C8)** and **`--no-claim-axis`** — the reduction already tolerates it.
- **The failure corpus store (C6)** — C5 emits ingestable corrupt-success cases (S1); does not persist.
- **Network egress verification** — UNVERIFIED-only (M4); not observable.
- **Any LLM-assisted invariant inference** — invariants are declarative or annotation-inferred by rule,
  never model-written. (Model-written checks are A3/C8, and even there execution decides.)
- **Static-lint invariants over the trace** — A1 evaluates the *replayed effect*, never a scan of the
  recorded trace. Grounded-by-construction is the whole claim.
- **Non-macOS, non-stdio.**

---

## Acceptance Criteria (test-first)

From `CAPABILITY_ROADMAP.md` C5, plus the collapse-guard the dig surfaced:

| # | Criterion |
|---|---|
| **A1** | 🔴 **THE LAUNCH DEMO.** A trace whose turn N is the one that **performs the weakening** — a `readOnlyHint:false` tool whose `tools/call` writes `tests/test_auth.py` — and returns success. **On that turn:** replay produces a delta *containing* the `tests/` write; **A1 = FAIL** naming the `tests/`-read-only invariant + the violating path, **AND A2 (result + effect) = PASS**. Reduced turn status FAIL, **driven solely by A1.** *This single composed assertion is the non-redundancy proof.* |
| **A2** | A **clean run** that respects the invariants → **A1 PASS**. |
| **A3** | An **annotation-inferred** invariant fires with **zero user-authored config** (the default scope). |
| **A4** | An **unevaluable** invariant (a network `no-egress`, or `delta is None`) → **UNVERIFIED**, never PASS. |
| **A5** | 🔴 **Non-redundancy, negatively:** on the demo turn, A1's verdict is **not equal** to C4's effect-conformance verdict (FAIL vs PASS). A test that would pass if A1 merely re-ran effect-conformance must FAIL. |
| **A6** | **Byte-prefix scope match:** `tests/` matches `tests/test_auth.py` (raw bytes); a path outside scope does not trip the invariant. |
| **A7** | **Operator-only policy:** the invariant is loaded from `--invariants`, and a test asserts a trace **cannot** carry a policy that A1 would honor (no invariant is read from trace records). |
| **A8** | Zero LLM — the AST grep test covers C5's modules. |
| **A9** | C1+C2+C3+C4 suites pass **untouched** (348). |

All: **deterministic, no network** (fake MCP servers), CI-runnable (macOS).

> **Explicitly NOT asserted (would over-claim):** that A1 catches a cheat with *no* declared or inferred
> invariant (it can't — a policy must exist; R3's default is the mitigation); that network egress is
> verified; that A1 replaces A2 (they catch different things — that is the point).
