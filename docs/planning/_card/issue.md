# Card: C5 — Invariant verdict (axis A1)

## Source

**No GitHub issue.** Tracker empty. `id` is the slug `invariant-verdict-a1`.
Authoritative source: `docs/technical/CAPABILITY_ROADMAP.md` §C5, quoted verbatim below. No inline
brief — C5 is fully specified there; paraphrasing would introduce drift.

- Branch: `feat/invariant-verdict-a1/aliz` · Worktree: `.claude/worktrees/feat-invariant-verdict-a1`
- Base: `origin/master` @ ddfed4b (C1+C2+C3+C4 merged, 348 tests green)
- **This is the FINAL capability of the C1–C5 Phase-0 gate.**

## C5, verbatim

> ## C5. Invariant verdict — axis A1 · week 3
>
> **Why it is moat.** **This is the capability that earns the 27–78% statistic**, and the one most
> likely to be under-built because A2 *looks* like it already covers verification. It does not. A
> cheating agent's trace is faithful; only a declared invariant catches it, and it catches it
> deterministically, at an exact turn, with no LLM. No incumbent has this axis at all.
>
> This capability also reframes primitive #1: **the sandbox is not just containment, it is a verdict
> axis.** The boundary that contains an action is the same machinery that judges it.
>
> **What we build:**
> - An invariant declaration format: scoped, declarative, versioned with the trace (e.g. *"`tests/`
>   is read-only for this task"*, *"no network egress to non-allowlisted hosts"*, *"no tool declaring
>   `destructiveHint` outside `build/`"*).
> - Evaluation of invariants against the **observed effects of replay** (from C4), not against the
>   agent's prose and not against a static lint of the trace. Grounded by construction.
> - **Annotation-inferred invariants** — the zero-friction default. Every MCP tool's declared
>   annotations *are* an invariant we get for free, with no user authoring. This is the first
>   mitigation of risk **R3** (nobody authors the invariant) and it must ship inside C5, not after it.
> - A violation yields FAIL (`kind="invariant"`) naming the invariant, the turn, and the exact
>   observed effect that broke it.
> - An invariant that cannot be evaluated (effects unobservable for that substrate) yields
>   `unverified` — never a silent pass.
>
> **Acceptance (test-first):**
> - **The launch demo, as a test.** A recorded trace in which the agent weakens a test file and
>   reports success yields **FAIL at the exact turn**, naming the `tests/` read-only invariant and
>   showing the diff — while A2 independently returns PASS on that same turn (asserting the axes are
>   genuinely non-redundant, which is the whole thesis).
> - A clean run yields PASS on A1.
> - An annotation-inferred invariant fires with **zero user-authored config**.
> - An unevaluable invariant yields **UNVERIFIED**, never PASS.
> - Deterministic, no network.
>
> **Eval data captured:** every violation is a labeled **corrupt-success** case — the highest-value
> cases in the corpus, and the ones the Phase-0 number is made of.
>
> **Dependencies:** C1, C2, C3, C4.

## 🔴 THE NON-REDUNDANCY — the whole point, and the easiest thing to get wrong (CLAUDE.md)

> **A2 catches trace infidelity. A2 CANNOT catch a cheating agent, because a cheater's trace is
> faithful.** The agent really did weaken the test; replay restores the recorded pre-state (already
> weakened), re-invokes, observes the same result, returns **PASS — correctly.** Only a declared
> invariant (A1) catches corrupt success. **Building A2 and expecting it to catch cheating is the
> single most likely way this project fails quietly. Building A1 as a duplicate of A2's
> effect-conformance is the second.**

C4's effect-conformance is PER-TOOL, PER-TURN: "did THIS tool conform to ITS OWN declared annotation?"
C5's A1 invariant is TASK-SCOPED, TOOL-INDEPENDENT: "was the TASK policy (`tests/` read-only) violated,
regardless of which tool did it or what that tool declared?" The launch demo turns on this: the agent
weakens `tests/` using a tool that is honestly destructive/un-annotated — C4 says PASS/UNVERIFIED (the
tool conformed / had no contract), but C5's declared `tests/`-read-only invariant FAILs the exact turn.
**If C5's A1 verdict equals C4's effect-conformance on the demo, C5 is built wrong.**

## Reduction: A1 slots into C4's ALREADY-axis-agnostic reduce()

C4's `reduce()` (verify/verdict.py) is worst-status-wins across axes, verified: `A1 FAIL + A2 PASS ->
FAIL`. So the demo (A2 PASS, A1 FAIL) reduces to FAIL. A1 is a new Verdict(axis="A1", kind="invariant").

## What C1–C4 hand C5 — to compose, not rebuild

- **C4 (`src/belay/verify/`):** `Verdict(axis, kind, status, observed, expected, message)`, `Status`,
  `reduce()` (axis-agnostic), `verify_turn` (the composition A1 joins), the delta from `engine.replay_turn`.
- **C1:** `annotations`/`declared` (tri-state; the annotation-inferred invariant source), `bth1.FieldDiff`
  (the observed effect — a path + field), the trace records.
- **C2:** the `network_policy` record + `denial` records (sandbox policy as an invariant axis); `substrate`.
- **C3:** replay observations (the observed effects A1 evaluates against).

## Related PRs
- #1 C1, #2 docs, #3 C2, #4 C3, #5 C4 — all merged.
