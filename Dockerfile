# Belay, self-hosted. Two stages so the ONLY build input is this checkout: a
# stranger with Docker and nothing else runs `docker build -t belay .` and gets a
# working image. A Dockerfile that COPYs a pre-built wheel works on the machine
# that just ran `uv build` and fails everywhere else, at `lstat /dist`, before any
# test could notice.
FROM python:3.12-slim AS build
WORKDIR /src
# Only what the wheel is built from. Everything else in the context is excluded by
# .dockerignore, and run data (traces/, runs/, corpus/) is excluded there too — a
# build context is not a place for the user's own data.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

FROM python:3.12-slim
# The wheel has zero runtime dependencies — stdlib only — so this installs exactly
# one thing and pulls nothing else in. That contract is load-bearing here: it is
# why the runtime stage carries no build toolchain and no package index access.
COPY --from=build /dist/belay_harness-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/belay_harness-*.whl \
    && rm /tmp/belay_harness-*.whl
RUN adduser --disabled-password --uid 1000 --gecos "" belay
# The documented state mount, owned by the user that will run in it. WORKDIR
# creates it as root, and without the chown `belay sandbox check --scope /workspace`
# — the first command README gives a reader — exits 1 with "the probe never ran":
# the containment probe must WRITE inside the scope to learn whether writes outside
# it are refused. A bind mount at this path carries the host's ownership instead,
# which is the contract the ownership test pins.
WORKDIR /workspace
RUN chown belay:belay /workspace
USER belay
ENTRYPOINT ["belay"]
