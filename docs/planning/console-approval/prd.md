# PRD — console approval UI

**Issue:** #55 · **Slug:** `console-approval` · **Branch:** `feat/55/aliz`

## Problem

The engine approval gate is shipped and headless: a risky `tools/call` is held pending a
human decision through a file contract (`BELAY_APPROVAL_DIR/requests/<hold_id>.json` →
`decisions/<hold_id>.json`). Today a human must write that JSON by hand. The console
wiring was deferred by name at `approval-gate` (2026-09-15).

## What ships

**Server** (`console/src/server/`):

- `ServerConfig.approvalDir` from `BELAY_APPROVAL_DIR` (optional).
- `GET /api/approvals` → `{configured, holds: [...]}`. A hold is *pending* when its request
  file exists, no decision file exists, and `now < created_at + timeout`. Malformed request
  files are skipped (never crash the list); expired and decided holds are not listed.
- `POST /api/approvals/decision` `{hold_id, decision: "approve"|"deny", reason?}`:
  - hold id validated against `^[A-Za-z0-9._-]+$` and checked inside the approval dir;
  - 409 `approval-not-configured`, `hold-not-found`, `hold-expired`, `already-decided`;
  - 400 `bad-decision` / `bad-hold-id`;
  - write is atomic (temp file in `decisions/` + rename) and matches the engine contract
    exactly: `{"decision": ..., "reason"?: ...}`.
- No catch-all exists in the router; the new handlers own their errors.

**UI** (`console/src/components/ApprovalPanel.vue`):

- Polls `/api/approvals` (1 s) while mounted; renders nothing when `configured` is false.
- Per hold: tool, triggers, created time, a countdown to `created_at + timeout`; Approve and
  Deny buttons; a reason field for deny.
- Past the deadline the buttons disable and the row reads `timed out — the engine fails
  closed`; the UI never claims the call was verified or denied by it.
- On a 409 the row refreshes from the server (no optimistic state).

**Compose:** both services get `BELAY_APPROVAL_DIR` pointing at a shared
`/workspace/approvals`; the engine already has `BELAY_TRACE_DIR` (required).

## Non-goals

- No change to the engine, the file contract, or verdicts. A denied call stays an observation.
- No call arguments in the UI — the request file does not carry them.
- No history view of decided/expired holds, no notifications, no websockets (polling only).
- No approval over HTTP for the engine (stdio/file contract unchanged).

## Acceptance criteria

1. With a request file and no decision, `GET /api/approvals` lists it with tool/triggers and
   `expires_at`; with a decision file it is absent.
2. A request past `created_at + timeout` is absent and its decision is refused 409
   `hold-expired` (late decisions are dead — the engine ignores them).
3. Approve/deny writes exactly the contract JSON, atomically; a second write is 409
   `already-decided`.
4. `hold_id` traversal (`../x`, slashes, empty) → 400; unknown id → 409.
5. Malformed request JSON and a missing approvals dir never break the list.
6. Unconfigured server: `configured: false`, empty list, decision 409.
7. UI: renders holds, disables at the deadline, shows the fail-closed text, and refreshes on
   409; no test asserts a verdict for a held call.
8. Compose passes the shared approval dir to both services.

## Risks

- **R-a:** request files accumulate forever. Mitigated by filtering to pending only; cleanup
  stays out of scope (the engine never deletes them).
- **R-b:** `created_at` is wall clock, so a countdown can drift from the engine's monotonic
  deadline. Mitigated: the UI treats expiry as advisory, and the server refuses late writes.
- **R-c:** a decision can race the engine's timeout. Accepted: the engine re-checks and its
  fail-closed rule wins; the UI never decides a verdict.

## Open questions

- 🟡 **Q1:** show expired holds for a short grace window? Proposed: no — pending only.
