# PRD: The trace-ordering race — request records always precede their responses

Slug: `trace-ordering-fix` · Branch: `bug/trace-ordering-race/aliz` · Type: bug ·
Owner: aliz
Sources: `docs/planning/_card/issue.md` (the brief), `CLAUDE.md` L3 block, the
docker-selfhost record (`docs/planning/docker-selfhost/`), `STATUS.md` L3 entry.

## Problem Statement

The proxy's two pump threads forward a chunk and **observe (record) it afterwards** —
`proxy.py:359-373`: *"forwarding must never wait on the recorder"* is the transparency
contract, and the record is deliberately after the forward. A fast server can therefore
have its `tools/list` RESPONSE **recorded before its own REQUEST**: the s2c pump's
record wins the writer lock first. Measured shape
(`tests/fixtures/docker_roundtrip_trace.py:9-10`):

```
seq 5  frame s2c  (reply to id 2)      <-- the tools/list RESPONSE
seq 6  frame c2s  tools/list  id 2     <-- its own REQUEST, recorded after
```

The consequence is a **coverage-loss path for any fast local server**, not a wrong
verdict:

1. `index.py` correlates strictly forward in seq order — a response answers only a
   *later-recorded* request. An inverted pair yields `response-without-request` **and**
   `unanswered` — two broken records, no re-pairing (`index.py:148-192`).
2. `derive_annotations` needs a correlated `tools/list` RESPONSE to take its snapshot;
   an inverted pair dies at `annotations.py:114-118` — **no snapshot at all**.
3. Every `tools/call` then has no live snapshot → `readOnlyHint` is
   `not-declared`-with-cause → **effect-conformance abstains (UNVERIFIED)** for the
   whole run (`effect.py:200-210`, `:556-565`).

The degradation is honest — UNVERIFIED, never a false PASS — and the engine was left
UNCHANGED at L3 time: the fixtures close the window by waiting on the trace itself
(no sleep; 40/40 stress from 18/20). That is a **fixture mitigation, not a fix**: any
real fast local server outside the fixtures still loses annotation coverage on its
first `tools/list`.

## Goals & Success Metrics

1. **The inverted pair becomes structurally impossible at the recorder.** For every
   request/response pair, the request's trace record is written before the response's
   — enforced by the engine, not by fixtures.
2. **The transparency contract survives where it is load-bearing, and the residue is
   named.** `proxy.py`'s pump and `_FrameHold` are **untouched**: the frame being
   recorded has already been forwarded, so no frame ever waits for its own record.
   **Corrected 2026-09-05, during the plan** — the first draft of this goal said "the
   data path never waits on recording", and that is not what the fix buys. The pump calls
   the recorder synchronously, so while a deferral is parked the **next** chunk on that
   direction is not read or forwarded. In the causal case the wait is zero (the request
   record precedes the reply's arrival by a hash and a write); in the pathological case it
   is bounded by the deadline, once per orphan response. Stated, not hidden — see
   `request-before-response/spec.md` → *Honest cost*.
3. **Fail-open honesty is preserved.** In pathological cases (the c2s pump died; a
   request id never reaches the recorder) the response records anyway, after a bounded
   wait, and the trace is honestly out of order — UNVERIFIED, never a fabricated
   PASS. The engine never manufactures coverage it did not earn.
4. **The race is pinned by a deterministic test** (no sleep, no probabilistic
   interleaving): the deferral mechanism itself is asserted, plus a fast-server
   roundtrip through the real proxy whose correlation and annotation snapshot are
   asserted end to end (the shape that measured 18/20 before).

## Requirements

### Must-have

- **M1 · Request index.** `TraceWriter` records, under its own lock, the ids of every
  c2s frame that is a **request** (has a `method`; JSON-RPC responses — client replies
  to server requests, e.g. sampling — and notifications are excluded). The index
  update is atomic with the append: a waiter that sees the id knows the record is on
  disk.
- **M2 · Response deferral.** For an s2c frame that is a **response** (has an `id`,
  no `method`), the writer waits — bounded, fail-open — until that id's request
  record exists, then records. The wait holds no writer lock; it is closed-aware
  (aborts early once the writer closes) and has a generous deadline (**settled in the
  plan at 2.0 s**, not the ~5 s first written here: 2 s is already four orders of
  magnitude above the window it covers, and every extra second is paid only by the
  pathological orphan; injectable for tests).
- **M3 · Exactness, not heuristics.** A frame is waited on only when it is provably a
  response to a client request. Server-originated requests (`method` present) never
  wait; notifications (no id) never wait; unparseable or truncated frames never wait.
  No error-text matching, no time-window guesses.
- **M4 · Deterministic RED → GREEN.** Tests written before the fix:
  - the deferral unit test — response observed with its request absent does **not**
    land until the request record arrives, then lands with
    `seq(request) < seq(response)` (fails on the current engine: response records
    immediately);
  - the fail-open test — a response whose request never arrives records after the
    deadline, out of order, honestly;
  - the no-wait tests — server-request frames and pre-recorded-request responses
    record immediately;
  - the integration test — a **new fast server fixture** (replies instantly, no
    trace-waiting guards) behind the real proxy, N roundtrips, asserting every
    request/response pair **correlates** (no `response-without-request`, no
    `unanswered`) and the `tools/list` **annotation snapshot exists** — the exact
    defect shape that measured 18/20 before. **The assertion is deliberately the
    defect's shape, not snapshot-liveness for the immediately-following call** —
    that property is client-side by construction (S1) and stays fixture-guarded:
    the engine's guarantee is request-before-response, nothing more.
- **M5 · Doc correction, exactly as wide as the fix.** The "logged as a follow-up"
  lines in `CLAUDE.md`'s L3 block and `STATUS.md` are retired and replaced with the
  fix's claim; `trace.py`'s between-directions ordering docstring (`trace.py:126-131`)
  is corrected from *"only ever 'when the proxy saw it'"* to the new guarantee; the
  docker-selfhost planning doc's follow-up line is retired if it names one. **No
  published number, verdict axis, or trace-format field moves.**

### Should-have

- **S1 · The fixture mitigations stay, documented as belt-and-braces.** The existing
  trace-waiting guards (`docker_roundtrip_server.py`, `claim_liar_server.py`,
  `demo/server.py` — the demo server is a pinned launch artifact and is NOT touched)
  are now redundant for the request-before-response property but still needed for the
  *snapshot-before-next-call* property, which is client-side by construction (only the
  client decides when its next request crosses) and cannot be closed by the recorder
  without delaying the client's data path. Docstrings get a one-line note; no code
  change.
- **S2 · Memory bound.** The index never grows with the run's total traffic.
  **Corrected in the plan, 2026-09-05:** the mechanism first written here — *"a request id
  leaves the index once a response for it has been recorded"* — is wrong in a reachable
  case. A **duplicate response** (a non-conforming server answering twice; `index.py` names
  it `duplicate-response` and this repo carries fixtures for it) would find its key already
  drained and stall for the whole deadline. The index is therefore **monotone and
  FIFO-capped** (4096 keys): a key stays once written, and the oldest is dropped past the
  cap. Bounded memory, and a spurious wait only for a duplicate arriving more than 4096
  requests late.

### Nice-to-have

- **N1 · A perf note**: the deferral adds a `json.loads` per frame on the record path
  (the gate already parses c2s frames at forward time; the writer now parses a copy
  for the index). The wait itself is typically zero-length — the request record
  causally precedes the response's arrival.

## Technical Considerations

- **Where the fix lives:** `src/belay/trace.py` only. `proxy.py` (the pump, the
  transparency contract, `_FrameHold`), `index.py`, `annotations.py`, `effect.py` are
  **unchanged** — they already handle out-of-order traces honestly, and the fix
  removes the *cause* rather than teaching the readers to tolerate it.
- **Byte-transparency is preserved structurally:** the proxy still has no name for
  `json` (`tests/test_import_guard.py`). The parse lives in `trace.py`, which already
  imports `json` to serialise records. The request/response discrimination mirrors
  `gate.py`'s `_turn_ids`/`_answered_ids` semantics (method-vs-result/error), not a
  new vocabulary.
- **Sequencing semantics change, honestly:** `seq` was *arrival order at the writer*;
  it becomes *arrival order with the guarantee that a response never precedes its
  request*. The trace format is unchanged (no new field, no schema bump); the
  docstring is the contract that moves.
- **Deadlock analysis:** the s2c record waits only on the c2s record, which causally
  must happen (the request was forwarded before the server could reply) and which
  never waits on s2c. The only non-causal cases are process death and direction
  teardown — both covered by the deadline and the closed-abort. The wait holds no
  writer lock, so `close()` and the other direction are never blocked behind it.
- **Shutdown latency:** `_CaptureGate.stop()` waits for an in-flight observation; an
  s2c observation mid-wait delays shutdown by at most the deadline (closed-abort
  shortens it). Bounded, named, accepted.
- **Placement:** C1 (capture) hardening — the moat (execution-grounded capture
  fidelity), not a framework or a judge.
- **Verdict impact:** no axis changes; effect-conformance will PASS/FAIL more often
  instead of abstaining on fast-server traces — improved coverage, never a
  reclassification. The 11/60 mint number and all published figures stand unedited
  (no Phase-0 capture was affected by this path).

## Risks & Open Questions

- **The wait hides a genuinely dead recorder?** No — the wait is on the *index* (the
  c2s record), and the c2s record happens regardless of the s2c path. A dead c2s
  observer surfaces as `capture_error` on that direction exactly as today.
- **A malicious/buggy server echoing a client id before... impossible:** the server
  cannot send a response before receiving the request, and the request record is
  written by the c2s pump — which forwarded it first. The wait's causal anchor is
  sound.
- **Resolved in the plan:** the default deadline is **2.0 s** and is not configurable from
  the CLI — a pathological 2 s stall on the s2c record path is the accepted cost; expose it
  only if a real user hits it.
- **Open:** whether the integration stress test's N (20) is enough regression
  protection — decided in the plan (N=20 measured, deterministic on the fixed engine).

## Out of Scope

- The **snapshot-before-next-call** property (client-side by construction; fixture
  guards stay load-bearing for it — S1).
- Any change to `proxy.py`, `index.py`, `annotations.py`, `effect.py`, the trace
  format, the verdict contract, or any published number.
- The `demo/server.py` fixture (pinned launch artifact).
- Any CLI surface or configuration for the deadline.