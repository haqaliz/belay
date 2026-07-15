# Card: C2 — Sandbox + execution boundaries

## Source

**No GitHub issue.** `gh` is authenticated; `gh issue list` is empty (the tracker has never been
used). `id` is the slug `sandbox-snapshot-restore`.

**The authoritative source is the repo itself**, not a brief: `docs/technical/CAPABILITY_ROADMAP.md`
§C2. That entry is quoted verbatim below. No inline brief was authored, and none is needed — C2 is
fully specified in the roadmap, and inventing a paraphrase would only introduce drift.

- Branch: `feat/sandbox-snapshot-restore/aliz`
- Worktree: `.claude/worktrees/feat-sandbox-snapshot-restore`
- Base: `origin/master` @ 3cc48f5 (C1 merged, 79 tests green)

## C2, verbatim (`docs/technical/CAPABILITY_ROADMAP.md`)

> ## C2. Sandbox + execution boundaries · weeks 1–2
>
> **Why it is moat.** Primitive #1, and the prerequisite for literally every verdict: you cannot
> re-execute a turn without restoring the state it ran against. Containment and verification are the
> same machinery here, which is why the sandbox is not "a feature" — it is the engine's floor.
>
> **⚠️ This is the schedule's critical path.** Snapshot/restore fidelity is the hardest problem in
> the v0 engine, it lands in week 2, and C3/C4/C5 all block on it. Risk **R2** in the roadmap. Start
> with the narrowest restorable substrate that carries the demo (a container filesystem overlay +
> one tool family), and abstract *late*.
>
> **What we build:**
> - A pluggable sandbox seam (`sandbox/` with a `Sandbox` protocol) so containers / gVisor /
>   firejail are swappable. **Ship exactly one** implementation first — the abstraction is earned by
>   the second, not designed for it.
> - Enforced boundaries: filesystem scope, network policy, and per-tool allow/deny. A denied action
>   is contained and *recorded as denied*, never silently dropped.
> - **Snapshot / restore**: a per-turn pre-state handle that can be restored byte-identically. This
>   is what C3 replays against.
> - An explicit, documented **unrestorable** signal. State we cannot restore is not guessed at — it
>   propagates as `UNVERIFIED` all the way to the verdict. This is the first place the honesty
>   contract becomes load-bearing code.
> - A threat model doc: Belay executes untrusted agent actions, so Belay is itself an attack surface
>   (risk R8). We never claim a boundary we don't enforce.
>
> **Acceptance (test-first):**
> - A turn's pre-state snapshot restores byte-identically; a hash of the restored tree equals the
>   hash of the original.
> - An escape attempt (write outside scope, disallowed network egress) is contained AND appears in
>   the trace as a denial.
> - An explicitly unrestorable substrate (e.g. a stateful remote service) yields the `unrestorable`
>   signal, **never** a silent success.
> - Deterministic, no network, runs in CI.
>
> **Eval data captured:** restore-fidelity rate per tool family, and the taxonomy of unrestorable
> substrates — which directly predicts the UNVERIFIED rate (risk R7).
>
> **Dependencies:** C1 (needs a trace to snapshot against).

## What C1 shipped that C2 builds on

- `src/belay/proxy.py` — byte-transparent stdio pump; `run(command, observe=None,
  on_capture_error=None)`; `BoundedPeek`; a defined capture shutdown; never imports `json`.
- `src/belay/trace.py` — append-only JSONL `TraceWriter`, 0o600 via O_EXCL, extensible record
  `kind`s, thread-safe monotonic `seq`. **Already carries `state_handle: {"status": "absent"}` —
  the three-state slot reserved for C2**, deliberately left empty.
- `src/belay/hashing.py` — sha256 + `belay/jcs-v1` canonical form.
- `src/belay/index.py`, `annotations.py`, `declared.py`, `connection.py`, `errors.py` — derived
  indices.
- `docs/technical/TRACE_FORMAT.md` — the schema + the unknown-kind rule.
- `README.md` — the honest coverage statement.

## Related PRs

- **#1** C1: MCP proxy trace capture (merged) — the trace C2 snapshots against.
- **#2** Correct three claims the docs now get wrong (merged) — includes the 2026-07-28 RC note.
