# Aspect: console-container-api (A2)

Part of `docs/planning/launch-demo/prd.md` (launch checklist L7). Close the L6 gap: the
compose console must render traces and verdicts, not just serve a dead SPA.

## Problem slice

`console/server-static.mjs` (the container's server) implements only static serving +
`/health` — every `/api/*` call 404s in the container, so `docker compose up console`
cannot render a trace or a verdict. The demo (L7) is only a demo if the console can
show it.

## In-scope requirements (PRD M4)

- The console image runs the REAL server (`console/src/server/index.ts` — tail, trace
  derivation, engine subprocess, /api/traces, /api/trace, /api/feed, /api/verify,
  /api/replay, /api/events, static SPA serving) instead of the static-only server, OR
  `server-static.mjs` gains the API — decided: build the real server to plain JS
  (`tsc`/esbuild → `dist-server/`) and run it with node in the image (one server, one
  behavior — never two implementations of the API).
- The real server gains `/health` (the image's healthcheck target stays; the engine
  version field preserved).
- The docker-gated render check: `docker run` the console image with a fixture trace
  mounted, `GET /api/traces` lists it, `GET /api/trace` derives its turns, `/health`
  reports the engine version — the demo capture (once A1 lands) renders.
- `docker-compose.yml` wiring unchanged except what the server needs
  (`BELAY_CONSOLE_TRACE_DIR` already points at `/workspace/traces`).

## Out of scope

- The gif (A3), the capture (A1), any engine change, the GHCR publish.

## Acceptance criteria (test-first)

1. `console/package.json` gains a `build:server` step producing plain JS from
   `src/server/`; `npm run build:server` succeeds.
2. The Dockerfile's runtime CMD runs the built server (not `server-static.mjs`); the
   image build still works (docker CI job).
3. The docker-gated test (extending `test_the_console_image_builds_and_reports_health_with_the_engine`
   in `tests/test_docker_compose.py`): build the image, `docker run` with a fixture
   trace mounted at the trace dir, `curl /health` (engine version) + `curl
   /api/traces` (lists the trace) + `curl /api/trace?path=` (derives turns) — all 200
   with the expected shapes.
4. `server-static.mjs` is deleted or reduced to a dev-only fallback; no two API
   implementations coexist.
5. The console's offline test suite stays green; the SPA tests unchanged.

## Dependencies & sequencing

- Second aspect: A3's gif drives the console through this server. The render check can
  use a fixture trace; the demo capture (A1) is the natural fixture once it exists.
- Parallel-safe with A1 (no shared files except the eventual render-check fixture).

## Open questions / risks

- Whether `tsc` (typescript) is already a console dev-dep (it is — `vue-tsc` is) or
  needs `esbuild` — decide in the plan (prefer tsc's existing presence; `tsx` is
  already used for `npm run server`, so its output shape is known).
- The render check needs docker — it runs in the docker CI job's module (the existing
  `test_docker_compose.py` gate), not the default suite.
## Amendment — 2026-08-27: the console's verdicts needed one engine flag

**Out of scope said "any engine change". This aspect made one, deliberately, and it is
recorded here rather than absorbed silently.**

The console shells out to `belay verify --json`. The demo capture's `run_process` turns
re-run a real suite in ~44s, and `verify`'s per-replay timeout was the fixed 10s default
— so the console's headline turns rendered UNVERIFIED. A prior commit on this branch
answered that by passing `--timeout` from `BELAY_CONSOLE_VERIFY_TIMEOUT`. **The flag did
not exist on `verify`.** `corpus add`, `phase0 run` and `interop correlate` each had one;
`verify` did not. argparse answered `unrecognized arguments: --timeout <trace>` with an
EMPTY stdout and exit 2, so with the compose service's pinned `300` **every** console
verify degraded to the `empty-output` error path — strictly worse than the abstention it
was meant to fix, and invisible to the console's own suite, whose stub engine echoes argv
and cannot object.

Three changes, each pinned by a test:

1. **`belay verify --timeout <seconds>`** (`tests/test_verify_cli_timeout.py`) — the same
   flag the three sibling surfaces already carry, defaulting to the same
   `cli.DEFAULT_TIMEOUT`, passed through to `verify_turn`. No verdict axis, invariant or
   status changed; a raised timeout can only turn an UNVERIFIED-by-clock into whatever
   the replay actually finds.
2. **The console's replay context by default** — `BELAY_CONSOLE_VERIFY_SERVER`
   (whitespace-split into `--server` argv tokens; `verify --server` is a REMAINDER and
   takes separate tokens, so the previous single-string push would have exec'd the whole
   command as one filename) and `--manifest-dir` defaulting to the trace's
   `<trace-stem>.manifests` sibling **only when it exists**. Absent either, nothing is
   passed and the engine's own fail-closed error stands. A request-carried
   `server`/`manifest` always wins.
3. **The console's own subprocess wall, derived rather than fixed** — the wall was 60s
   while the authorised per-replay budget was 300s, so the console SIGTERMed a legitimate
   replay at exactly 60.0s and reported `empty-output`, blaming the engine for its own
   kill. The wall is now `timeout x turns-in-scope` (floored at the old 60s default) and
   a wall that does fire reports `console-wall-timeout`, a distinct named cause.

**Measured end-to-end on the committed capture**, not inferred from stubs:
`belay verify --json --timeout 300 ... --server python3 demo/server.py '{workspace}'`
→ **7/7 PASS, 0 UNVERIFIED, trajectory PASS — supported by 2 replayed command turn(s)**,
exit 0, ~2m12s; the same verdict through the console's `POST /api/verify` with only the
env defaults set; and the slow `run_process` turn 6 through `POST /api/replay` → **PASS**
in 66s (the run that was being killed at 60s).

**Still out of scope and untouched:** the gif (A3), the capture itself (A1), the GHCR
publish, and every verdict axis, invariant and status.
