# Aspect spec — `seatbelt-sandbox`

**Feature:** `sandbox-snapshot-restore` (C2) · **PRD:** [`../prd.md`](../prd.md)
**Scope:** M1–M13, S1–S4. One aspect, because containment and snapshot are the same machinery and
C2 is the critical path (R2) — three aspect directories would buy ceremony, not clarity.

## Problem slice

Belay can record what an agent did (C1) but cannot **re-execute** it, because it cannot restore the
state a turn ran against, and cannot contain what the agent does while it runs.

**Outcome:** the founder can run an MCP server through Belay with a scope, and (a) an escape attempt
is contained **and recorded**, (b) a turn's pre-state restores **byte-identically in milliseconds**,
(c) anything we cannot restore says so **with a named cause** instead of pretending.

## In scope

M1 Seatbelt substrate · M2 boundaries (fs scope, network enum, per-tool) + denial records ·
M3 `realpath` everything · M4 `clonefile(CLONE_ACL)` via ctypes · M5 the 3 repairs ·
M6 BTH-1 tree hash · M7 narrow substrate + **refuse out-of-substrate loudly** ·
M8 `unrestorable` + named cause filling C1's slot · M9 record network policy as a fact ·
M10 threat model · M11 local-only · **M12 the `before_frame` gate** · **M13 zero-config default scope**
S1 `capabilities()` + manifest + refuse cross-backend · S2 GC handles ACL'd trees ·
S3 `com.apple.provenance` ignore-list · S4 fidelity rate + taxonomy as eval data

## Out of scope

Any verdict (C4/C5 judge; C2 *originates* the fact) · replay (C3) · diffs (C4) · invariants (C5) ·
Docker/Linux/bwrap/gVisor/firejail · HTTP/SSE transports · restoring birthtime/ctime/atime/
ownership-when-not-root/sockets/devices/FIFO-contents (each **named**) · cross-filesystem restore
(**refused**) · a `Sandbox` ABC for substrates that don't exist.

## Acceptance criteria (test-first)

| # | Criterion |
|---|---|
| A1 | Pre-state restores **byte-identically**: `BTH-1(restored) == BTH-1(original)` on a torture tree |
| A2 | Escape contained **AND recorded**: direct · `../` · symlink-out · `mv`-out · **grandchild**. Each: no file, **exact rc**, **exact stderr**, **`denial` record** |
| A3 | **Positive control**: same write succeeds when permitted; same egress succeeds under allow-all |
| A4 | Out-of-substrate (FIFO) **detected and refused** with a named cause; `state_handle = unrestorable` |
| A5 | **Repair-ablation**: disabling `hardlinks`/`suid`/`dirmtimes` (each, and all) **MUST fail A1** |
| A6 | **Mutation suite, field-attributed** — caught by the field under test, *not* a parent dir's mtime |
| A7 | **Negative controls STABLE**: no-op re-snapshot · atime churn · inode churn don't move BTH-1 |
| A8 | **Hostname allowlist REJECTED at the API** |
| A9 | `realpath`: scope `/tmp/x` behaves identically to `/private/tmp/x` |
| A10 | **C1's gate still passes untouched** — differential + teeth + import guard |

All deterministic, no network, CI-runnable (macOS runners).

## Dependencies

**Upstream:** C1 ✅ (`proxy.py:300` Popen = the hook; `trace.py:156` `state_handle` = the slot;
extensible record kinds; `hashing.py`).
**Downstream:** C3 replays against this. **C2 blocks the engine.**

## Risks

R2 (critical path — largely retired: the hard part is measured working) · R-C2-3 (containment test
passes for the wrong reason — SIGABRT) · R-C2-4 (restore test passes for the wrong reason — dir
mtime) · R-C2-5 (loopback unresolved → **spike first**) · R-C2-7 (**the sandbox gets turned off →
Belay is a recorder again**).
