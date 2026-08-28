# The console, self-hosted — built from NOTHING but this checkout, mirroring the
# engine image's rule (see the engine Dockerfile's README note). A Dockerfile
# that COPYs a prebuilt SPA or a prebuilt wheel works on the machine that just
# built them and fails everywhere else: here `npm ci` + `npm run build` make the
# SPA and `python -m build` makes the engine wheel, both in-image. The engine is
# BUNDLED — not fetched — so verify/replay inside this container run the engine
# this checkout ships, never a stale published wheel.
#
# Build with the repo root as context (the engine sources must be in it):
#   docker build -f console/Dockerfile -t belay-console:test .
#   docker compose build console        # the compose file sets the same context

FROM node:22-slim AS spa-build
WORKDIR /console
# The lockfile lands first, so `npm ci` is deterministic and layer-cached.
COPY console/package.json console/package-lock.json ./
RUN npm ci
# The sources. node_modules/ and dist/ are excluded from the context by the
# root .dockerignore — a stale local build never reaches this stage.
COPY console/ ./
# The SPA and the API server both build in-image: `build:server` compiles
# src/server/ to plain JS (dist-server/), which is what the runtime stage runs.
RUN npm run build
RUN npm run build:server

FROM python:3.12-slim AS engine-build
WORKDIR /src
# Only what the wheel is built from — the engine Dockerfile's exact stage.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

FROM python:3.12-slim
# The bundled engine: the wheel built above, installed with nothing else (the
# wheel is zero-dependency, stdlib only).
COPY --from=engine-build /dist/belay_harness-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/belay_harness-*.whl \
    && rm /tmp/belay_harness-*.whl
# Node is the server's runtime, copied from the node build stage — the
# same glibc base (bookworm) as this image, so the binary runs. libstdc++6 is
# node's one runtime library outside glibc; apt installs it if the base lacks
# it (idempotent either way — this image is a web server, not the engine
# image's minimal runtime, and it says so here rather than pretending).
COPY --from=spa-build /usr/local/bin/node /usr/local/bin/node
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
# The built SPA and the built API server (plain JS from src/server, /health
# included): the runtime runs ONE server — the same one `npm run server` runs
# locally — never a second implementation.
COPY --from=spa-build /console/dist /console/dist
COPY --from=spa-build /console/dist-server /console/dist-server
RUN adduser --disabled-password --uid 1000 --gecos "" belay
WORKDIR /console
USER belay
# The IMAGE's own defaults, not the dev server's. `run.ts` defaults to 8787 on
# 127.0.0.1 and reads traces from ~/.belay/traces — right for `npm run server` on
# a laptop, wrong in a container: the loopback bind is the container's own, the
# port disagrees with EXPOSE below, and the trace dir is not the `/workspace`
# state mount this image is deployed with. So `docker run -p 127.0.0.1:8080:8080`
# published a port nothing listened on, and a trace mounted at /workspace/traces
# was invisible. Compose set all of these by hand and was therefore the only path
# that ever worked. An image must be correct when run plainly; compose may still
# override, and does.
#
# NOT set here, deliberately: BELAY_CONSOLE_VERIFY_SERVER (no server command can
# be guessed — the engine's fail-closed error is the honest answer) and
# BELAY_CONSOLE_VERIFY_TIMEOUT (deployment-specific; compose pins the demo's 300).
ENV BELAY_CONSOLE_PORT=8080 \
    BELAY_CONSOLE_HOST=0.0.0.0 \
    BELAY_CONSOLE_TRACE_DIR=/workspace/traces \
    BELAY_SNAPSHOT_DIR=/workspace/snapshots
EXPOSE 8080
CMD ["node", "dist-server/run.js"]