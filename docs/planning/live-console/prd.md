# PRD: Live console (launch checklist L6 / C7)

Slug: `live-console` · Branch: `feat/live-console/aliz` · Type: feat · Owner: aliz
Sources: `docs/planning/_card/issue.md` (brief), `docs/planning/_card/understanding.md`
(dig), `docs/planning/launch-readiness/CHECKLIST.md` item L6,
`docs/technical/CAPABILITY_ROADMAP.md` §C7.

## Problem Statement

The launch demo is CLI output and gifs: the moat is real but **not legible**. C7 — the
live console — is the surface through which the moat is seen
(`CAPABILITY_ROADMAP.md:712-714`): a green Langfuse trace beside Belay's red turn-7
verdict is the launch visual. It is also the "watch and steer" primitive the Phase-2
team/approval layer grows out of. Nothing renders verdicts today except the human-text
CLI — there is no frontend, no `verify --json` structured output, no streaming source
beyond the append-only trace file, and no click/override machinery (all confirmed in the
dig, `understanding.md` §Ground facts).

## Goals & Success Metrics

1. **C7 acceptance, as tests:** a recorded trace renders every turn with its verdict and
   the FAILed turn shows its diff; an UNVERIFIED turn **renders distinctly from PASS** —
   a snapshot/DOM test, correctness not style (`CAPABILITY_ROADMAP.md:729-733`); the
   console works fully offline against a local trace.
2. **The honesty contract gains a surface, machine-checked.** Every console surface
   renders the status with its coverage line, and the `verify --json` seam carries the
   same verdicts, sub-verdicts, UNVERIFIED causes and coverage line the human report does
   — a PASS without its coverage line in the JSON is a test failure (the repo's
   one-test-per-surface rule, `tests/test_coverage_rendering.py`, extended to a new
   surface).
3. **Streaming live feed:** a capture in progress (trace-*.jsonl being appended) shows
   turns as they land, via a file tail — no engine event stream.
4. **Replay-from-here:** any past turn re-runnable from the console
   (`belay verify --turn N` / `belay replay --turn N` primitives exist,
   `cli.py:2068-2073, 2101-2106`).
5. **Eval data starts:** which turns a human expands/clicks is logged locally (on-box
   JSONL, no egress) — C7's "first signal of where our verdicts are unconvincing"
   (`CAPABILITY_ROADMAP.md:735-736`).

## User Personas & Scenarios

- **The PH launch audience**: watches the demo — a real agent run, live, with a red
  verdict where the dashboard didn't notice. The console is the visual.
- **The stranger evaluator** (Phase-1 gate, ≥3 external self-hosters): installs Belay,
  captures their own agent run, opens the console on their box, and *sees* the verdicts
  with the coverage line — offline, local-first.
- **The operator** (the "watch and steer" user): follows a long run as it streams, opens
  a FAILed turn's diff, replays a turn from the console, and sees what was NOT_COVERED.

## Requirements

### Must-have

- **M1 · `belay verify --json` (engine seam, test-first).** A structured output flag on
  `belay verify` that emits the same verdict data the human report renders — per-turn
  reduced status, every sub-verdict (A2 replay, A2 effect, A2 effect:network NOT_COVERED,
  A1 invariants) with its message, the aggregate, the coverage line, exposure facts,
  trajectory disposition, and the exit code semantics (FAIL/UNVERIFIED exits non-zero,
  unchanged). Built by rendering the JSON **from the same structured objects** the human
  renderer consumes (one computation, two renderers — never two verdict computations).
  The honesty contract applies to the machine surface: a JSON record whose status is PASS
  and whose coverage line is absent fails a test. Stdlib-only (`json`), zero-dep
  preserved, covered by `tests/test_coverage_rendering.py`-style tests plus a
  JSON-shape test. `interop correlate --json` is the precedent
  (`cli.py:2587-2591`). **Two hardening clauses: (a) the JSON is always valid JSON** —
  on an internal failure the command emits no half-written document and exits non-zero
  (or emits an explicit `{"error": ...}` record; decided by test), and (b) the JSON and
  the human report are rendered from the same objects (one computation, two renderers)
  — a divergence between them fails a test.
- **M2 · The console app (Vue 3 + Vite + TypeScript, new `console/` tree).** A
  local-first SPA whose dev server (a) serves the app, (b) tails `trace-*.jsonl` files
  (append-only per `TRACE_FORMAT.md:22-24` — safe to read mid-run), (c) shells out to
  the local `belay` CLI for `verify --json` and per-turn replay. Nothing leaves the box.
  Per-worktree `npm install`; `node_modules`/`.next` already gitignored (`.gitignore:47-49`).
- **M3 · Trace rendering.** A trace (or a directory of traces) loads and renders every
  turn: tool name, arguments, result, annotations (from the derived
  `annotation_snapshot`), timing — decoded from frames per `TRACE_FORMAT.md:62` (human
  rendering is the console's job). Verdicts attach when the engine computes them
  (`verify --json`); the trace itself holds none (`TRACE_FORMAT.md:367-368`) and the
  console never computes verdicts itself. **Trace rendering never requires the engine
  binary to be present**: without it (or before a verify run), turns render as
  unverified-by-cause ("no engine / not yet verified"), clearly distinct from PASS and
  from UNVERIFIED — the trace view works alone; verdicts attach when available.
- **M4 · Verdict rendering is the honesty contract.** Per-turn status + the coverage line
  on every console surface; UNVERIFIED has its own distinct visual treatment and is
  never colored, grouped, or summarized as PASS (C7 acceptance #2 as a snapshot/DOM
  test); NOT_COVERED sub-verdicts render as coverage boundaries, never as PASS.
- **M5 · Streaming live feed.** A capture running with `BELAY_TRACE_DIR` pointed at a
  watched directory streams turns into the feed as the file tail advances. Honest
  mid-run state: a partially written final line renders as pending, never as a verdict.
- **M6 · FAILed-turn diff.** The FAILed turn shows the concrete diff from the
  sub-verdict messages (result-equivalence diff, invariant diff).
- **M7 · Replay-from-here.** A per-turn action that re-runs that turn
  (`belay verify <trace> --turn N --manifest-dir <dir> --server ... --json`) and shows
  the verdict; the server/manifest-dir come from the run's recorded context or are
  supplied in a run dialog; a turn that cannot replay renders honest UNVERIFIED with its
  named cause (never a fabricated result).
- **M8 · Local click/expand log.** Every turn-expand / diff-open click is appended to a
  local JSONL (e.g. `~/.belay/console-events.jsonl`): trace id, turn ordinal, event
  kind, ISO timestamp. On-box only; no egress. This is C7's eval-data first slice.
- **M9 · Offline, deterministic console tests.** The console's test suite runs fully
  offline against committed fixture traces: snapshot tests for rendering, component
  tests for the honesty contract, no network, no clock dependence (timestamps injected).

### Should-have

- **S1 · Compose service + healthcheck.** The `console:` service lands in
  `docker-compose.yml` with a `Dockerfile` (console tree) and the `HEALTHCHECK` the L3
  deferral ties to C7's existence (`CHECKLIST.md:189-190`); the compose regression test
  flips from "console named but not shipped" (`tests/test_docker_compose.py:91-102`) to
  asserting the service exists with a healthcheck.
- **S2 · Docs join the surface list.** README's coverage-surface statement
  (`README.md:189`) gains the console; `CAPABILITY_ROADMAP.md` §C7 status;
  CLAUDE.md status line; the `verify --json` output shape documented where the human
  report is.
- **S3 · Aggregate strip.** A live aggregate header (PASS/FAIL/UNVERIFIED counts +
  coverage) over the streaming feed.

### Nice-to-have

- **N1 · `belay replay --json`** — structured UNVERIFIED-rate report for the console's
  replay panel (the replay-from-here path can use `verify --turn N --json` today).
- **N2 · Trace-directory picker** in the UI (choose which capture to watch).

## Technical Considerations

- **Capability placement:** C7, Phase 1, launch surface (`CAPABILITY_ROADMAP.md:710-738`);
  dependencies C1–C6 all built. Not cuttable.
- **Verdict impact:** **none on any axis.** No A1/A2/A3 change, no reduction-rule change,
  no trace-format change. M1 adds a *structured rendering surface*; the one-computation
  rule (JSON and human text from the same objects) is what keeps it honest.
- **Zero-dep guardrail:** the engine stays zero-dep (M1 uses stdlib `json`); the console
  is a separate npm project with its own deps (Vue, Vite, TypeScript, test tooling).
- **Determinism:** console tests offline; fixture traces committed under
  `console/` test fixtures (traces are small; the no-raw-data-egress guardrail governs
  *user* run data — fixtures are synthetic, deliberately NOT lifted from real captures,
  so committing them touches no raw data).
- **Feasibility (effort):** three aspects — A1 `verify-json` engine seam (test-first,
  ~1 day, no new deps), A2 `console-app` (Vue 3 + Vite + TS SPA with tail/verify/replay,
  ~3–5 days including its test suite), A3 `compose-healthcheck` + docs (~0.5 day, after
  A2). The seam and the app can proceed in parallel after the seam's shape is pinned by
  its first test. This is the largest remaining unit; R10 is managed by the narrow slice
  (no engine server, no overrides, no SSR).
- **Engine/console boundary:** the console shells out to the local `belay` CLI. No engine
  API server in this slice. This keeps the engine a stdio tool and the console a thin,
  honest renderer.
- **Corpus note, stated honestly:** this unit adds no corpus cases — it is a renderer,
  not a detector. Its eval-data contribution is the click/expand log (M8), which is the
  first instrument on *"where our verdicts are unconvincing rather than merely wrong"*;
  the corpus itself compounds via the external-self-hoster reports the console enables.
- **Streaming mechanics:** file tail by size/offset polling (or `fs.watch` fallback),
  JSONL line-parse tolerant of a trailing partial line.
- **The launch gate:** L6 ✅ requires the C7 acceptance + the console being the demo
  visual (L7's demo gif replaces the current one — L7 is a separate item, but the console
  is its substrate).

## Risks & Open Questions

- **R5 (over-claiming what A2 proves) — the console is where UNVERIFIED-as-PASS would be
  most damaging.** Mitigation: acceptance #2 is a snapshot/DOM correctness test, the
  coverage-line-per-surface rule extends to every console surface by test, and the
  `--json` seam carries coverage + named causes. This is the load-bearing risk and the
  PRD's hardest requirement is the tests around it.
- **R10 (solo-founder bandwidth)** — the narrow slice is the mitigation: Vue+Vite (no
  SSR), no engine server, no overrides. The console is a focused SPA, not a platform.
- **The `verify --json` shape is a new machine contract** — it must be pinned by test
  from day 1 (a fixture JSON snapshot) so the console and future consumers don't drift
  against it.
- **Open:** where the console reads traces by default (a watch dir arg vs
  `~/.belay/traces` vs the run's `BELAY_TRACE_DIR`) — decide in the plan; the console
  takes an explicit dir argument.
- **Open:** the replay-from-here dialog's server/manifest sourcing (recorded
  `source_root`/server command vs user-supplied) — the console must not fabricate
  context; missing context renders a named-cause UNVERIFIED.

## Out of Scope

- **Approval/override capture** — Phase 2 (the approval gate, `ROADMAP.md:296`); the
  click log (M8) is the eval-data first slice, not an override mechanism.
- **C8 (A3) verdict rendering** — A3 is unshipped and cuttable; when it lands, its
  distinct rendering requirement (`CAPABILITY_ROADMAP.md:723-727`) extends the console.
- **Any engine change beyond the `verify --json` seam** — no API server, no event
  stream, no verdict-logic change, no trace-format change.
- **Multi-user, cloud, auth, OTel export-back** — later phases.
- **A second ingest surface** — the wedge is locked to MCP.