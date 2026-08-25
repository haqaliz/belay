# Aspect: compose-healthcheck (A3)

Part of `docs/planning/live-console/prd.md` (launch checklist L6 / C7). The console as a
compose service, plus the docs that make the console a named surface.

## Problem slice

`docker-compose.yml:11-15` names the console as a comment only, and
`tests/test_docker_compose.py:91-102` regression-guards that state. The L3 deferral
(`CHECKLIST.md:189-190`) ties two things to C7's existence: the `console:` service in
compose, and the Docker `HEALTHCHECK` (a long-running service is when a healthcheck
becomes meaningful — a one-shot CLI image never needed one).

## In-scope requirements (PRD S1, S2)

- `console/Dockerfile`: build the SPA, run it with a static server, and bundle the
  `belay-harness` engine (pip install the wheel built in-image, mirroring the engine
  Dockerfile's pattern) so verify/replay work inside the container; non-root user;
  health endpoint.
- `docker-compose.yml`: the `console:` service (build from `./console`), a port
  mapping, the traces/snapshots volume mounts consistent with the engine service's
  `BELAY_*` defaults (`docker-compose.yml:37-44`), and a `healthcheck` hitting the
  console's health endpoint.
- The compose regression test flips: `test_the_console_is_named_but_not_shipped`
  becomes `test_the_console_service_ships_with_a_healthcheck` — asserting the service
  exists, builds, and declares a healthcheck; the engine-only assertions stay.
- Docs: `README.md` surface list (`README.md:189`) gains the console; the "named and
  not yet built" callouts (`README.md:80`) updated; `CAPABILITY_ROADMAP.md` §C7 status
  block; `CLAUDE.md` status line; `docker-selfhost` deferral notes marked resolved by
  C7.

## Out of scope

- The GHCR publish job (still deferred — the image is built and validated, not pushed).
- Any engine change; any change to the `belay` service in compose beyond what the
  console needs to share volumes.

## Acceptance criteria (test-first)

1. The flipped compose test passes: `console:` is a service with a build context, a
   healthcheck, and a non-root user; `docker compose config` validates.
2. `docker compose build console` succeeds (or the docker CI job's in-image run covers
   it — decide in the plan); `docker compose run --rm console` serves the health
   endpoint.
3. The console image bundles `belay` (in-image `belay --help` works) — mirror the
   engine image's wheel-install pattern.
4. Docs: the surface list and the "not yet built" callouts no longer claim the console
   doesn't exist; the L3 deferral notes cite C7 as the resolution.

## Dependencies & sequencing

- After A2 (the console app must exist to build); the docker job's pinned ubuntu-24.04
  is the validation substrate. The engine image's `tests/test_docker_image.py` patterns
  (version stamp, entrypoint) are the template.

## Open questions / risks

- Whether the console container needs the engine at all in this slice (it does —
  replay-from-here must work in-container for the demo; the wheel is tiny and the
  engine Dockerfile pattern is proven).
- R8 territory (the container is an attack surface) — the console container serves the
  local network only; state it in `THREAT_MODEL.md`-style docs within the aspect's
  scope (one honest paragraph, not a full section).