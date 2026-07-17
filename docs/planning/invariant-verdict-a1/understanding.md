# C5 — Invariant verdict (axis A1): Understanding note (Phase 2)

**Status:** pre-PRD. The core non-redundancy and every API claim were **read in source** and I
verified the decisive one myself. **Base:** master @ ddfed4b — C1-C4 merged, 348 tests green.
**Source:** `docs/planning/_card/issue.md` (quotes `CAPABILITY_ROADMAP.md` §C5 verbatim).
**This is the FINAL capability of the C1–C5 Phase-0 gate.**

---

## 1. What the work is really asking

**The capability that earns the 27–78% statistic**, and — per `CLAUDE.md` — the one most likely to be
**under-built**, because A2 *looks* like it already covers verification. It does not. A2 catches
trace **infidelity**; A1 catches **cheating** — a *faithful* trace that violates a task policy. No
incumbent has this axis. It also reframes primitive #1: **the sandbox boundary that contains an
action is the same machinery that judges it.**

## 2. 🔴 The non-redundancy — PROVEN from real code (not theory)

I ran C4's actual effect-conformance on the launch-demo turn (agent weakens `tests/test_auth.py`):

```
tool declares readOnlyHint:false  -> C4 effect-conformance = PASS   <- effect.py:384-393 verbatim:
                                       "there is no read-only contract to violate"
tool declares destructiveHint:true -> UNVERIFIED
tool un-annotated                  -> UNVERIFIED
```

**None is a FAIL.** The `readOnlyHint:false` case is the cleanest: the tool declared it mutates and it
mutated, so C4 correctly returns **PASS** — while the task invariant *"tests/ is read-only"* is
violated, which **only A1 catches.** Same turn, same `delta`, divergent verdicts. **The demo (A2 PASS +
A1 FAIL) is achievable, and it does not collapse into C4.**

The distinction, precisely:
- **C4 / A2 effect-conformance:** *"did the tool conform to ITS OWN declared contract?"* — per-tool,
  per-turn, **tool-declared**.
- **C5 / A1 invariant:** *"was the TASK-scoped policy violated by the observed effect?"* — **task-scoped,
  tool-independent**, evaluated against the *same delta* but by an *operator-declared* rule.

## 3. 🔴 The two design decisions that keep A1 honest AND non-redundant

### 3a. The invariant is an OPERATOR-PROVIDED FILE, read by `belay verify` — NOT a trace record

The map's sharpest point, and it is load-bearing: **the trace is the agent-produced *evidence*; the
invariant is the *policy the operator holds it to*. Mixing them lets a run author its own passing
invariant.** If the agent could write a permissive invariant into its own trace, A1 is defeated by
construction. So:
- `belay verify --invariants <path>` reads a declaration file (a `{scope, rule}` list).
- `trace.record(kind, ...)` is extensible (`trace.py:262`), so an `"invariant"` KIND is *possible* —
  but C5 must **READ a declaration, not let the trace carry the policy.** If provenance is ever wanted,
  record a **hash** of the invariants file, never the policy itself.

### 3b. An annotation-inferred invariant is NEW only if SCOPED **and** TOOL-INDEPENDENT

The largest redundancy trap in C5 (R3 mitigation must ship, but must not duplicate C4):
- **COLLAPSES into C4 — do NOT ship:** *"a `readOnlyHint:true` tool must never mutate."* That is exactly
  `render_effect_verdict`'s per-turn check applied per turn (`effect.py:354-382`). Identical verdict.
- **GENUINELY NEW — ship:** scoped policies inferred from annotations + a default scope. The roadmap's
  *"no tool declaring `destructiveHint` outside `build/`"* is this: a destructive tool's write to
  `tests/` is **C4-PASS** (it declared it mutates) but **A1-FAIL** (it violated the scope). Tool-
  independent, task-scoped → a verdict **not derivable from C4.**
- **Rule of thumb (from the map):** new only if it is **SCOPED (task/path) AND TOOL-INDEPENDENT.**
  Anything reducing to *"tool X honours tool X's own hint"* is C4.

## 4. The observed effect A1 evaluates against

- **Filesystem — reuse C4's delta.** `replay_turn` → `TurnReply.delta: Optional[list[FieldDiff]]`
  (`engine.py:113`), a real BTH-1 before/after diff. `FieldDiff = (path: bytes, field, left, right)`.
  `effect._paths(delta)` (`effect.py:220-229`) already decodes the distinct touched paths — A1's
  scope-match reuses it. **This is the observed filesystem effect A1 checks a `tests/`-read-only
  invariant against.** Per turn A1 gets: `delta = reply.delta` (already in `verify_turn` at
  `turn.py:185`), the tool name, and `n`.
- **🔴 `delta is None` (no post-state observed) → UNVERIFIED, never `[]`** (`engine.py:309-324`, the
  fix I made in C4's review). So an unobserved effect can never yield a false invariant-PASS. **This
  guarantee carries straight into A1.**
- **🔴 Network — NOT observable. The same EPERM gap C4 hit.** A network-egress denial and an fs-write
  denial are the *identical* EPERM line; `network_policy` records the policy applied, not egress;
  successful egress under allow-all is uncaptured. → **a "no egress" invariant is UNVERIFIED-only** —
  it must mirror C4's `openWorldHint` discipline (`effect.py:258-326`): **never PASS, never a fabricated
  FAIL.** *Never claim coverage we don't observe.*

## 5. Where A1 plugs in — extend `verify_turn` additively

`reduce()` is **axis-agnostic** (reads `status`, never `axis` — `verdict.py:74-82`), verified: **A1 FAIL
+ A2 PASS → FAIL** (the demo), **A1 UNVERIFIED + A2 PASS → UNVERIFIED** (an unevaluable invariant never
lets a PASS through). The `net_verdict` precedent (`turn.py:193-195`) is the exact additive shape:
after the effect verdict, if invariants were provided, append `Verdict(axis="A1", kind="invariant", ...)`
to `sub_verdicts`, then `reduce`. Threads an `invariants` arg through `verify_turn`'s signature
(`turn.py:139`) + the CLI call (`cli.py:508`). The renderer needs **no rewrite** — `_emit_verdict` loops
`_axes_in_order` over A1/A2/A3 (`cli.py:534-547`). The Verdict model **already reserves `kind="invariant"`**
(`verdict.py:59`) — the engine was built for this.

## 6. The launch demo, concretely (the acceptance test)

The one non-obvious choice: **the cheating tool MUST declare `readOnlyHint: false` (≡ `destructiveHint:
true`)** — NOT un-annotated. Un-annotated → C4 effect UNVERIFIED → the turn reduces to UNVERIFIED, not
PASS, and the demo breaks. **The declared-false annotation is load-bearing.**
- Fixture server: one fake MCP tool that (a) declares `readOnlyHint:false` in `tools/list`, (b) on
  `tools/call` weakens a file under `tests/`, (c) returns a fixed success payload. Deterministic, no
  network.
- Invariant `{scope:"tests/", rule:"read-only"}` vs `reply.delta` (paths include `tests/...`) → A1 FAIL.
- Both verdicts on the ONE replay (`turn.py:158`). **The test asserts: result==PASS ∧ effect==PASS (A2
  PASS) AND invariant==FAIL, with the reduced turn status FAIL driven SOLELY by A1.** That single
  assertion *is* the non-redundancy proof — the whole thesis, in code.

## 7. Guardrail check

| Guardrail | C5 |
|---|---|
| No agent framework | ✅ Evaluates a declared policy against observed effects; never authors/drives an agent |
| No LLM judge | ✅ **Zero model calls — scope-match on the delta decides. This is the point.** |
| UNVERIFIED never PASS | ✅ Structural via `reduce`; unevaluable invariant (delta None / network) → UNVERIFIED |
| Never claim coverage we don't observe | ⚠️ **The network invariant is UNVERIFIED-only.** Never imply A1 verifies egress |
| The engine gets better as models improve | ✅ Deterministic scope-match; a better model writes better *tools/policies*, A1's check is unchanged |
| Test-first | ✅ The acceptance bullets become failing tests first |

## 8. What C5 must BUILD vs COMPOSE

**BUILD (new):**
1. The invariant declaration format + a loader (operator-provided file; `{scope, rule}` list).
2. The evaluator: scope-prefix match on `_paths(delta)` + rule → `Verdict(axis="A1", kind="invariant")`,
   FAIL naming the invariant, the turn, and the exact violating paths.
3. **Annotation-inferred SCOPED invariants** (R3 mitigation) — *not* the `readOnlyHint` restatement.
4. `--invariants <path>` flag, threaded through `verify_turn`.
5. The demo fixture + the non-redundancy acceptance test.

**COMPOSE (unchanged):** `reply.delta` + `FieldDiff`; `_paths` decoding; `annotation_for_turn` (only for
inferred invariants); `reduce()`; `verify_turn`'s additive slot; `_emit_verdict`/`_axes_in_order`.

## 9. Collapse risks to police (from the map)

1. **Any inferred invariant reducing to "tool honours its own readOnlyHint" = C4.** Ship only
   scoped + tool-independent ones.
2. **A1 must evaluate against `reply.delta`, never prose or a static lint of the trace.** Grounded by
   construction is the whole claim.
3. **Network "no egress" = UNVERIFIED-only** (mirror `openWorldHint`), or defer it.
4. **`delta is None` → UNVERIFIED, not PASS** (already guaranteed at `engine.py:309-324`).

## 10. Open questions for the PRD

1. **Default scope for annotation-inferred invariants?** The roadmap's example is *"destructiveHint
   outside build/"* — implying a default like *"the workspace is writable except `tests/`"* or a
   convention. What's the zero-config default that fires with no user authoring (R3) yet isn't
   arbitrary? Recommend: a small, documented, conservative default (e.g. `tests/` read-only), clearly
   labeled as a default the operator can override — never a silent policy the user didn't choose.
2. **Invariant rules beyond `read-only`?** v0 recommend `read-only` (scope must not be mutated) — it
   delivers the demo and R3. `no-create` / `no-delete` / `no-egress` (UNVERIFIED) can follow.
3. **`belay verify` with no `--invariants`?** A1 emits nothing (or a single UNVERIFIED "no invariants
   declared")? Recommend: **A1 is simply absent** from the reduction when none are declared (A2 stands
   alone), PLUS the annotation-inferred defaults always run (R3 — zero-config). State this clearly.
4. **Scope match semantics** — path-prefix on raw bytes (matching BTH-1's raw-path discipline), so
   `tests/` matches `tests/test_auth.py`. Confirm byte-prefix, not normalized-string, to avoid the
   unicode traps BTH-1 already avoids.
