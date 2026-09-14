# PRD: Approval Gate

**Slug:** `approval-gate` · **Type:** feat · **Owner:** aliz · **Date:** 2026-09-14
**Phase:** 2 (`docs/ROADMAP.md:307`) · **Capabilities:** builds on C1 (proxy, trace), C2
(sandbox/turn gate), C6 (corpus), C7 (console); no new C-id.
**Sources:** `docs/planning/_card/issue.md` (belay-next handoff, 2026-09-14),
`docs/planning/_card/understanding.md` (code-path dig).

---

## Problem Statement

An agent running unattended can call a tool that declares itself **destructive**
(`destructiveHint: true`) or **open-world** (`openWorldHint: true`) — deleting files,
hitting an external service — and nothing between the agent and the server can stop it.
Belay today can *record* that call (C1), *contain* it (C2), *judge* it after the fact
(A1/A2), and *watch* it live (C7 console) — but it cannot **hold it for a human
decision**. The roadmap names this gap as Phase 2's second goal: *"hold a risky action
(destructive, `openWorldHint`) pending human approval — the 'watch and steer'
surface"* (`docs/ROADMAP.md:307`).

The watch half already ships: the console (C7, v0.23.0) streams a live run feed. The
steer half does not exist — a grep across `src/belay/` and `console/` finds no approval,
hold, or pause concept (`understanding.md`). The one hold primitive that exists,
`_FrameHold` (`src/belay/proxy.py:202-291`), can only **delay** a frame until a hook
returns; it can never suppress one (`proxy.py:254` forwards unconditionally). A deny
path needs a new primitive.

The trigger facts are already captured and paid for: MCP tool annotations are recorded
per-tool as **tri-state** facts (`src/belay/declared.py:32-54`) — `declared-true` /
`declared-false` / `not-declared` / `declared-non-boolean` — with the explicit rule that
**a default is never a declaration**. The same facts that make annotation
contract-conformance a free verdict axis now make a zero-config hold possible.

**Evidence it matters:** R11 (*OSS adoption ≠ revenue*, Med/High, `ROADMAP.md:380`)
names the CI gate as the first surface with a named budget; this is the second, and it
is the live-control half of the surface the console built the watch half of. The
Phase-1→2 gate's demand-pull criterion (≥2 users asking for a shared/CI surface) is
**not met** — see Risks.

---

## Goals & Success Metrics

**Goal:** with the approval gate configured, a `tools/call` whose tool declares
`destructiveHint: true` or `openWorldHint: true` is held before it reaches the server
until a human approves or denies it; approve forwards the frame byte-identically, deny
returns a named JSON-RPC refusal to the client; the trace records the hold and the
decision as observations; nothing else about a run changes.

**Success metrics (all machine-checked by acceptance tests):**

- A configured gate holds exactly the declared-true calls; unconfigured runs are
  **byte-identical** to today (differential test).
- A deny never reaches the server and never corrupts the trace (no `frame` record for
  either direction, no `response-without-request`).
- The deadline is bounded and **fail-closed**: an unanswered hold denies with a named
  cause — an unattended agent can never block forever, and a timed-out hold can never
  silently forward a destructive call.
- `belay verify` reports approval events with absent-never-zero; **no verdict axis
  moves** (a denied call is not a turn, and is never rendered as any verdict).

---

## User Personas & Scenarios

- **The operator running an agent unattended (primary).** They wire
  `BELAY_APPROVAL_DIR` into the proxy environment, run their agent, and watch the
  approval requests appear. When the agent tries to delete a directory, the operator
  approves or denies; the agent receives a refusal and can adapt. Nothing in the
  agent's code changes — it is the same MCP boundary.
- **The CI/team user (secondary).** In CI there is no human, so the gate stays
  unconfigured and the run is byte-identical — the CI regression gate (`belay gate
  check`, v0.32.0) is the surface for that mode. The approval gate is for live runs.
- **The console (future consumer, not built here).** The watch surface becomes the
  steer surface: it reads `<dir>/requests/` and writes `<dir>/decisions/`. This slice
  ships the engine side of that contract; the UI wiring is deferred by name.

**Scenario (the load-bearing one):** an agent calls `delete_file` on a directory. The
tool declares `destructiveHint: true`. The proxy holds the request — the server never
sees it. The trace gains `approval_hold`. The operator denies. The proxy writes a
JSON-RPC error to the client with the request's id, the trace gains
`approval_decision` (deny, named cause), and the agent reads a refusal instead of a
success. No snapshot was taken, no turn was recorded, no verdict was manufactured.

---

## Requirements

### Must-have

- **M1 · Opt-in activation.** The gate is active iff `BELAY_APPROVAL_DIR` is set and
  names a usable directory; otherwise the proxy installs no approval hook and the run
  is byte-identical to today (pinned by a differential test). Fail-closed on a
  configured-but-unusable dir (refuse to start, like the existing env validation at
  `proxy.py:545-572`) — never a silently inactive gate.
- **M2 · Trigger vocabulary — positive declarations only.** A call is held iff the
  tool's **most recent observed** `tools/list` facts say `destructiveHint` is
  `declared-true` **or** `openWorldHint` is `declared-true`. `not-declared`,
  `declared-false`, `declared-non-boolean`, unknown tool, or no snapshot observed →
  forward untouched. This is the tri-state rule (`declared.py:32-54`): a default is
  never a declaration, and the gate is a supplement for honest-but-buggy servers
  (annotations are hints — `CLAUDE.md`), never an adversarial control.
- **M3 · Hold before forward.** The hold is inserted on the c2s direction **before**
  the frame is forwarded and **before** the turn gate's snapshot hook, so a denied
  call never reaches the server, never consumes a snapshot, and never enters the turn
  ledger. The s2c direction keeps draining while a hold is parked (the pumps are
  separate threads by construction — `proxy.py`), so a hold cannot wedge the pipe.
- **M4 · Decision channel (engine slice).** The proxy writes
  `<dir>/requests/<hold_id>.json` (hold id, tool name, params, request id, deadline)
  and polls `<dir>/decisions/<hold_id>.json` for `{"decision": "approve"|"deny",
  "reason": ...}`. Decision files are read atomically (write-temp-then-rename on the
  approver side; a partially-written file is retried, never guessed). Polling is
  bounded by `BELAY_APPROVAL_TIMEOUT` (default 300 s, configurable).
- **M5 · Fail-closed deadline.** Past the deadline the call is **denied** with the
  named cause `APPROVAL_TIMEOUT` and the refusal is returned — never forwarded. (The
  recorder's fail-open deadline exists for transparency — never lose a frame — and
  does not apply to a safety gate.)
- **M6 · Approve is byte-faithful.** On approve the held frame is forwarded
  **verbatim** (the `_FrameHold` guarantee: a hook may delay, never alter —
  `proxy.py:211-218`), and the server's response reaches the client byte-identically.
- **M7 · Deny is a named refusal, never a frame.** On deny the proxy writes a
  JSON-RPC 2.0 error to the client carrying the request's own id (code `-32000`,
  message naming the gate and the tool, `data` naming the hold id and cause). The
  suppressed request and the synthesized refusal are **never recorded as `frame`
  records** — they never crossed the server boundary; recording them would fabricate
  a crossing and produce `response-without-request`. The event is carried by additive
  record kinds instead (M8).
  **Mechanism constraint (the delicate part):** the recorder observes *chunks* in
  `_pump` (`proxy.py:359-373`), not frames, so suppression must extend to the
  observation path — the hook that decides a deny must also make the frame invisible
  to `_observe` for that chunk. The observation-suppression bookkeeping is
  frame-level and lives with the deny primitive; the no-config path never installs
  it and stays byte-identical. The decision record is written **before** the refusal
  bytes are handed to the client, so a client-observable refusal is never missing
  from the trace (the recorder's "forwarding never waits" contract applies to
  forwarding, not to a refusal the gate itself produces).
- **M8 · Trace observations — additive kinds, no schema bump.** Two new record kinds
  written through `TraceWriter.record` (the documented extension point,
  `trace.py:483-493`): `approval_hold` (written when a hold begins: hold id, tool,
  the triggering annotation states, request id, deadline) and `approval_decision`
  (written when decided: hold id, decision, cause, waited seconds). Old readers skip
  unknown kinds by contract (`replay/reader.py:139-152`); no `frame`, no
  correlation-machinery interaction, no park. A derived reader
  (`derive_approval_events`, mirroring `derive_annotations`) exposes them.
- **M9 · Per tool-call, not per request-id.** The hold keys on
  `method == "tools/call"` + `params.name`; the request id is carried for the refusal
  but never used as the hold identity. MRTR retries carry **new** request ids
  (`CAPABILITY_ROADMAP.md:43-62`); an id-keyed hold would be bypassed by the retry
  the spec mandates.
- **M10 · Reporting — absent-never-zero, no verdict change.** `belay verify` reports
  the trace's approval events (hold count, decisions by cause) on text and `--json`,
  absent-never-zero, with the coverage line discipline. A held/denied call produces
  **no verdict** on any axis — nothing ran; A1/A2/A3 and `verdict.reduce` are
  untouched. The verify JSON contract gains one additive section; the pinned snapshot
  fixture is updated deliberately and documented.
- **M11 · Import guard and zero deps hold.** The approval module is json-capable and
  is imported only at the composition root (`proxy.main` / `_contained_run`), exactly
  like `belay.sandbox.gate` (`proxy.py:617-618`); `proxy.py` itself stays
  serialiser-free (`tests/test_import_guard.py:114-140`). No new runtime dependencies.
- **M12 · Determinism.** No network, no sleeps beyond the poll interval, injectable
  clock for the deadline. The full proxy/trace-ordering suite
  (`tests/test_turn_gate.py`, `tests/test_trace_ordering.py`,
  `tests/test_differential.py`, `tests/test_capture_shutdown.py`,
  `tests/test_proxy_containment.py`) stays green.
- **M13 · Shutdown while a hold is parked.** If the writer closes, the client
  disconnects, or the proxy shuts down while a hold is pending, the hold resolves
  deterministically: it is denied with a named shutdown cause (or abandoned with a
  named record), never left without a decision, and the capture-shutdown discipline
  (`tests/test_capture_shutdown.py`; `BoundedPeek`/`_pump` exit paths) still holds.
  A parked hold must not delay process exit beyond the shutdown path's own bounds.
- **M14 · Deterministic race resolution.** A decision observed before the deadline
  wins; the deadline check and the decision check are ordered under one clock, so the
  same inputs always produce the same outcome. A decision file that arrives after the
  timeout deny is **ignored**, never applied retroactively; the late file is named in
  the record (or dropped by a named rule), never a silent re-decision.
- **M15 · Hold identity contract.** A hold id is deterministic, unique per hold,
  filesystem-safe, and meaningful to a human approver (carries the tool name and a
  monotonic sequence; the request id is carried alongside for the refusal). The
  sanitization follows the corpus `_safe_case_id` precedent (`corpus/add.py:122-150`).
  A retried call (MRTR, new id) is a **new hold**, never a reuse.
- **M16 · Approval requires tracing.** A configured approval gate with no trace
  destination is refused at startup (the observations must have somewhere to go) —
  the existing fail-closed env validation pattern (`proxy.py:545-572`), never a
  silently unrecorded hold.

### Should-have

- **S1 · Hold-start visibility.** `approval_hold` is written when the hold begins (not
  only at decision time) so a trace being tailed shows a pending hold live — the
  console's feed polls the trace and can render "awaiting approval" without a new
  channel.
- **S2 · Named causes on every decision.** `APPROVED`, `DENIED`, `APPROVAL_TIMEOUT`,
  plus a closed vocabulary for malformed/unreadable decisions — every denial has a
  cause a reader can name, never a bare boolean.
- **S3 · `belay verify` counts by cause** (not just total), so an operator can see
  "3 denied: 1 explicit, 2 timeouts".

### Nice-to-have

- **N1 · `belay approval list` / `belay approval decide` CLI helpers** that operate on
  a configured dir (thin wrappers over the file contract; no new channel).
- **N2 · Console wiring** — the watch surface reading requests and writing decisions.
  Deferred by name to a follow-on unit.

---

## Technical Considerations

**Architecture fit.** The hold hook already exists (`_FrameHold` + `before_frame`,
`proxy.py:202-291`); what is missing is a **deny primitive** — the forwarder contract
must grow a "suppress and substitute" outcome, produced by the approval module and
written as opaque bytes by the proxy. The composition root composes hooks in a chain:
approval (c2s) → turn gate (c2s), approval cache observer + turn gate (s2c). When no
approval dir is configured the hook is not installed and the path is the current
byte-identical one (`_forwarder`, `proxy.py:294-308`).

**Live annotation cache.** `derive_annotations` (`annotations.py:103-155`) is a
derived reader over a closed trace; the gate needs the facts **live**. The approval
module observes s2c `tools/list` responses (parsing a copy) and caches per-tool
tri-state facts; `notifications/tools/list_changed` invalidates the cache until the
next snapshot (the staleness rule, mirrored live). No trace-format change is needed
for this — the records it already writes stay the source of truth for after-the-fact
readers.

**Trace format.** Two additive kinds (`approval_hold`, `approval_decision`), no schema
bump — the `run_identity` precedent (`gate/baseline.py:135-233`). Non-frame kinds
deliberately: a synthesized refusal recorded as a `frame` would park 2.0 s in
`_await_request` and read as `response-without-request` (`trace.py:430-465`).

**Verdict impact.** None. No axis changes, no status is added, `verdict.reduce` is
untouched. A denied call is an **observation** (the agent attempted a risky action),
not a verdict — it never ran, so nothing can be verified. `UNVERIFIED`-never-`PASS`
holds trivially.

**Flag parity.** Any new flag shared by ≥2 replay-bearing surfaces must be declared in
`tests/test_cli_flag_parity.py` (`:42-134`); the approval config is env-only in this
slice, so the guard is checked, not widened, unless N1 lands.

**No raw-data egress.** The approval dir is on the user's box, path user-specified;
request/decision files carry tool params (the same data the user's own trace already
holds) and nothing is uploaded. The proxy remains stdio-only with no ports.

**Corpus.** Held/denied attempts are **not** banked as corpus cases in this slice.
`add_case` requires the target turn's `state_handle` to be `present`
(`corpus/add.py:338-349`) and `corpus run` recomputes MATCH by re-execution; a
never-forwarded call has no frame, no snapshot, and no re-executable verdict, so a
constructed expected would be structural, not grounded — a violation of the corpus's
own contract. The events are reported from the trace instead; banking is a named
follow-on (owner decision, 2026-09-14).

---

## Risks & Open Questions

| Risk | Mitigation |
|------|-----------|
| **R11 — demand-pull unmet** (the Phase-1→2 gate's ≥2-user criterion is not satisfied) | Engine slice only; no console/UI wiring; acceptance tests carry the shape so the surface can be re-cut when real reports arrive (the `ci-regression-gate` precedent). |
| **R10 — solo bandwidth** | Scope capped at the engine slice; banking and console deferred by name. |
| **The deny primitive touches the byte-transparency core** | The no-config path installs no hook and is byte-identical (differential test); approve forwards verbatim; deny is the only suppression and is recorded as non-frame observations. |
| **Deadlock / pipe wedge** | c2s-only hold; s2c pump keeps draining (separate threads); bounded deadline, fail-closed. |
| **MRTR retries bypass an id-keyed hold** | Holds key on `method` + tool name (M9); the trace record carries the request id it saw, never assumes stability. |
| **Approval channel abuse / malformed decisions** | Closed cause vocabulary; unreadable or unknown decision files are retried until the deadline, then denied with a named cause; no guessed approvals. |
| **The verify JSON contract change** | One additive section; snapshot fixture updated deliberately; absent-never-zero; documented on every surface. |

**Open questions (resolved at interview, 2026-09-14):**

1. **Banking** — deferred by name (owner decision); report from the trace instead.
2. **Deadline** — fail-closed deny (owner decision).
3. **Trigger set** — both `destructiveHint` and `openWorldHint` declared-true (roadmap
   wording, `ROADMAP.md:307`).
4. **Activation** — opt-in env; absent = byte-identical passthrough.
5. **Channel** — control directory (files), not a listener; the proxy stays stdio-only.

---

## Out of Scope

Console approval UI/wiring (N2) · corpus banking of held/denied attempts · adversarial
evasion (annotations are hints; the gate catches honest-but-buggy servers only) ·
holds driven by invariants, tool allowlists, or task specs (annotations only) ·
network/HTTP approval listeners · a hosted or multi-user approval service ·
`run_process`/shell special-casing (shell tools carry no annotations and are not
triggered) · changing any verdict axis, coverage line, or published number.

---

## Aspect Decomposition (proposed)

1. **`decision-model`** — the pure decision core: parse a c2s frame copy, match
   `tools/call`, resolve the tool's live annotation facts, decide hold/no-hold, and
   model hold state (pending → approved/denied/timeout) with the closed cause
   vocabulary. No I/O, no proxy coupling.
2. **`hold-channel`** — the approval directory contract: request file writes, atomic
   decision-file reads, bounded polling, injectable clock, fail-closed timeout; plus
   the live annotation cache observer for s2c `tools/list`.
3. **`proxy-deny`** — the forwarder contract change (suppress-and-substitute), hook
   composition at the composition root (approval before turn gate on c2s), the
   byte-identical no-config path, the JSON-RPC refusal, and the import guard.
4. **`trace-observations`** — the additive record kinds (`approval_hold`,
   `approval_decision`), the derived reader, reader-skip compatibility, and the
   trace-ordering suite staying green.
5. **`verify-report`** — `belay verify` text/`--json` reporting of approval events,
   absent-never-zero, the additive JSON section, snapshot fixture update, docs
   (README + `TRACE_FORMAT.md`).

Each aspect is independently shippable in order; 2 depends on 1, 3 on 1+2, 4 on 1+3,
5 on 4.

---

## Self-Critique (prd-generator review, 2026-09-14)

**Scorecard:** Problem Definition 🟢 · User Understanding 🟡 · Success Metrics 🟢
(machine-checked by design) · Scope Clarity 🟢 · Edge Cases & Risks 🟡 · Stakeholder
Alignment 🟢 · Feasibility Signal 🟢 · Go-to-Market 🟡.

**Top gaps, closed in this revision:**

- 🔴 **The deny primitive's observation path** — the recorder sees chunks, not
  frames, so suppressing a frame from the trace is not free; M7 now states the
  mechanism constraint and the write-before-refusal ordering. The plan must pin the
  frame-level bookkeeping; a differential test keeps the no-config path honest.
- 🟡 **Shutdown while parked** — M13 added: bounded, deterministic, named.
- 🟡 **Deadline/decision race** — M14 added: one clock, decision-before-deadline
  wins, late files never re-decide.
- 🟡 **Hold identity** — M15 added: deterministic, sanitized, per-tool-call.
- 🟡 **Approval without a trace destination** — M16 added: fail-closed at startup.

**Remaining honest weaknesses (not papered over):**

- **User validation is absent by construction** — no demand-pull (R11); the persona
  is the roadmap's, not a user's. The slice's contract is that acceptance tests carry
  the shape until real reports arrive.
- **No outcome metric** — "success" in this slice is the feature working correctly,
  not adoption; adoption metrics live at the Phase-2 gate where they belong.
- **The timeout default (300 s) and the poll interval (0.1 s) are product guesses** —
  named in M4/M5, re-cuttable when the console lands.

**The question I'd want answered before greenlighting:** *if a human is required to
unblock a destructive call, what does the agent do when the gate denies — and is
"the agent read the refusal" a property this slice should pin, or is it the agent's
problem?* This slice pins only that the refusal is delivered with the request's own
id; whether the agent handles it is out of scope by construction (we wrap, never
author), but the demo/console follow-on will need a story for it.
