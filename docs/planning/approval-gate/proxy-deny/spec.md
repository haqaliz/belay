# Aspect: proxy-deny

**Slug:** `approval-gate/proxy-deny` · **Depends on:** `decision-model` + `hold-channel` (aspects 1–2)

## Problem slice

The deny primitive and its wiring: the proxy's forwarder contract grows a
suppress outcome, the observer stays byte-consistent with the delivered stream, the
refusal is written to the client under a shared peer lock, and the composition root
activates the gate (env, validation, hook chain, import guard). The no-config path
must remain byte-identical to today.

## In-scope

- `BeforeFrame` returns `bool`: `True` = forward the original frame; `False` =
  suppress it (deliver nothing to the peer). `_FrameHold` records suppressed frames
  and reports them to the pump.
- `BoundedPeek.feed(chunk, suppressed: Sequence[bytes])`: the observer sees exactly
  the delivered stream — a suppressed frame's bytes (spanning chunks or not) are
  removed from the observation; any sync mismatch raises a named error that kills
  observation (best-effort rule: `_observe` names it and forwarding continues),
  never a silent corruption.
- `_pump` wiring: the forwarder's suppression report flows into the peek before
  `feed`; `_observe` carries it.
- A shared peer-write lock: the s2c forwarder's writes to the client fd and the
  approval gate's refusal delivery hold one lock per frame/chunk, so a refusal can
  never interleave with a server frame. Ungated runs install none of this.
- Composition root (`proxy.main` / `_contained_run`): `BELAY_APPROVAL_DIR` +
  `BELAY_APPROVAL_TIMEOUT` env validation (unusable dir, invalid timeout, or
  approval without `BELAY_TRACE_DIR` → refuse at startup, M1/M16); subdir setup;
  hook chain c2s = approval-decision then turn gate (a denied call never reaches the
  turn gate — no snapshot, no ledger entry), s2c = approval-cache observer then turn
  gate; `deliver` wired to the locked client writer; the import guard holds
  (`proxy.py` stays serialiser-free).
- A hold parks the c2s direction (the pump is inside the forwarder) — bounded by the
  deadline, fail-closed; the s2c pump keeps draining throughout.

## Out-of-scope

Trace record kinds (aspect 4), verify reporting (aspect 5), replacement semantics
(the hook may suppress or forward; it may never alter bytes), console wiring.

## Acceptance criteria (test-first)

1. **No-config byte identity:** with no `BELAY_APPROVAL_DIR`, the proxy path is
   byte-identical to today — the existing differential/byte-transparency tests stay
   green untouched, plus a new differential test exercising a destructive-annotated
   server with the gate unset (nothing is held, nothing is written to the approval
   dir).
2. **Deny never reaches the server:** with the gate configured and a deny decision
   pre-written, a `tools/call` to a `destructiveHint: true` tool is suppressed — the
   server's stdin never receives the request bytes (asserted via a server that
   records its stdin), and the client receives the refusal carrying its request id.
3. **Trace consistency:** the e2e denied trace contains no `frame` record for the
   suppressed request or the refusal (aspect 4's reader asserts this; the proxy
   tests assert the observation side: the peek's emitted frames equal the delivered
   stream).
4. **Suppression bookkeeping:** a suppressed frame wholly inside one chunk, spanning
   two chunks, and adjacent to other frames (before/after) — in every case the
   remaining frames are observed exactly and byte-identically; a sync mismatch names
   a `capture_error` and stops observation, never forwarding.
5. **Approve forwards verbatim:** with an approve decision, the request reaches the
   server byte-identically and the server's response reaches the client
   byte-identically (the `_FrameHold` never-alter guarantee).
6. **Holds park c2s only:** while a hold is parked, server-originated s2c bytes keep
   flowing to the client (a server writing to stdout while a later call is held —
   scripted server); the deadline denies.
7. **Shutdown while parked:** closing the writer / ending the run resolves the
   pending hold with `APPROVAL_SHUTDOWN` (no hang; capture-shutdown tests green).
8. **Hook chain ordering:** a denied call produces no turn-gate snapshot and no
   ledger entry (the turn-gate tests' ordering pins hold); an approved call behaves
   exactly as today.
9. **Import guard:** `tests/test_import_guard.py` green — `proxy.py` still imports
   no `json`; the approval module is imported only at the composition root.
10. **Env validation:** `BELAY_APPROVAL_DIR` set without `BELAY_TRACE_DIR` → exit 2
    with a `belay:` message; unusable dir → exit 2; invalid timeout → exit 2;
    absent → byte-identical (1).

## Dependencies and sequencing

Aspects 1–2 provide the decision/registry/channel; this aspect wires them. The
existing suites `test_turn_gate.py`, `test_trace_ordering.py`, `test_differential.py`,
`test_capture_shutdown.py`, `test_proxy_containment.py`, `test_import_guard.py` must
stay green throughout.