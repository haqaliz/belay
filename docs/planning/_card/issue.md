# Card: C3 — Deterministic replay

## Source

**No GitHub issue.** Tracker is empty. `id` is the slug `deterministic-replay`.
**The authoritative source is `docs/technical/CAPABILITY_ROADMAP.md` §C3**, quoted verbatim below.
No inline brief was authored — C3 is fully specified there, and paraphrasing would introduce drift.

- Branch: `feat/deterministic-replay/aliz`
- Worktree: `.claude/worktrees/feat-deterministic-replay`
- Base: `origin/master` @ 521bc0a (C1 + C2 merged, 250 tests green)

## C3, verbatim

> ## C3. Deterministic replay · week 2
>
> **Why it is moat.** This is the durable core. A stronger base model writes better checks and
> cleaner re-derivations, and makes Belay *sharper*; it never makes deterministic replay redundant.
> A judge's guess gets cheaper to fool every year — a re-executed diff does not. Replay is also what
> makes the trace *useful* rather than merely recorded, which is precisely the line between us and
> Langfuse/Phoenix.
>
> **What we build:**
> - `belay replay <trace> [--turn N]`: restore the recorded pre-state (C2), re-invoke the exact
>   recorded `tools/call` against the real MCP server, capture the observed result and the observed
>   state delta.
> - Replay is **side-effect-contained by construction** — it runs in the sandbox, against a restored
>   copy, never against live state.
> - Nondeterminism is *detected, not hidden*: replaying a turn N times and observing divergent
>   results marks the tool nondeterministic in the trace. That marking is an input to C4, not an
>   excuse.
> - Whole-trajectory replay (`--from`, `--to`) for debugging, regression, and audit.
>
> **Acceptance (test-first):**
> - Replaying a clean recorded run reproduces every result with 100% result-equivalence.
> - Replaying a turn whose pre-state is unrestorable yields `unverified`, never a result.
> - A deliberately nondeterministic fake tool (clock/random) is detected as nondeterministic across
>   repeated replays rather than reported as a divergence.
> - Replay never mutates the original trace or live state (asserted, not assumed).
> - Deterministic, no network (fake MCP servers), runs in CI.
>
> **Eval data captured:** per-tool determinism classification — a reference distribution that tells
> us which tools are verifiable at all, and feeds the UNVERIFIED-rate explanation.
>
> **Dependencies:** C1, C2.

## What C1 + C2 shipped that C3 composes

**C1 (PR #1):**
- `proxy.py` — byte-transparent pump; `run(command, capture, before_frame)`; never imports `json`
- `trace.py` — append-only JSONL `TraceWriter`, extensible record kinds, `state_handle` per frame
- `index.py` — `(direction, id)` correlation; `tools/call` as a derived index
- `annotations.py` / `declared.py` — the four-state declared/not-declared encoding
- `hashing.py` — sha256 + `belay/jcs-v1` canonical form
- `errors.py` — protocol-error vs `isError` classification
- `connection.py` — per-call resolved protocol version / client identity

**C2 (PR #3):**
- `sandbox/seatbelt.py` — `build_profile`, `run(...)`, `NetworkPolicy.{deny_all,allow_all,allow_ports}`
- `sandbox/launch.py` — the composition root; spawns the server under `sandbox-exec`
- `sandbox/gate.py` — the `before_frame` turn gate; snapshots the exact pre-state
- `sandbox/scope.py` — `default_scope`: write scope (workspace + `$TMPDIR`) vs **snapshot scope
  (workspace only)**
- `snapshot/clone.py` — `snapshot(root, dest)`, `restore(snap, dest, repairs=...)` via `clonefile`
- `snapshot/bth1.py` — `scan_tree`, `hash_tree`, `diff_records` → `FieldDiff(path, field, left, right)`
- `snapshot/substrate.py` — `take_snapshot`, `guarded_restore`, `guard`, the **18 named causes**
  (9 raised, 9 deferred, 0 unaccounted), and `absent_handle` / `present_handle` /
  `unrestorable_handle`
- `cli.py` — `belay sandbox check`

## Related PRs

- **#1** C1: MCP proxy trace capture (merged)
- **#2** Correct three claims the docs now get wrong (merged)
- **#3** C2: Sandbox + execution boundaries (merged) — **includes `UNRESTORABLE_CONCURRENT_TURN`,
  which directly bounds what C3 can replay.**
