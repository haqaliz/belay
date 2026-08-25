# Understanding: Live console (launch checklist L6 / C7)

Phase 2 dig for the L6 unit. Sources: `docs/planning/_card/issue.md` (brief), the read-only
research pass over `docs/technical/CAPABILITY_ROADMAP.md` §C7, `docs/technical/TRACE_FORMAT.md`,
`src/belay/cli.py`, `src/belay/trace.py`, `tests/test_coverage_rendering.py`,
`docker-compose.yml`, `docs/planning/launch-readiness/CHECKLIST.md`, and `docs/ROADMAP.md`.

## What this work really is

C7 is **the launch surface** — the visual a Product Hunt launch demos (the demo today is CLI
output and gifs). It is explicitly *not the moat*: "the surface through which the moat is
legible" (`CAPABILITY_ROADMAP.md:712-714`). It is **not cuttable** (sequencing table:
"C7 | Live console | Wk 5–6 | 1 | No — the launch surface", `CAPABILITY_ROADMAP.md:865`).

Per §C7 the console is: local-first, self-hosted, TypeScript (Next.js or Vue); a streaming
per-turn feed (tool call, args, verdict, and the diff where FAILed); **the verdict rendering
is the honesty contract made visible** (UNVERIFIED distinct, never grouped as PASS; the
coverage line travels with the status); replay-from-here (any past turn re-runnable).
Acceptance: trace renders every turn + FAILed turn shows diff; **UNVERIFIED rendered
distinctly from PASS — a snapshot/DOM test, correctness not style**; fully offline against a
local trace. Dependencies C1–C6 — all met.

## The ground facts that shape the design

1. **Verdicts are NOT in the trace.** "Nothing in this format is a verdict"
   (`TRACE_FORMAT.md:367-368`). Verdicts are computed by `belay verify`/`phase0 run`/`corpus
   add` (`verify_turn`, `src/belay/verify/turn.py:205`). A console therefore must either
   shell out to the engine or reimplement it — the engine owns verdicts, always.
2. **The only structured CLI output today is `interop correlate --json`.** `belay verify`
   and `belay replay` emit human text only (`cli.py:676` `_emit_verdict`, `:917`
   `_emit_coverage`, `:956` `_emit_aggregate`). There is no `--json` for verify — the C7
   card's open question. A machine-checked culture (the repo's) argues for a real
   structured seam rather than parsing human text.
3. **The trace is append-only JSONL** (`TRACE_FORMAT.md:22-24`; `trace-*.jsonl`, created
   0600) — "safe to read while a run is still in progress". The natural streaming source is
   a **file tail** of the live trace; no watch command or event stream exists in the engine
   (confirmed: none anywhere in src/).
4. **A server command is required for real verdicts** (`--server` + `--manifest-dir`;
   without it everything degrades to named-cause UNVERIFIED). "Offline" means local
   subprocess server, never network. The console must surface this boundary, not hide it.
5. **The honesty contract is enforced one test per surface** in
   `tests/test_coverage_rendering.py` (597 lines, 11 surfaces enumerated). The console adds
   a new surface — the same rule applies, and C7's acceptance #2 (UNVERIFIED ≠ PASS,
   snapshot/DOM test) is the console's version of it. `README.md:189` states the surface
   list; the console must join it.
6. **Replay-from-here already has its primitive**: `belay replay --turn N` and
   `belay verify --turn N` (0-based, `cli.py:2068-2073, 2101-2106`).
7. **No frontend exists** — no console/dashboard dir, `.gitignore` pre-stages
   `node_modules/`, `.next/`; `docker-compose.yml:11-15` names the console as a comment
   only and `tests/test_docker_compose.py:91-102` regression-guards that it stays a comment
   until C7 ships. When C7 lands, the compose `console:` service joins and the deferred
   Docker HEALTHCHECK becomes right (`CHECKLIST.md:189-190`).
8. **No click/override machinery exists** — the eval-data intent (which turns humans click
   into, which verdicts get overridden) is greenfield; overrides are Phase-2 scope
   (`ROADMAP.md:296` — the approval gate).

## Strategic constraints

- **Not an agent framework, not an LLM judge** — a renderer of engine verdicts; orthogonal
  by construction. The engine owns verdicts; the console never computes them.
- **No raw-data egress** — local-first; the console reads local traces and writes its own
  local state only. Never uploads.
- **Honest verdicts only** — this is the console's *raison d'être*; the coverage line +
  UNVERIFIED-distinctness are acceptance tests, not style.
- **R10 (bandwidth)** — the console must be a narrow first slice, not a platform.
- **Determinism** — the console's own tests (snapshot/DOM) run offline against fixture
  traces; no network, no clock.

## Verdict-axis placement

**None — the console renders existing verdicts.** It changes no axis (A1/A2/A3), no trace
format, no verdict computation. It may add a *structured output seam* to the engine
(`verify --json`) — a rendering surface, not a verdict change; the reduction rule and the
statuses are untouched (the `--json` must carry exactly what the human report does,
including the coverage line — the honesty contract applies to the machine surface too).

## Open questions for the PRD interview

1. **Framework**: Vue 3 + Vite + TS (founder's primary stack; leanest fit for a
   local-first offline SPA) vs Next.js (heavier; SSR is not needed offline).
2. **Engine interface**: add a test-first `belay verify --json` structured seam (matches
   the interop `--json` precedent and the machine-checked culture) vs parse the human
   report (fragile) vs the console computing verdicts itself (rejected — the engine owns
   verdicts).
3. **Streaming**: file-tail of the append-only trace (zero engine change; the honest
   source) vs an engine-published event stream (new machinery).
4. **Watch-and-steer scope in this slice**: replay-from-here only (approval/override is
   Phase 2 per ROADMAP) vs pulling override capture in now.
5. **Eval-data capture**: a local click/expansion log (on-box, first signal of
   unconvincing verdicts) vs defer entirely.
6. **Compose/healthcheck**: land the `console:` service + HEALTHCHECK with C7 (the L3
   deferral note says it becomes right when C7 exists) or defer to a follow-on slice.