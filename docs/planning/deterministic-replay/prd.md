# PRD — C3: Deterministic replay

**Capability:** C3 · **Phase:** 0 · **Window:** week 2 · **Cuttable:** **No — the durable core**
**Dependencies:** C1 ✅ (PR #1) · C2 ✅ (PR #3) — both merged, 250 tests green
**Branch:** `feat/deterministic-replay/aliz` · **Slug:** `deterministic-replay`
**Inputs:** [`_card/issue.md`](../_card/issue.md) · [`understanding.md`](./understanding.md)

> Every claim below was **read in source or run on this machine**. Inference is marked.

---

## Problem Statement

**Replay is what makes the trace *useful* rather than merely recorded — "precisely the line between
us and Langfuse/Phoenix."** It is also the moat's durable half: *"a judge's guess gets cheaper to
fool every year; a re-executed diff does not."*

**Who:** immediately, C4 — which cannot exist without it. A2's entire verdict is
*re-execute and diff*; C3 is the re-execution.

**Evidence it's needed now:** C1 records faithfully, C2 restores byte-identically and contains. The
trace is complete and inert. **Nothing has ever been re-executed.** Every claim Belay makes about
verification is, today, a claim about a capability that doesn't exist.

---

## 🔴 The critical path: snapshots do not survive their process

**Verified:**
```
trace says : handle = 2b239e812ab143208ee1c72b1636460d
disk has   : turn-0000/
joins them : NOTHING
```

C2 named this and handed it over, in its own source:
> *"In-process only: the sidecar `clone.restore` needs lives in memory, so restoring in a **later
> process is C3's problem, not a promise made here**."* (`gate.py:318-320`)
> *"The sidecar lives in memory, so a `Snapshot` does not outlive its process."* (`clone.py:66-68`)

**This is C3's critical path.** `belay replay <trace>` runs in a *later process* by definition. Until
a snapshot is resolvable from a trace, C3 cannot restore anything, and A2 cannot exist.

### 🔴 And it comes pre-loaded with a false PASS

`clone.restore` **requires** `snap.sidecar` — it is what rebuilds **hardlink identity, setuid, and
dir mtimes**, the three things `clonefile` silently destroys, **all invisible to a content-only
hash**.

> **A C3 that reconstructs a `Snapshot` from the on-disk tree with a synthesized empty sidecar WILL
> restore, WILL hash, and WILL look correct — while having silently dropped exactly the divergence
> BTH-1 exists to catch.**

That is the cardinal sin, waiting. **The sidecar must be persisted, not synthesized.** Its fields are
**raw bytes** (`clone.py:116-130`) → base64; **never decode** — the bytes are the whole point.
`test_ablating_a_repair_breaks_the_restore` is the permanent guard.

---

## Goals & Success Metrics

| Goal | Metric |
|---|---|
| Replay reproduces a clean run | **100% result-equivalence** |
| Unrestorable pre-state | **`unverified`, never a result** |
| Nondeterminism detected, not hidden | A clock/random tool is marked **nondeterministic**, not divergent |
| Replay is inert | **Never mutates the original trace or live state — asserted, not assumed** |
| **The honest headline** | **UNVERIFIED rate reported, every instance traced to a named cause** |
| Small and finished | ≤5 working days |

---

## Requirements

### Must-have

**M1 · Snapshot persistence — the critical path.** An on-disk manifest joining
`handle → tree path, backend, capabilities`, **plus a serialized sidecar** (`link_groups`,
`special_modes`, `dir_times` — raw bytes, base64, never decoded). Without it `present` is
unresolvable in a later process.
**Forbidden: synthesizing an empty sidecar.** See above.

**M2 · A trace reader.** `trace.py` is **writer-only** (verified: no reader anywhere in `src/`; the
only readers are two copies of a test helper). C3 owns it, and it must honour the contract C1 wrote
at `trace.py:48-52`: **a record with an unknown `kind` or a higher `v` is SKIPPED and the skip is
RECORDED** — never dropped silently, never fatal.

**M3 · A minimal stdio MCP client.** `proxy.py` is a **pump**; C3 is a **client** — it sends one
frame and awaits the matching reply. Nothing reusable exists.
- **Use `launch.contained(command, workspace=, network=)`** (`launch.py:181`) — a contextmanager
  yielding `Contained(argv, ...)` that **keeps the profile file alive** and does **not** spawn. It
  was built for exactly this (`launch.py:38`). `seatbelt.run` is run-to-completion and unusable —
  C2 says so at `launch.py:20-25`.
- Then C3's own `Popen(spawn.argv, stdin=PIPE, stdout=PIPE, stderr=PIPE)`; write `frame + b"\n"`;
  read newline-delimited stdout until the **matching id**; **with a timeout**.
- **Trap:** `_UntrackableTurn` (`gate.py:169`) — a `tools/call` with no usable id is unanswerable by
  JSON-RPC. **Never block forever awaiting a reply that cannot exist.**

**M4 · Replay the handshake — and tolerate its absence.** Verified: the trace **does** record
`initialize`. C1 filters nothing (`proxy.py:419-439`; no method check on the capture path).
**But under MCP 2026-07-28 the handshake does not exist** (SEP-2575/2567 — `connection.py:19-28`), so
a legitimate trace may contain zero initialize frames. **Do not hard-require one.** Use
`connection.derive_connection_context(records)` (`connection.py:214`), which resolves per-frame:
handshake → per-request `_meta` → **unknown with a named cause**.
> **A fresh server may negotiate a different version than the recorded one. That is a real replay
> finding, not an error to swallow.**

**M5 · Restore to a scratch copy — never live state.** `clone.restore(snap, dest)` and
`substrate.guarded_restore(snap, dest)` (`substrate.py:386`) **already accept an arbitrary dest** and
capability-check before touching it. **Not a blocker.** Replay runs inside `launch.contained` against
the restored copy.

**M6 · The state delta.** `bth1.scan_tree` before → re-invoke → `scan_tree` after →
`diff_records` → `FieldDiff(path, field, left, right)`. **It names the field** — that is what makes a
delta reportable instead of two hex strings. Nothing missing.

**M7 · Nondeterminism: detected, not hidden.** Replay a turn **N times**; divergent results mark the
tool **nondeterministic**. Append a **`nondeterminism` record** — C1 already reserved the kind
(`trace.py:52`).
> **Append, never rewrite.** The roadmap says "marks the tool nondeterministic **in the trace**" *and*
> "replay never mutates the original trace." **Those reconcile only via append.** C1's schema is
> extensible; this is exactly what that was for.

**M8 · C3's inherited causes.** C2 named three and deferred them (`substrate.RAISED_BY`):
`UNRESTORABLE_RUNNING_PROCESS` (fds, pools, auth sessions) · `UNRESTORABLE_RANDOMNESS` (*"Seatbelt is
access control, not a hypervisor"*) · `UNRESTORABLE_WALL_CLOCK`.
**The enum invariant must survive: 18 causes, 0 unaccounted**, proven by
`test_each_locally_raised_cause_is_actually_produced`.
> 🔴 **C2's sharpest warning, and C3 is where it lands:** *"Never let a timestamp diff render as FAIL
> — that's how you train users to ignore the verifier."* A clock-dependent tool **diverges
> legitimately**. **That is nondeterminism, not infidelity.** Conflating them turns C4 into noise.

**M9 · Key on `tools/call`, never on `state_handle`.**
`index.derive_correlation(records)` → `index.tool_calls(index)` (`index.py:190`).
> **Verified trap:** batched into one client write, **every frame in the chunk claims the turn's
> handle** — including an `initialize` that crossed *before* the turn. Documented by
> `test_a_batched_write_puts_the_turns_handle_on_its_whole_chunk`. **Claude Code batches by
> instruction — this is the common case.**
> **Correlation key is `(direction, type(id).__name__, id)`, never the bare id** (`index.py:75-82`) —
> `id:1` routinely exists twice meaning two different things.
> `status` may be `unanswered` / `response-without-request` / `duplicate-response`, so
> **`response_seq` can be None on a turn that really executed.**

**M10 · Read `state_handle.status` first.** `absent` | `present` | `unrestorable`.
**`absent` is NOT failure** — it means no snapshot was attempted (`substrate.py:407-409`).
Only `present` carries a restorable pre-state.
> 🔴 **`FIDELITY_GAPS` are NOT blocks.** They appear on **every** `present` handle; treating them as
> blocks would **refuse every turn**.
> 🔴 **Parsing trap:** `SNAPSHOT_FAILED = "UNRESTORABLE_SNAPSHOT_FAILED"` (`gate.py:156`) appears in
> traces and is **deliberately not an `UnrestorableCause` member**, pinned by
> `test_the_gate_owned_cause_is_not_smuggled_into_the_taxonomy`. **`UnrestorableCause(cause_string)`
> will throw.**

**M11 · Report the UNVERIFIED rate, with every instance traced to a named cause.**
`ROADMAP.md:112` requires exactly this. **This is the honest headline, not an appendix.**

### Should-have

- **S1 · Per-tool determinism classification** as eval data — *"a reference distribution that tells us
  which tools are verifiable at all."*
- **S2 · `launch.DenialCapture`** (`launch.py:124`) during replay — free A1 signal.
- **S3 · `substrate.gc`** for scratch trees — it deletes trees the OS says you may not delete (an
  agent under test can set *"everyone deny delete"*).

### Nice-to-have / deferred

- **N1 · `--from` / `--to` whole-trajectory replay.** **Recommend deferring** — single-turn replay
  unblocks C4, and C4 is the critical path. Trajectory is a follow-on slice.

---

## Technical Considerations

**Composes unchanged (verified in source):** `index.derive_correlation` / `tool_calls` ·
`frames.message_of` (returns `(msg, cause)` so a caller **must** name the cause or visibly ignore it)
· `connection.derive_connection_context` · `launch.contained` / `network_policy` (**defaults
deny-all**) / `DenialCapture` · `substrate.guarded_restore` · `bth1.scan_tree` / `diff_records` /
`hash_tree` · `substrate.gc`.

**Verdict axis: none.** C3 produces the **observations** A2 consumes. But it **decides what A2 can
ever say**: a turn C3 cannot replay is UNVERIFIED forever; a tool marked nondeterministic yields
UNVERIFIED, *"never PASS and never a false FAIL."* The marking is *"an input to C4, not an excuse."*

**Guardrails.** No agent framework (C3 replays a recorded call; it never authors or drives an agent).
No LLM judge — **re-execution IS the mechanism**. No egress (replay is sandboxed, deny-all default).
Zero runtime deps — the `mcp` SDK is dev-only and `test_import_guard.py` enforces it statically. ✅

---

## Risks & Open Questions

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| **R-C3-1** | **The empty-sidecar false PASS.** A synthesized sidecar restores, hashes, and looks correct while dropping hardlinks/setuid/dir-mtimes. | **Critical** | M1: persist it. A test must **watch a synthesized-empty-sidecar restore FAIL** the BTH-1 comparison — otherwise this ships. |
| **R7** | *Roadmap.* **UNVERIFIED becomes the default verdict; the product says "shrug".** Pipelined turns are unreplayable **and Claude Code batches by instruction**; wall-clock, randomness and process state stack on top. | **High** | **C3 is where this is MEASURED rather than speculated.** M11. **If UNVERIFIED dominates, that is a gate signal — not a bug to hide.** |
| **R-C3-2** | **A timestamp diff rendered as FAIL** trains users to ignore the verifier. | **High (trust)** | M7/M8: nondeterminism ≠ infidelity, and the distinction is made by **repeated replay**, not by guessing. |
| **R-C3-3** | Replay mutates live state. | **Fatal** | M5: restore to scratch, inside `launch.contained`. **Assert it, don't assume it.** |
| **R-C3-4** | Version drift: a fresh server negotiates a different protocol version than recorded. | Med | M4: **a finding, not an error to swallow.** |
| **R-C3-5** | A `tools/call` with no usable id blocks replay forever. | Med | M3: timeout + `_UntrackableTurn` awareness. |

**Open questions:**
1. **N for nondeterminism detection?** N=2 is cheap and catches clock/random; N=3 costs time.
   **Recommend N=3, configurable** — 2 can't distinguish "differs" from "differs *consistently*".
2. **Trajectory replay in v0?** Recommend **no** (see N1).
3. **Does `belay replay` write into the source trace, or a sibling?** Recommend **a sibling replay
   artifact** referencing the source trace by hash — cleanest reading of *"never mutates the original
   trace"*, and it keeps a replay reproducible against the exact trace it ran on.

---

## Out of Scope

- **Any verdict** — C3 observes; **C4 judges**. No PASS/FAIL/UNVERIFIED emitted; C3 emits the
  *facts* (result-equivalence observations, deltas, determinism classification) A2 reduces.
- Effect-conformance vs annotations (C4). Invariants (C5). The corpus (C6).
- Whole-trajectory replay (N1, follow-on).
- Fixing the batched-chunk handle attribution — **a C2 follow-up**, documented; C3 routes around it
  by keying on `tools/call`.
- Non-macOS. Non-stdio.

---

## Acceptance Criteria (test-first)

From `CAPABILITY_ROADMAP.md` C3, plus the traps the map surfaced:

| # | Criterion |
|---|---|
| **A1** | **A clean recorded run replays with 100% result-equivalence.** |
| **A2** | **A turn whose pre-state is unrestorable yields `unverified` — never a result.** |
| **A3** | **A deliberately nondeterministic fake tool (clock/random) is detected as NONDETERMINISTIC across repeated replays — not reported as a divergence.** |
| **A4** | **Replay never mutates the original trace or live state** — asserted, not assumed. |
| **A5** | 🔴 **A synthesized-empty-sidecar restore FAILS the BTH-1 comparison** — the false PASS in R-C3-1, proven catchable. |
| **A6** | A snapshot **survives its process**: a fresh `belay replay` resolves a `present` handle from the trace alone. |
| **A7** | An unknown `kind` / higher `v` is **skipped AND the skip recorded** (C1's reader contract). |
| **A8** | A trace with **no handshake** (2026-07-28 shape) still replays via `_meta`. |
| **A9** | The **UNVERIFIED rate** is reported with **every instance traced to a named cause**. |
| **A10** | C1's + C2's suites pass **untouched** (250 tests). |

All: **deterministic, no network** (fake MCP servers), **CI-runnable** (macOS).

> **Explicitly NOT asserted:** that most turns are replayable. **The UNVERIFIED rate is an output of
> this capability, not an assumption of it.**
