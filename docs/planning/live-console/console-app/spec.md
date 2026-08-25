# Aspect: console-app (A2)

Part of `docs/planning/live-console/prd.md` (launch checklist L6 / C7). The console
itself: the launch surface.

## Problem slice

Nothing renders verdicts beyond the human-text CLI; the moat is not legible and the PH
demo is CLI output and gifs. This aspect builds the local-first Vue 3 + Vite + TS SPA
that streams a live run feed and renders past traces offline, with the honesty contract
as the load-bearing spec.

## In-scope requirements (PRD M2–M9, S3, N2)

- `console/` tree: Vue 3 + Vite + TypeScript; per-worktree `npm install`; `node_modules`
  gitignored.
- A local server (node) that: serves the built SPA; lists/reads `trace-*.jsonl` files
  (decodes frames → per-turn data per `TRACE_FORMAT.md`); tails a live trace (append-only
  JSONL, partial final line = pending, never a verdict); shells out to the local `belay`
  CLI for `verify --json` (A1) and per-turn replay (`verify --turn N --json`); streams
  the feed (polling or SSE — decide in the plan; offline and simple).
- The SPA: live feed view (streaming turns + live aggregate), trace view (every turn:
  tool, args, result, annotations, verdict, diff on FAIL), replay-from-here dialog,
  coverage line on every surface, UNVERIFIED distinct treatment.
- Local click/expand log: appends to `~/.belay/console-events.jsonl` (trace id, turn
  ordinal, event kind, ISO timestamp) — on-box only.
- Tests: Vitest + Vue Test Utils, fully offline against **synthetic** fixture traces
  (deliberately not lifted from real captures); the honesty contract as correctness
  tests: UNVERIFIED renders distinctly from PASS (snapshot/DOM), every surface carries
  the coverage line, NOT_COVERED renders as a boundary never as PASS.
- A console CI job (npm ci → vitest → vite build) on the pinned ubuntu-24.04.

## Out of scope

- Approval/override (Phase 2), auth, cloud, multi-user, C8/A3 rendering, an engine API
  server, `belay replay --json` (N1 — replay uses `verify --turn N --json`).

## Acceptance criteria (test-first — the C7 acceptance, as component tests)

1. A fixture trace renders every turn with its verdict; the FAILed turn shows its diff
   (from the `verify --json` sub-verdict messages).
2. **An UNVERIFIED turn renders distinctly from PASS** — a snapshot/DOM test asserting
   the two render differently (different element/class, never grouped under a
   "passed"/"ok" summary): correctness, not style.
3. The console works fully offline against a local trace (no network; the engine binary
   absent → turns render as unverified-by-cause "no engine", distinct from PASS and
   from UNVERIFIED).
4. Every console surface renders status + coverage line; a rendered PASS without its
   coverage line fails a test.
5. The live feed shows turns as the trace file appends (tail test with an in-test
   append), and a partial final line renders as pending, never as a verdict.
6. Replay-from-here invokes the engine with the recorded/supplied context and renders
   the verdict; missing context → named-cause UNVERIFIED, never fabricated.
7. The click/expand log appends exactly one JSONL record per user click (injected
   clock, tmp dir).
8. `npm run test` green offline; `npm run build` succeeds; the CI job green.

## Dependencies & sequencing

- Depends on A1 (`verify --json`) for verdict data — A2's server tests use the real
  engine once A1 GREEN; until then the pinned A1 fixture snapshot stands in.
- After A2: A3 (compose service) consumes the built console.

## Open questions / risks

- The engine binary location for the server's subprocess calls: `belay` on PATH vs
  `uv run belay` in the repo — decide in the plan (PATH-first, configurable; the dev
  server must not require the repo venv).
- R5 is the load-bearing risk — the honesty tests are acceptance #1/#2/#4, not style
  extras.