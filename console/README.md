# belay console (C7)

Local-first Vue 3 + Vite + TypeScript console for the Belay engine: a live run
feed and per-turn verdicts, rendered with the honesty contract as the load-bearing
spec — UNVERIFIED is never PASS, NOT_COVERED is a boundary, and every surface
carries its coverage line.

## Run

```bash
npm install        # once per worktree
npm run server     # the local API server (node http, default http://127.0.0.1:8787)
npm run dev        # the SPA in dev mode (proxies /api to the server)
```

The server shells out to the local `belay` CLI for verdicts: PATH first, with a
`BELAY_CONSOLE_ENGINE` override for the repo venv. Traces are read from
`BELAY_CONSOLE_TRACE_DIR` (default `~/.belay/traces`); click/expand events append
to `BELAY_CONSOLE_EVENTS` (default `~/.belay/console-events.jsonl`).

## Test and build

```bash
npm run test       # vitest, fully offline — synthetic fixtures, stub engine, injected clocks
npm run build      # vue-tsc + vite build (the server serves console/dist statically)
```

The C7 correctness tests are the component specs: UNVERIFIED renders distinctly
from PASS, every surface renders status + coverage line, NOT_COVERED renders as a
boundary never as PASS, a partial tail line is pending never a turn, and replay
without context renders a named-cause UNVERIFIED.

The engine wrapper is tested against `fixtures/stub-engine.mjs`, which emits the
pinned `verify --json` contract documents; the console never computes a verdict
of its own.