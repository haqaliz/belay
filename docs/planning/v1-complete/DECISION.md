# Decision — v1 is complete; the rest of the roadmap is post-traction

**Date:** 2026-10-21 · **Release:** v1.0.1 · **Status:** accepted

## What this decides

The **buildable** roadmap is complete. There is no code left to write honestly before
traction: every remaining phase goal is gated on users, a target agent, or revenue, and
building it now would be scaffolding for a user who does not exist.

## What is done

- **Phase 0** — the gate PROCEEDed (n=60, 11 independent hand-audited TPs, 18.3%).
- **Phase 1** — launch checklist L1–L8, the console, the demo, PyPI + GHCR channels.
- **C1–C10** — capture, sandbox, replay, A2, A1, corpus, console, A3, interop, triage.
- **Phase 2 first slices** — CI regression gate, approval gate (engine + console),
  invariant authoring, and the corpus pattern catalog.
- **The 1.0 line** — live OTLP/JSON export, N-document ledger aggregation, budget
  suggestion, console approvals, shared pattern catalog, stale-contract abstention.

## What remains, and why it is not built

| Item | Gate that is not met |
|---|---|
| Second surface past the MCP boundary (#59) | ≥2 recorded user requests. Building one now also requires picking one agent (Claude Code? Cursor?) — the "become an agent framework" trap. |
| Team corpus query server | Multi-user identity and persistence: the Phase-3 control plane, not a local-first slice. |
| Phase 3 (control plane, SSO/VPC/audit, flywheel, published benchmark) | A paying team and real production runs. |
| Phase 1 → 2 gate | 3 external self-hosters catching a real failure; 2 explicit CI-surface requests. |

## Reopen triggers

- **#59:** two recorded requests (issues or links) for a non-MCP surface, plus a named
  agent to test against.
- **Team corpus:** a team asks for shared, queryable cases and accepts a server component.
- **Phase 3:** the first paying team.

## What this does not do

It does not claim the roadmap is "done" as a business, and it changes no verdict, axis,
status, coverage line or published number (`11/60 = 18.3%`, `precision 0.00`, `1/15`,
`4/16`, `recall 0.00`, `3/93` stand unedited). It is a stop on speculative building, not a
claim of completeness.
