# C3 — Deterministic replay: Understanding note (Phase 2)

**Status:** pre-PRD. Every claim below was **run on this machine** against the merged C1+C2 engine.
**Source:** `docs/planning/_card/issue.md` (quotes `CAPABILITY_ROADMAP.md` §C3 verbatim).
**Base:** master @ 521bc0a — C1 + C2 merged, 250 tests green.

---

## 1. What the work is really asking

**This is the durable core.** *"A judge's guess gets cheaper to fool every year — a re-executed diff
does not."* Replay is what makes the trace **useful** rather than merely recorded — *"precisely the
line between us and Langfuse/Phoenix."*

C3 is the first capability that **composes** everything: read the trace (C1), restore the pre-state
(C2), re-invoke the recorded call in the sandbox (C2), observe the result and the state delta.

**C3 emits no verdict.** It produces the *observations* C4 turns into A2. It classifies determinism;
it does not judge.

## 2. 🔴 Verified: the handshake IS replayable (checked first — it would have been a blocker)

MCP servers under 2025-11-25 expect `initialize` before `tools/call`. **If the trace didn't record
the handshake, C3 could not re-invoke anything.** Ran it:

```
seq=2 c2s initialize                    ✓ recorded
seq=3 s2c <resp id=1>                   ✓ recorded
seq=4 c2s notifications/initialized     ✓ recorded
seq=5 c2s tools/call                    ✓ recorded
seq=6 s2c <resp id=2>                   ✓ recorded
CAN C3 REPLAY THE HANDSHAKE?: True
```

**Not a blocker.** C3 can replay `initialize` → `notifications/initialized` → the target
`tools/call`.

## 3. 🔴 The trap that will bite C3: `state_handle: present` ≠ "this frame is a replayable turn"

**Verified, unbatched — attribution is correct:**
```
seq=2 initialize                status=absent    ✓
seq=3 <resp id=1>               status=absent    ✓
seq=4 notifications/initialized status=absent    ✓
seq=5 tools/call                status=present  handle=2b239e  ✓ its own
seq=6 <resp id=2>               status=present  handle=2b239e  ✓ the turn's response
```

**Verified, BATCHED (one client write) — every frame claims the turn's handle:**
```
seq=2 initialize                status=present  handle=6326b5   <-- crossed BEFORE any turn
seq=3 notifications/initialized status=present  handle=6326b5
seq=4 tools/call                status=present  handle=6326b5   <-- the only legitimate owner
seq=5 <resp id=1>               status=present  handle=6326b5
seq=6 <resp id=2>               status=present  handle=6326b5
```

Cause: `_FrameHold` runs the hook per **frame**, but `_pump` feeds the peek per **chunk**. The suite
documents this (`test_a_batched_write_puts_the_turns_handle_on_its_whole_chunk`).

> **C3 MUST key on `tools/call` frames via the index — NEVER on `state_handle == "present"`.**
> A batched `initialize` claims `present`. **Claude Code batches by instruction, so this is the
> common case, not the corner.**
>
> **C2 follow-up (Minor, not C3's to fix):** strictly, a batched `initialize` carrying a turn's
> handle is a false statement about *that frame's* pre-state. It is documented, and the review's
> fix (b) closed the *pipelined-`tools/call`* case but not the *batched-mixed-frame* case.

## 4. 🔴 The strategic finding: C3 is where R7 gets tested for real

**R7:** *"Nondeterministic tools make UNVERIFIED the default verdict — the product says 'shrug'."*

C2's final fix means **pipelined turns have no pre-state** (`UNRESTORABLE_CONCURRENT_TURN`), so
**C3 cannot replay them.** And **Claude Code batches independent tool calls by instruction.** Stack
wall-clock, randomness, and process state on top, and a real agent run may be **mostly
unverifiable**.

**That is not a defect — it is the honest consequence of refusing to fake a pre-state.** But it is
**exactly the number the Phase-0 gate exists to produce**, and C3 is the first capability that can
*measure* it instead of speculating.

→ **C3 must report the UNVERIFIED rate with each instance traced to a named cause** (`ROADMAP.md:112`
requires precisely this). If the rate dominates, that is a **gate signal**, not a bug to hide.

## 5. C2's inherited obligations — three causes C2 named and deferred to C3

Read from `substrate.RAISED_BY` (not from docs):

| Cause | C2's stated reason C3 owns it |
|---|---|
| `UNRESTORABLE_WALL_CLOCK` | *"Re-execution happens at a different time, so a time-dependent call diverges **legitimately**. That is a property of the replay, not of the pre-state, and it is invisible to a snapshot."* |
| `UNRESTORABLE_RUNNING_PROCESS` | *"Process-internal state — open fds, connection pools, auth sessions — is restorable in principle but never by a filesystem snapshot."* |
| `UNRESTORABLE_RANDOMNESS` | *"Seatbelt is access control, not a hypervisor: it virtualises no entropy source, so a snapshot cannot make `urandom` replay the same bytes."* |

**C3 must raise these**, and the enum invariant (18 causes: 9 raised locally, 9 deferred, **0
unaccounted**, proven by `test_each_locally_raised_cause_is_actually_produced`) must survive.

> **`UNRESTORABLE_WALL_CLOCK` carries C2's sharpest warning:** *"Never let a timestamp diff render as
> FAIL — that's how you train users to ignore the verifier."* A clock-dependent tool **legitimately**
> diverges. That is **nondeterminism, not infidelity.** Conflating them is how C4 becomes noise.

## 6. The architectural fact: **C3 is a CLIENT, not a pump**

`proxy.py` forwards between two live pipes. **C3 must SEND one recorded frame and READ the reply** —
a fundamentally different shape. Expect C3 to need its own **minimal stdio client** (stdlib only;
the `mcp` SDK is dev-only and cannot be imported from `src/belay/` — `test_import_guard.py` enforces
it statically).

**Kill and respawn the server per replay.** C2 already argued this: it is what avoids most
`PROCESS_INTERNAL_STATE`, and it is another reason v0 is stdio-only.

## 7. Verdict axes

C3 sits on **no axis** — it produces the observations A2 (C4) consumes. But **it decides what A2 can
ever say**:
- a turn C3 cannot replay is **UNVERIFIED forever**
- a tool C3 marks nondeterministic yields **UNVERIFIED**, *"never PASS and never a false FAIL"*
- **the nondeterminism marking is "an input to C4, not an excuse"** — the roadmap's words

## 8. Guardrail check

| Guardrail | C3 |
|---|---|
| No agent framework | ✅ C3 replays a recorded call; it never authors or drives an agent |
| No LLM judge | ✅ Zero model calls. Re-execution *is* the mechanism |
| UNVERIFIED never PASS | ✅ **C3's core deliverable** — unrestorable → `unverified`, never a result |
| No raw-data egress | ✅ Local; replay runs in the sandbox against a restored copy |
| Never claim coverage we don't have | ⚠️ **The UNVERIFIED rate is the honest headline.** Do not bury it |
| Test-first | ✅ |

## 9. Open questions for the PRD

1. **Restore destination** — can a snapshot restore to a *different* directory? C3 must restore to a
   scratch copy and **never touch live state** (*"Replay never mutates the original trace or live
   state — asserted, not assumed"*). If restore is destination-locked, that is a real design issue.
   *(Awaiting the API map.)*
2. **How many replays decide "nondeterministic"?** N=2 is cheap and catches clock/random; N=3+ costs
   time. The roadmap says *"replaying a turn N times"* without fixing N.
3. **Does C3 write back into the trace, or emit a separate artifact?** The roadmap says
   nondeterminism *"marks the tool nondeterministic **in the trace**"* — but the trace is
   **append-only** and *"replay never mutates the original trace"*. → **Append a new record kind**
   (C1's schema is extensible); never rewrite a frame. **These two requirements only reconcile via
   append.**
4. **`--from`/`--to` whole-trajectory replay** — in v0, or is single-turn enough to unblock C4?
   Recommend: single-turn first; trajectory is a follow-on slice.
