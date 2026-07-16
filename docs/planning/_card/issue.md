# Card: C4 — Replay-verify (axis A2)

## Source

**No GitHub issue.** Tracker empty. `id` is the slug `replay-verify-a2`.
Authoritative source: `docs/technical/CAPABILITY_ROADMAP.md` §C4, quoted verbatim below. No inline
brief — C4 is fully specified there; paraphrasing would introduce drift.

- Branch: `feat/replay-verify-a2/aliz` · Worktree: `.claude/worktrees/feat-replay-verify-a2`
- Base: `origin/master` @ 48dcf6e (C1+C2+C3 merged, 290 tests green)

## C4, verbatim

> ## C4. Replay-verify — axis A2 · weeks 2–3
>
> **Why it is moat.** The first grounded verdict, and the answer to the question no incumbent
> answers. Langfuse/Phoenix/LangSmith/Braintrust record and (optionally) LLM-judge score; none
> re-execute a tool call in a sandbox to check real state. There is no LLM anywhere in this
> capability — that is the point.
>
> **What we build.** Two deterministic checks per turn:
> - **Result equivalence.** Restore pre-state, re-invoke, diff observed result vs recorded result.
>   Divergence = the trace does not reproduce = **FAIL** with a concrete diff (`kind="replay"`). A
>   tool classified nondeterministic by C3 yields **UNVERIFIED**, never PASS and never a false FAIL.
> - **Effect conformance.** Snapshot state before/after the replayed call, compute the real delta
>   (files touched, network egress, exit codes), and check it against the tool's **declared MCP
>   annotations** plus the sandbox policy. A tool declaring `readOnlyHint: true` that mutates the
>   filesystem is a **grounded FAIL** with zero LLM involvement — a verdict axis that exists only
>   because we chose the MCP wedge. A tool that declares *no* annotations yields `unverified` for
>   this check (an absent contract is not a permissive one).
> - A `Verdict` model (axis, kind, status, observed, expected, message) and the reduction rule
>   (worst-status-wins across A1/A2).
>
> **Acceptance (test-first):**
> - A fake server injected with a fabricated result yields **FAIL** with the exact recorded-vs-
>   observed diff in the message.
> - A clean turn yields **PASS**.
> - A nondeterministic tool yields **UNVERIFIED**, not FAIL and not PASS.
> - A `readOnlyHint: true` tool that writes a file yields **FAIL** naming the annotation and the
>   observed write.
> - An un-annotated tool yields **UNVERIFIED** for effect-conformance while result-equivalence still
>   decides independently.
> - A turn with an unrestorable pre-state yields **UNVERIFIED** — asserted explicitly, because this
>   is the "never a false pass" contract in code.
> - Deterministic, no network.
>
> **Eval data captured:** every divergence is a labeled **trace-infidelity** case in the corpus,
> with its pre-state, recorded result, and observed result — a replayable regression forever.
>
> **Dependencies:** C1, C2, C3.

## 🔴 The load-bearing warning C4 must NOT violate (CLAUDE.md)

> **A2 catches trace infidelity — fabricated/tampered/nondeterministic results. A2 CANNOT catch a
> cheating agent, because a cheater's trace is faithful.** Replay restores the recorded pre-state
> (already containing the weakened test), re-invokes, observes the same result, and returns **PASS —
> correctly**. Only a declared invariant (A1/C5) catches corrupt success. **Building A2 and
> expecting it to catch cheating is the single most likely way this project fails quietly.**

C4's PASS means "the trace reproduces", NEVER "the agent did the right thing". The docs/verdict
messages must say exactly that and no more.

## What C3 (+C1/C2) hands C4 — to compose, not rebuild

**C3 replay engine (`src/belay/replay/`):**
- `engine.replay_turn(records, n, *, server_command, manifest_dir, ...)` -> outcome with
  `status` (replayed/unverified/not-verifiable), `cause`, `result_equivalence` (equal/diverged/None),
  `recorded_reply`, `replayed_reply`, `delta` (list[FieldDiff]), version fields.
- `determinism.classify_determinism(...)` -> DETERMINISTIC / NONDETERMINISTIC / NOT_REPLAYABLE + axis.
- `reader.read_trace`, `persist.load_snapshot`, `report` (the UNVERIFIED-rate reporter).

**C1/C2:**
- `annotations` / `declared` — the **tri-state** annotation snapshot (declared-true / declared-false /
  not-declared) that effect-conformance checks against. **Absent ≠ false.**
- `bth1.diff_records` -> `FieldDiff(path, field, left, right)` — the state delta primitive.
- `sandbox` — the network policy fact recorded per turn (C2's `network_policy` record); DenialCapture.
- `substrate` — the 18-cause taxonomy; `unrestorable` pre-state must propagate to UNVERIFIED.

## Related PRs
- #1 C1, #2 docs, #3 C2, #4 C3 — all merged.
