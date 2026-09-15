# Approval Gate — unit card

> `gh` issue not used — `approval-gate` is a slug, not a numeric issue id (no GitHub
> issue exists for this work). Source is the inline brief below, produced by the
> `belay-next` skill handoff (2026-09-14) and executed by the owner.

## Brief

Build Phase 2's second goal (docs/ROADMAP.md:307): the proxy holds a tools/call whose
tool declares destructiveHint or openWorldHint (tri-state — absent is never a trigger)
pending human approval — the "watch and steer" surface whose watch half (C7 console)
already ships. Engine slice first, console/UI wiring later; the hold is a gate before
forwarding, never a conversation model, and the trace must record the hold/deny as
observations (additive record kind, no schema bump — the gate precedent). Caveat: no
demand-pull yet, so keep wiring minimal and let acceptance tests carry the shape; the
hold must not deadlock the pipe or regress trace-ordering (park the response like the
recorder parks s2c), and holds are per tool-call, not per request-id, or MRTR retries
bypass them. Test-first acceptance: (1) a destructive-annotated call blocks until
approved, unannotated calls pass through untouched; (2) approval resumes and the
recorded response reaches the client byte-identically, deny returns a named refusal;
(3) held/denied attempts bank as trajectory-shaped corpus cases and recompute MATCH;
(4) absent-vs-declared-false is never confused (a default never manufactures a hold);
(5) deterministic, no network, runs in CI.