# Aspect spec — `replay-engine`

**Feature:** `deterministic-replay` (C3) · **PRD:** [`../prd.md`](../prd.md)
**Scope:** M1–M11, S1–S3. One aspect — replay is one composition, and C3 is not cuttable.

## Problem slice

The trace is complete and inert. C3 restores a recorded pre-state, re-invokes the exact recorded
`tools/call` in the sandbox against a fresh server, observes the result and the state delta, and
classifies determinism — producing the observations A2 (C4) turns into a grounded verdict.

**Outcome:** `belay replay <trace> [--turn N]` re-executes a recorded turn against its restored
pre-state, reports result-equivalence + the state delta, marks nondeterministic tools, and — for
anything it cannot replay — emits `unverified` with a **named cause**, never a result.

## In scope

M1 snapshot persistence (manifest + serialized sidecar) · M2 trace reader (skip-unknown, record the
skip) · M3 minimal stdio client via `launch.contained` · M4 handshake replay tolerating its absence ·
M5 restore to scratch, never live · M6 state delta via `diff_records` · M7 nondeterminism via N
replays, appended as a `nondeterminism` record · M8 C3's three inherited causes, enum invariant
intact · M9 key on `tools/call` via the index · M10 read `status` first; FIDELITY_GAPS not blocks;
`SNAPSHOT_FAILED` parse trap · M11 the UNVERIFIED rate report · S1 per-tool determinism ·
S2 DenialCapture · S3 gc scratch trees.

## Out of scope

Any verdict (C4). Effect-conformance / invariants / corpus. Trajectory replay (`--from`/`--to`,
follow-on). Fixing batched-chunk handle attribution (C2 follow-up). Non-macOS. Non-stdio.

## Acceptance criteria (test-first)

A1 clean run → 100% result-equivalence · A2 unrestorable → `unverified`, never a result ·
A3 clock/random → nondeterministic, not a divergence · A4 replay mutates neither trace nor live
state (asserted) · **A5 synthesized-empty-sidecar restore FAILS the BTH-1 comparison** ·
A6 a snapshot survives its process (fresh replay resolves `present` from the trace alone) ·
A7 unknown kind/higher v → skipped AND recorded · A8 no-handshake (2026-07-28) trace still replays ·
A9 UNVERIFIED rate reported, each instance → a named cause · A10 C1+C2 suites pass untouched (250).

All deterministic, no network, CI-runnable (macOS).

## Dependencies

Upstream: C1 (trace, index, frames, connection, hashing), C2 (launch.contained, guarded_restore,
clone, bth1, substrate, the 3 deferred causes). **C3 unblocks C4 — the critical path.**

## Risks

R-C3-1 empty-sidecar false PASS (Critical — A5 is the guard) · R7 UNVERIFIED may dominate (C3
measures it) · R-C3-2 timestamp-as-FAIL · R-C3-3 replay touches live state (Fatal — assert scratch) ·
R-C3-4 version drift (a finding) · R-C3-5 untrackable turn blocks forever (timeout).
