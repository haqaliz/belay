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