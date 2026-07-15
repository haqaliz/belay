# Aspect spec — `stdio-proxy-capture`

**Feature:** `mcp-proxy-capture` (C1) · **PRD:** [`../prd.md`](../prd.md)
**Scope:** the whole of C1's must-haves **M1–M15** plus should-haves **S1–S4**.

> **Why one aspect, not three.** C1's top risk is **R-C1-1: over-investing in capture while C2 (the
> critical path, R2) waits**. The proxy, the trace format, and the annotation snapshot are mutually
> coupled — the schema is shaped by what the pump can observe, and the pump is proven by a test that
> reads the trace. Splitting them into three aspect directories buys ceremony, not clarity.
> Decomposition lives in the plan's **phases**.

---

## Problem slice and user outcome

There is no faithful, re-invocable record of what an agent did. This aspect delivers one: a
**byte-transparent stdio MCP proxy** and the **versioned trace format** every later capability reads.

**Outcome:** the founder can point an MCP-speaking agent at Belay instead of its server, run it, and
get a tamper-evident, replayable, opinion-free record — with **no observable change to the agent's
behavior**, proven by an executable differential rather than asserted.

---

## In scope

All PRD must-haves:

| ID | Requirement |
|---|---|
| M1 | Transparent stdio proxy (agent → Belay → real server), stdio only |
| M2 | Forward original bytes verbatim; never re-serialize |
| M3 | Full-duplex pump (not request/response) |
| M4 | Correlate on `(direction, id)`; correlation in our own side-table |
| M5 | Record **every frame**, append-only JSONL; `tools/call` is a derived index |
| M6 | Store raw (base64) + `hash_raw` + `hash_canonical` + `canonical_form` |
| M7 | Annotation snapshot with **mandatory tri-state** |
| M8 | Re-snapshot on `notifications/tools/list_changed`; append, never overwrite |
| M9 | Per-call resolved session context (2026-07-28-proof) |
| M10 | Forward everything, police nothing |
| M11 | Honest failure recording; protocol error vs `isError` distinguishable |
| M12 | Versioned, self-describing schema; documented unknown-record/higher-version rule |
| M13 | **Forward by streaming chunks; observe by peeking a bounded copy** |
| M14 | Local-only; configurable artifact root, default `/traces/` |
| M15 | Trace is sensitive by construction: owner-only modes, documented, no capture-time redaction |

Should-haves **S1** (annotation incoherence recorded), **S2** (three-state handle slot, left empty),
**S3** (`structuredContent` + duplicate text block recorded faithfully), **S4** (session-window facts).

---

## Out of scope (boundaries)

Everything in the PRD's Out of Scope, restated at aspect level because these are the tempting drifts:

- **Any verdict on any axis.** No PASS/WARN/FAIL/UNVERIFIED emitted. C1 records; it does not judge.
- **Snapshot/restore** — the state-handle slot is **defined and left empty**. Do not guess C2's
  substrate.
- **Replaying, re-invoking, or diffing anything.**
- **Redaction / secret-scanning** — an opinion, and C1 is opinion-free.
- **Streamable HTTP / SSE / OAuth.**
- **A migration framework** — ship the version field and the unknown-record rule, nothing more.
- **Any UI.**

---

## Acceptance criteria (testable — written as failing tests BEFORE the code)

Lifted from `CAPABILITY_ROADMAP.md:84-91` plus the guards the prototype proved necessary:

| # | Criterion |
|---|---|
| A1 | **Behavior-neutrality.** Fake server + scripted client, with and without proxy → **byte-identical** streams. *The gate everything hangs from.* |
| A2 | **Teeth.** A deliberately re-serializing proxy is **rejected** by A1. Permanent in CI. |
| A3 | **Anti-vacuity.** Fixture still carries hostile-but-legal bytes (scrambled key order, `\u` escapes, explicit nulls, unknown top-level field, interleaved unsolicited notification). |
| A4 | **Capture completeness.** Every `tools/call` appears with args, result, annotations; per-frame hashes **stable across two identical runs**. |
| A5 | **Tri-state annotations.** `not-declared` distinguishable from `declared-false`. |
| A6 | **Honest errors.** Malformed/non-conforming server → **recorded error, never a dropped turn**; protocol error vs `isError: true` distinguishable. |
| A7 | **Schema round-trip.** Version N written → version N readable. |
| A8 | **Real-client compat.** A real `mcp` SDK client drives through the proxy successfully. SDK is **dev-only**. |
| A9 | **Byte-exact round-trip**, including a **non-UTF-8 / non-conforming** frame that must round-trip rather than crash the writer. |
| A10 | **Trace files owner-only** at creation (mode asserted). |

All tests **deterministic, no network, CI-runnable**.

**Explicitly NOT asserted (would be false):** timing equivalence; hash stability against a real
nondeterministic server; that any real server is unperturbed. **C1 proves byte-transparency against
deterministic fixtures.**

---

## Dependencies and sequencing

- **Upstream:** none. *"This is the first commit of the engine"* (`CAPABILITY_ROADMAP.md:96`).
- **Downstream:** C2 (state handle + denials), C3 (re-invoke recorded call; nondeterminism marks),
  C4 (result content **and** hash; tri-state annotations), C5 (annotation-inferred invariants),
  C6 (sliceable cases), C9 (turn identity + timing for OTel correlation).
- **Blocks:** everything. C1 must be **small and finished** so C2 (R2) starts.

---

## Aspect-specific risks / open questions

- **R-C1-1** — over-investing here. **Budget: ≤5 working days.** Scope-add defers to C2+ by default.
- **Canonical form undecided** — JCS (RFC 8785) vs a Belay-defined form. Must be **documented and
  versioned** either way (`canonical_form: "belay/jcs-v1"`). *Decide in Phase 4; do not block A1.*
- **Python ≥3.10 required** by the `mcp` SDK (dev dep); system Python is 3.9 → **pin the interpreter**.
- **Bounded peek vs indexing** — a frame exceeding the observe cap forwards exactly but may index
  incompletely. That must be a **named cause**, never silently indexed as absent.
