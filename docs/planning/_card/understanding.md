# Phase-2 understanding — `subscription-model-client`

**Date:** 2026-08-05 · **Base:** `origin/master` @ `d4c7647` (v0.12.0 + 2 doc commits)
**Baseline confirmed in this worktree:** `uv run pytest` → **1342 passed, 1 skipped, 1 deselected**
(1343/1344 collected).

> **Replaces the predecessor's note.** This file previously held the Phase-2 understanding for
> `feat/under-firing-measurable` (2026-08-03, baseline 1238). That unit merged at `7bcd82b` and
> released v0.12.0; its note is superseded here rather than deleted from history.

---

## What the work is really asking

Not *"write a client"*. The unit exists to **remove the last blocker between Phase 0 and a
denominator**. `entrypoint.py:90` registers two metered providers; Stage 3 died on a daily cap; the
≥50 PROCEED clause counts *instances minted* and is detector-independent. So: no subscription
client → no affordable mint → **R1's quantitative form stays untested indefinitely**.

## Affected area

`eval/` **only**. No `src/belay/` change, no C1–C9 capability, **no verdict on any axis**, no
product surface. The driver is a *consumer* of the engine; a client that needed the engine to
change would be reaching across a boundary.

## What I verified rather than assumed

| Claim | Status |
|---|---|
| `CLAUDE.md`: *"1238 tests"* | **STALE.** Actual: 1342/1/1. Superseded going forward; no published number re-derived |
| Spec: headless subscription auth works (v2.1.220, 2026-07-28) | **Re-confirmed today** on v2.1.221, and additionally from a **scrubbed** `env -i` subprocess — so it does not depend on a Claude Code session |
| Dependencies `quota-circuit-breaker` + `run-accounting` are built | **Confirmed** — `resilience.py:220 classify_error`, accounting wired at `batch.py:72-89`, `checkpoint.py:121` |
| The `Model` seam | `propose_next(list[Message]) -> ToolCall \| Done` (`model.py:46-54`). Template is `anthropic_client.py`: `provider`/`model`/`request_count`/`usage`, `_seen` cursor, count-before-call, absent-never-zero, one-call-per-turn guardrail |
| Registry contains gold patches | **FALSE** — `pool.json`/`selected.json` carry only `base_commit`, `instance_id`, `is_control`, `problem_statement`, `repo`, `task_string`. This killed the first forecast design |

## Contradictions found between the 2026-07-28 spec and reality

The spec predates four things. None invalidate it; all change the build.

1. **`--strict-mcp-config` is unmentioned and required.** Without it the operator's own MCP servers
   are inherited into the oracle — a filesystem path bypassing the proxy, i.e. an **R6 hole**.
2. **`--tools ""` exists** and is a stronger primitive than the denylist the spec implies: an
   allowlist emptied, not an enumeration of what to forbid.
3. **`--bare` is a trap.** It looks like the isolation flag; its help says *"OAuth and keychain are
   never read"*, which would break the entire subscription path. Now a **negative** assertion.
4. **`--max-turns` is a no-op** — absent from `--help`, accepted silently, did not bound a run.
5. **`--json-schema` now exists** — rejected, with its measured ~89 s vs ~6–9 s cost as the reason.

Plus one conflict inside the repo's own rules: the envelope carries **`total_cost_usd`** (read
$0.248 on a *subscription* run) while `run-accounting` states no dollar amount is ever computed or
stored. Resolved by **dropping it** (PRD D-1).

## The drop-gate, and why it is discharged

`spec.md:6-10` pre-committed to dropping this aspect if the audit said the blunt `tests/` invariant
— not sample size — was the problem. **The audit did say that** (2026-07-29, `precision 0.00`).
The condition is nonetheless discharged because the defect was then fixed (v0.10.0) and measured
twice (v0.11.0 `1/15`; v0.12.0 exposure: **9 of 15 instances judged nothing**). `ROADMAP.md:310`:
*"only a re-mint reaches them."* **The bottleneck moved from the rule to the data** — and that
sentence has to be checkable, not taken on trust, which is why the PRD tabulates the three steps.

## Ambiguity found, and how it was resolved

The unit as briefed was one aspect. Two were added:

- **`exposure-forecast`** — because v0.12.0's result implies a mint at n≥50 could return *another*
  uninterpretable near-zero after ~11 h. **My first design for it was wrong** (a test-directory
  surface count returns ≈166/166 and could never fire its stop-branch); self-critique caught it and
  it was re-based on the instances' own problem statements, **measured to vary at 59/166 = 36%**
  before being specified.
- **`live-smoke-confirmation`** — the spec's one-instance rule promoted from *mitigation* to
  *deliverable*, because the headline risk (prompted tool-calls degrading edit behaviour) is
  untestable by any of the 12 offline criteria, all of which fake the subprocess.

## Guardrail check against `CLAUDE.md`

- **Not an agent framework.** The oracle is given **no tools**; the harness owns the loop.
  `loop.py`/`batch.py` unmodified is an acceptance criterion, not an intention.
- **Not a bare LLM judge.** The model here is the **subject under observation**, not a verifier.
  Nothing in this unit computes or influences a verdict.
- **Moat.** It does not deepen the replay engine directly — it unblocks the *data* the corpus and
  the Phase-0 number depend on, which is moat #2's supply line.
- **No raw-data egress.** Everything but the single smoke is offline; the smoke sends a task
  description and tool schemas the agent already receives.
- **R6/R7 preserved by construction**, and asserted on the constructed argv and env.
