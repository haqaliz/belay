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

**Verify timeout knob.** `BELAY_CONSOLE_VERIFY_TIMEOUT` (seconds) is passed to
`belay verify --timeout` on every verify/replay the server runs. The engine's
default per-replay timeout is 10s, which cannot replay the launch demo capture's
~44s `run_process` turns — without the knob they render `UNVERIFIED` (a false
abstention, never a false PASS). Set it for the demo (the compose console
service pins `300`):

```bash
BELAY_CONSOLE_TRACE_DIR=demo/capture BELAY_CONSOLE_VERIFY_TIMEOUT=300 npm run server
```

Absent (or not a positive integer) means nothing is passed and the engine
default applies.

**Replay context.** `belay verify` needs two more things to re-execute a turn:
the MCP server to replay against and the snapshot manifests of the recorded
pre-state. The server supplies both by default so a packaged capture verifies
without an operator typing them in:

- `BELAY_CONSOLE_VERIFY_SERVER` — the `--server` command, **split on whitespace**
  into argv tokens (`verify --server` is a remainder and takes the command as
  separate tokens). Unset means no `--server` is passed and the engine's own
  fail-closed error — *"a server command is required. Nothing to replay
  against."* — is the answer, never a guessed command replayed against the wrong
  binary.
- `--manifest-dir` defaults to the trace's `<trace-stem>.manifests` **sibling**,
  the convention the gate writes and `belay phase0 run` resolves, and only when
  that directory actually exists. Otherwise nothing is passed and `verify`'s
  required-argument error stands.

Both are defaults: a `server`/`manifest` carried on the request (the replay
dialog's inputs) always wins.

The server's own wall around the `belay` subprocess is **derived from the same
per-replay budget** (`timeout x turns in scope`, floored at 60s), not fixed: a
wall smaller than the budget the operator authorised would SIGTERM a legitimate
replay, and a killed engine leaves empty stdout. When the wall does fire the
cause is `console-wall-timeout`, deliberately distinct from `empty-output` —
the console never blames the engine for its own kill.

```bash
BELAY_CONSOLE_TRACE_DIR=demo/capture \
BELAY_CONSOLE_VERIFY_TIMEOUT=300 \
BELAY_CONSOLE_VERIFY_SERVER="python3 $(pwd)/demo/server.py {workspace}" \
  npm run server
```

## Record the demo gif

```bash
npm run record:demo      # -> assets/belay-demo.gif
```

**Manual by design, never CI.** It drives a real browser (Playwright's chromium — a
separate per-machine download: `npx playwright install chromium`) and it re-executes the
committed capture through the engine, which takes minutes. The gif is committed; nothing
regenerates it on a push.

What makes the output deterministic is not the clock: the subject is a frozen artifact
and each beat waits on the STATE it is about (the verdict landing, not a sleep), while
the frame sequence and per-frame delays are fixed constants in the script. The PNG decode
and the GIF encode both happen inside the browser page — it already has a PNG decoder and
gifenc is pure JS — so there is no ffmpeg and no image dependency in node.

| Variable | Effect |
|---|---|
| `BELAY_DEMO_TRACE_DIR` | what to record (default `demo/capture`) |
| `BELAY_DEMO_FRAME_DIR` | also write each beat as a PNG, for inspecting the composition |
| `BELAY_DEMO_FROM_FRAMES` | re-encode an existing frame dir instead of re-driving the console — tuning the palette or the delays should not cost another few minutes of real re-execution |
| `BELAY_DEMO_PALETTE` | GIF palette size (default 64; the console is flat UI) |
| `BELAY_DEMO_VERDICT_TIMEOUT_MS` | how long to wait for the verdict before giving up (default 15 min) |

## Test and build

```bash
npm run test        # vitest, fully offline — synthetic fixtures, stub engine, injected clocks
npm run build       # vue-tsc + vite build (the server serves console/dist statically)
npm run build:server # tsc — the API server as plain JS (dist-server/), what the container runs
```

The C7 correctness tests are the component specs: UNVERIFIED renders distinctly
from PASS, every surface renders status + coverage line, NOT_COVERED renders as a
boundary never as PASS, a partial tail line is pending never a turn, and replay
without context renders a named-cause UNVERIFIED.

The engine wrapper is tested against `fixtures/stub-engine.mjs`, which emits the
pinned `verify --json` contract documents; the console never computes a verdict
of its own.

## In the container

The compose console (`docker compose up console`) runs THIS server, not a static
fallback: the image builds the SPA and `dist-server/` in-image and serves the
full API — traces list, per-trace derivation, live feed, verify/replay, events,
and `/health` (the healthcheck contract: 200 `{"ok": true, "engine": "<version>"}`
via the bundled engine, honest 503 with `null` when the probe fails). A trace in
the shared `/workspace/traces` mount renders in the container exactly as it does
locally — one server, one behavior.