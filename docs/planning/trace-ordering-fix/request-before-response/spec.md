# Aspect spec — `request-before-response`

**Parent PRD:** `docs/planning/trace-ordering-fix/prd.md`
**One-line boundary:** the recorder defers a response's record until its request's record
exists, so an inverted pair cannot be written. `proxy.py`, `index.py`, `annotations.py`,
`effect.py`, the trace format and every verdict surface are untouched.

---

## Problem slice & user outcome

`_pump` forwards a chunk and observes it afterwards — *"forwarding must never wait on the
recorder"* — so a fast server can have its `tools/list` RESPONSE recorded before its own
REQUEST. `derive_correlation` pairs a request with a **later** response only, so the pair
breaks (`response-without-request` + `unanswered`), `derive_annotations` takes no
snapshot, and effect-conformance abstains for the whole run. Honest, and a real
**coverage-loss path for any fast local server**.

**Measured on this branch, before any engine change**, with a new fast-server fixture and
a sequenced client driving 22 request/response pairs per run through the real proxy: two
20-run stresses gave **15/20 and 12/20 runs holding at least one broken correlation** — 46
and 60 broken correlation records. That is the RED this aspect closes; it is a stochastic
race, so both observations are quoted rather than one averaged into a rate.

## In-scope requirements (PRD must-haves M1–M5)

1. **`src/belay/trace.py` only.**
   - **M1 · Request index.** Every c2s frame that carries a request contributes its
     `(type-name, id)` key to an in-writer index, updated **under the writer's lock, after
     the line is on disk** — so a waiter that sees a key knows the record exists.
   - **M2 · Response deferral.** An s2c frame that is a response to a client request waits
     on a `threading.Condition` over the writer's own lock until its key is indexed, or
     until a bounded deadline expires, or until the writer closes. The wait holds no lock
     (the condition releases it), so the other direction keeps recording.
   - **M3 · Exactness.** Structural classification identical to `index.classify`
     (`result`/`error` first, so a non-conforming response that also carries `method` is
     still a response). Truncated frames, unparseable frames, batch arrays, notifications,
     server-originated requests and container-valued ids **never wait and are never
     indexed**. No error-text matching, no time windows.
   - **M4 · Fail-open.** The deadline expiring records the response anyway, out of order.
     The trace stays honest and the readers name it exactly as they do today
     (`response-without-request` + `unanswered`); nothing is fabricated and no new record
     kind is invented.
2. **Tests, written first** — the deterministic unit RED (the deferral, the fail-open, the
   no-wait cases, the closed-abort, the index bound) plus the integration regression guard
   (the fast-server fixture above, N=20 calls, every pair `answered` with
   `request_seq < response_seq`, and the `tools/list` annotation snapshot present).
3. **M5 · Doc correction, exactly as wide as the fix** — `trace.py`'s between-directions
   ordering docstring, the "logged as a follow-up" lines in `CLAUDE.md` and `STATUS.md`,
   and the fixture docstrings that carry the old measurement.

## Explicitly out of scope

- The **snapshot-before-next-call** property (client-side by construction — only the client
  decides when its next request crosses). The fixture guards that still exist stay, and are
  re-documented as guarding that second property, not this one.
- Any change to `proxy.py` (the pump, `_FrameHold`, `_CaptureGate`), `index.py`,
  `annotations.py`, `effect.py`, the trace format, the verdict contract, `demo/server.py`,
  or any published number.
- Any CLI surface or environment variable for the deadline.

## Honest cost, stated because it is real

The deferral is on the **record** path, and the record path is called synchronously by the
pump *after* the frame it is recording has already been forwarded. So the frame being
recorded never waits — but while a deferral is in flight, the **next** chunk on that
direction is not read or forwarded. The wait is therefore a bounded stall on the s2c data
path, not the "never" the PRD's goal G2 first claimed. It costs:

- **nothing in the causal case** — the request was forwarded before the server could
  answer, and its record lands a hash and a write later, which is microseconds;
- **at most the deadline, once per orphan**, for a response whose request never crosses
  (a non-conforming server, or a proxy attached mid-connection — which this proxy cannot
  be, since it spawns the server itself).

**And the deadline is not optional, for a reason stronger than latency.** A parked response
stops its direction being read; a server that then floods its stdout fills the pipe and
blocks, stops reading its stdin, and blocks the other pump mid-write — so the record being
waited for cannot arrive. A legitimate pair cannot enter that cycle (a reply proves its
request was forwarded, and the c2s record follows its forward with only a hash in between,
before that pump can block on anything else), but an orphan response can. The deadline is
what makes that a bounded pause rather than a wedged proxy.

The deadline is therefore chosen small enough that a pathological orphan cannot dominate a
run and large enough to be orders of magnitude above the window it covers. The alternative
fix — recording a c2s frame *before* forwarding it — is causally airtight and was rejected
for the opposite trade: it puts the recorder in front of **every** client request rather
than behind a pathological handful, and it is a change to the one loop the transparency
contract is written on.
