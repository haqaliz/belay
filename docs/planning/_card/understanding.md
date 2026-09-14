# Approval Gate — understanding note

Source: `docs/planning/_card/issue.md` (belay-next handoff, 2026-09-14).
Research: full code-path map in the session report (proxy, trace, annotations,
index, gate, corpus, cli, console, MRTR).

## What the work really is

Phase 2's second goal (`docs/ROADMAP.md:307`): the MCP stdio proxy holds a
`tools/call` whose tool declares `destructiveHint: true` or `openWorldHint: true`
(tri-state — absent is never a trigger) pending human approval; approve forwards the
frame verbatim, deny returns a named refusal to the client. The trace records the
hold/deny as observations. The console (C7) is the natural approval surface but the
engine slice ships first — wiring minimal, acceptance tests carry the shape.

## Key findings (file:line)

- **The hold hook already exists.** `_FrameHold` + `before_frame` (`proxy.py:202-291`)
  reassembles frames and delays forwarding until the hook returns; forwarding is
  otherwise unconditional (`proxy.py:254`) and the proxy cannot parse JSON
  (`tests/test_import_guard.py:114-140`). A DENY needs a new primitive: suppress the
  forward and write refusal bytes (produced by a json-capable module imported at the
  composition root, exactly like `belay.sandbox.gate` at `proxy.py:617-618`).
- **Trigger vocabulary is captured.** Tri-state facts in `declared.py:32-54`
  (`declared-true` / `declared-false` / `not-declared` / `declared-non-boolean`); the
  four annotations incl. `destructiveHint`/`openWorldHint` are captured per-tool in
  `annotation_snapshot` (`annotations.py:60-81`). A default is never a declaration.
- **Hold/deny records must be additive non-frame kinds.** `writer.record(kind, ...)`
  is the documented extension point (`trace.py:483-493`); unknown kinds are skipped
  by old readers (`replay/reader.py:139-152`), the `run_identity` precedent
  (`trace.py:65`, `gate/baseline.py:135-233`). Recording a synthesized refusal as a
  `frame` would park 2.0 s in `_await_request` and read as `response-without-request`
  — the hold/deny carrier must be a new kind, never a frame.
- **Holds are per tool-call, never per request-id.** MRTR retries carry NEW ids
  (`CAPABILITY_ROADMAP.md:43-62`; `index.py:42-58`) — an id-keyed hold is bypassed
  by the retry the spec mandates. Key on `method == "tools/call"` + `params.name`.
- **Deadlock analysis is favorable.** The c2s pump parking on approval cannot wedge
  the pipe: the s2c pump is a separate thread that keeps draining the server, and
  the client is blocked on its own read, not on the proxy. The bounded-deadline
  discipline still applies (a parked c2s frame delays nothing on s2c, but an
  unattended agent must not block forever → deny on deadline, fail-closed).
- **Banking wrinkle (open question).** `add_case` requires the target turn's
  `state_handle` to be `present` (`corpus/add.py:338-349`) — a never-forwarded call
  has no frame record, no snapshot, and no re-executable verdict. Constructing an
  expected verdict for something that never ran would violate the honesty contract.
  Recommend: hold/deny as trace records + named reporting (absent-never-zero) on the
  verify surface; banking deferred by name until a case shape is decided.
- **No approval concept exists anywhere** (`src/belay/`, `console/` — grep zero
  hits). Clean slate; `_FrameHold` is a delay only, never a refusal.
- **Flag parity guard** (`tests/test_cli_flag_parity.py`): any new approval flag
  shared by ≥2 replay-bearing surfaces must be declared there.

## Verdict axis

None of A1/A2/A3 emit a verdict for a held call — nothing ran. The approval gate is
a **containment** surface (the sandbox axis): it prevents execution rather than
judging it. Deny is an observation (the agent attempted a risky action), never a
verdict; UNVERIFIED-never-PASS and the coverage line discipline apply to any
reporting surface.

## Open questions

1. Trigger vocabulary — both `destructiveHint` and `openWorldHint` declared-true?
2. Deadline semantics — fail-closed deny (recommend) vs fail-open forward?
3. Approval channel for the engine slice — control file/dir polling vs named pipe
   vs HTTP listener (console wiring later)?
4. Banking — defer by name (recommend) vs a constructed case shape?
5. Refusal shape — JSON-RPC error with the request's id; which code?
6. Activation — env toggle, absent = byte-identical passthrough (recommend)?