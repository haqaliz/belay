# Spec: Aspect A1 — the image (`image/`)

Part of `docs/planning/docker-selfhost/prd.md` (L3, Docker self-host).

## Problem slice

The container artifact itself: a `Dockerfile` that produces an image whose entrypoint is the real `belay` CLI (and proxy reachable as `python -m belay.proxy`), running the **real** Linux sandbox — Landlock + seccomp, copy-fidelity snapshot. "The image runs the real sandbox — not a container that can't do the core" (`CHECKLIST.md:121-126`).

## In-scope requirements

1. Base `python:3.12-slim` (Debian-based, closest maintained match to the measured ubuntu-24.04 substrate); `/bin/sh` + coreutils present (probes at `cli.py:199-208,251-256`).
2. Install the `belay-harness` wheel built from the PR — pinned between CI jobs, never stale; version stamps truthfully via `importlib.metadata` (`src/belay/__init__.py:18-21`).
3. `ENTRYPOINT ["belay"]` → `belay.cli:main` (`pyproject.toml:52-53`); `python -m belay.proxy <server-command>` reachable; `python -m belay` must NOT be documented (no `__main__.py`).
4. Non-root default user (belay); root opt-in via `--user root`.
5. `.dockerignore` excluding `.git`, `.venv`, `traces/`, `runs/`, `_sandbox/`, `corpus/`, `eval/`, `.claude/`, `node_modules/`, caches, `probe_result.json`.
6. Multi-stage build: build stage (`uv build`) → runtime stage (wheel copy, no build tooling).
7. Volume/state contract: document the recommended mounts (`-v` workspace, `BELAY_TRACE_DIR`, `BELAY_SNAPSHOT_DIR`) and the non-root-uid vs host-dir-ownership contract — the PRD's open question, resolved here.

## Out-of-scope

- GHCR publish job (deferred follow-on slice).
- The console (C7/L6) and its compose service.
- Any new sandbox mechanism or verdict surface.
- Cross-substrate replay support.

## Acceptance criteria (test-first)

- `docker build` succeeds from a clean checkout (CI verifies).
- `docker run belay --help` exits 0 and prints the full CLI surface; `docker run belay sandbox check --help` works.
- The image reports its version matching the built wheel (`docker run belay --version` or equivalent — verify `belay.__version__` path).
- The non-root user is the default: `docker run belay` processes run as the belay uid (CI asserts); root requires `--user root`.
- A mounted host dir with the documented ownership (uid 1000 belay) is readable/writable by the container without errors; the ownership contract is asserted in CI with a bind mount fixture.
- `.dockerignore` is asserted: `docker build` context excludes the named dirs (build-context check, e.g. via `COPY . /context` size/content probe or a static test of the file).
- No undocumented `python -m belay` anywhere in the image docs/help output.

## Dependencies / sequencing

First aspect — everything else (container-ci, compose-docs) consumes this image. Needs the wheel build step working in CI (`uv build`).

## Open questions / risks

- Exact uid/gid choice for the belay user (1000 is the common host default; document the mismatch path: host dir owned by another uid → user must chown or use `--user`).
- Debian slim vs ubuntu-24.04 divergence is verified by the container-ci escape matrix, not assumed here.
