# PRD: Docker self-host (launch checklist L3)

Status: draft — Phase 3/4 of `belay-begin-fast` (branch `feat/docker-selfhost/aliz`). Sources: `docs/planning/_card/issue.md` (brief), `docs/planning/_card/understanding.md` (dig), three read-only agent maps, and user decisions on the open questions.

## Problem Statement

The Phase-1 launch gate (`docs/ROADMAP.md:283`) requires **≥3 external parties to self-host** Belay and catch a real failure on their own agent. Nobody can do that today: the launch checklist's installability block (Block B) is the first open dependency, and its first open item is L3 — a container channel. `README.md:64` still says "the **Docker image** itself (L3) is still unbuilt". The engine spine (C1–C6 + C9 first slice) and the Linux substrate (L2) are shipped; what remains is packaging and **re-measurement on a new substrate**: an image that runs the **real** Linux sandbox (Landlock + seccomp, copy-fidelity snapshot) — *"not a container that can't do the core"* (`CHECKLIST.md:121-126`).

Evidence it's real: every Phase-1 deliverable in `ROADMAP.md:261-272` (packaging row: "`docker run` self-host") and every external-self-hoster metric sits behind installability; `RELEASING.md:11-15` explicitly defers a container channel to this item.

## Goals & Success Metrics

- **Primary (the checklist's DONE):** `docker run belay <subcommand>` works on Linux **and macOS hosts** (macOS via Docker Desktop's Linux VM), and the image runs the real sandbox — `belay sandbox check` inside the container reports Landlock + seccomp present and an escape attempt is contained and recorded as a denial.
- **Claim split (honesty rule — what CI can and cannot verify):** CI validates the **Linux-host** path (docker on the pinned ubuntu-24.04 runner). The **macOS-host** path (Docker Desktop's Linux VM kernel) is **not CI-verifiable**; it ships as a manual operator re-probe step with the caveat stated ("re-probe in-image on the macOS host before relying on it") — never asserted by CI as verified.
- **Acceptance, test-first, in-image (CI):**
  1. The full suite runs green inside the built image (skips only with named causes — inherited from `tests/test_platform_gate_named_causes.py`).
  2. The escape matrix (write outside scope, disallowed network egress) **PASSES** inside the container — denial recorded in the trace. **Decision rule:** a base image whose shell/coreutils diverge from the measured substrate such that the matrix fails is a **blocker for that base** (switch base or fix), not a skip — "the image runs the real sandbox" is the L3 DONE meaning. Named skips are allowed only for host-kernel absence (`landlock-unavailable`) and overlayfs (`reflink-unavailable`).
  3. A snapshot restore round-trips byte-identically inside the container **or** degrades with a named cause (`UNRESTORABLE_CAPABILITY_MISMATCH` / `reflink-unavailable` on overlayfs) — never a silent fallback.
  4. `docker run belay` behaves identically to the installed CLI (help, `sandbox check`, a verify smoke whose trace is **generated deterministically in-image** via a fake MCP server round-trip — never mounted from committed run data, which is gitignored under the no-raw-data-egress guardrail).
- **Honesty metric (non-negotiable):** no new claim about the container boundary ships until `THREAT_MODEL.md` states exactly what the container boundary does and does not enforce (the R5/R8 guardrail surface).

## User Personas & Scenarios

- **The Docker self-hoster** (L3 consumer, named in `linux-sandbox/prd.md:48-49`): an engineer running an agent on a Linux box or macOS, who wants `docker run belay …` / `docker compose up` as their install path. They must get the real sandbox — the container is not a downgrade.
- **The launch reviewer**: a stranger following the quickstart must reach a first verdict in <15 min (`ROADMAP.md:277`); the image is the fastest path.
- **The threat-model reader**: an auditor who must be able to tell exactly which boundary claims were measured inside the container vs on the bare ubuntu-24.04 CI image (`THREAT_MODEL.md:315-321`).

## Requirements

### Must-have

1. **`Dockerfile`** — base: `python:3.12-slim` (matches `.python-version`; Debian-based, the closest maintained match to the measured ubuntu-24.04 substrate — glibc/coreutils versions verified in-image by the escape matrix, not assumed), with `/bin/sh` + coreutils available (the `sandbox check` probes shell out to `/bin/sh -c` and `sys.executable -c`, `cli.py:199-208,251-256`). Installs the `belay-harness` wheel (stdlib-only, `pyproject.toml:43-44`) so `__version__` stamps truthfully via `importlib.metadata` (`src/belay/__init__.py:18-21`). **Build-input pinning:** the wheel is built from the PR by CI and pinned between jobs — a rebuild must never silently pick a stale or absent wheel.
2. **Entrypoint parity:** `ENTRYPOINT ["belay"]` = `belay.cli:main` (`pyproject.toml:52-53`); the proxy stays reachable as `python -m belay.proxy <server-command>` (`proxy.py:530`). `python -m belay` does **not** exist — never document it.
3. **Non-root default user** (user decision): a `belay` user in the image; `docker run --user root` opt-in. No root-environment skip, narrower R8 surface.
4. **`.dockerignore`** — exclude `.git`, `.venv`, `traces/`, `runs/`, `_sandbox/`, `corpus/`, `eval/`, `.claude/`, `node_modules/`, cache dirs (nothing keeps raw run data out of a build context today).
5. **`docker-compose.yml` (minimal, user decision)** — engine service only, working `docker run`-equivalent invocation; a comment names the C7 console service as the future addition. No broken console service ships.
6. **CI job — build + validate the image** — a new job (or workflow) that builds the image from the PR and runs the four acceptance items **inside it** (suite, escape matrix, snapshot round-trip/named-cause, `docker run belay` parity).
7. **`THREAT_MODEL.md` container section** — restate, measured not assumed: Landlock is the **host kernel's** (unprivileged, ≥5.13, not namespaced — an unprivileged container on a pre-5.13 host skips with `landlock-unavailable` and the launcher refuses at runtime); Docker's default seccomp profile interplay with Belay's BPF filter (verified in-image); overlayfs ⇒ `reflink-unavailable` ⇒ copy path with named-cause cross-capability restore; world-writable `/tmp` TMPDIR neighborhood unbound (`THREAT_MODEL.md:398-407,495`); the docker.sock line stays closed (`network-bind` measured narrow, `THREAT_MODEL.md:133-136`); the cross-substrate corpus consequence (SKIP with `UNRESTORABLE_CAPABILITY_MISMATCH`, never a guessed restore).
8. **README update** — replace the "no container yet" callout (`README.md:64`) with the `docker run` quickstart and an honest coverage line for the image; mark L3 ✅ in `docs/planning/launch-readiness/CHECKLIST.md`.

### Should-have

9. ~~`belay sandbox check` run as the image healthcheck / entrypoint preflight~~ — **NOT SHIPPED, deliberately (decided 2026-08-20).** The *capability* it wanted is shipped and is the load-bearing part: the probe is the re-measurement instrument, it runs in-container on every PR (`tests/test_docker_inimage.py`), and README gives a reader the exact command to re-probe a macOS host. What is not shipped is the Docker *directive*, because neither form fits this image. A `HEALTHCHECK` is periodic liveness for a **long-running** container; `ENTRYPOINT ["belay"]` is a one-shot CLI that exits, so the check would never meaningfully run. An **entrypoint preflight** would probe the sandbox before every invocation — including `belay --help`, which needs no sandbox — paying setup cost on each run and turning a substrate absence into a failure of commands that do not touch the substrate. It becomes right when a long-running service exists: **C7's console** (named, not built, in `docker-compose.yml`) is the service that should declare a healthcheck, and this is the note for whoever builds it.
10. A `docker run` smoke against a fixture trace exercising `verify` end-to-end (first real test of the installed console-script surface — the repo has none today; `python -m belay.cli` subprocess tests are the standing proxy).

### Nice-to-have

11. `.dockerignore`-level size trimming and multi-stage build (wheel build stage vs runtime stage).
12. macOS-host verification note in CI docs (image runs via Docker Desktop VM kernel — re-probe; cannot run in the macOS CI job).

## Technical Considerations

- **Capability:** this is L3 of the launch checklist (installability block), not a C-capability; it sits *on* C2 (the shipped Linux sandbox) and C6 (corpus). Dependencies: L1 ✅, L2 ✅ — nothing unshipped blocks it (`CHECKLIST.md:119`).
- **Zero-dependency contract is load-bearing for the image:** the wheel carries everything; the base image needs only CPython ≥3.10 + `/bin/sh` + coreutils. The dev-dependency guard (`tests/test_import_guard.py`) protects it in the build.
- **Determinism:** the in-image suite runs against fixtures and fake servers — no network in tests. The CI validation must not require network beyond the image pull.
- **Verdict impact: none.** No verdict axis changes. A1/A2 machinery is *re-measured on a new substrate* (escape matrix, fidelity round-trips, probes) and the honesty boundary statement is extended — R5 ("replay verifies fidelity, not correctness" — over-claiming) and R8 (sandbox escape / Belay itself is the attack surface) are the register entries in scope. UNVERIFIED-with-named-cause semantics are inherited unchanged: a snapshot that cannot restore is a named-cause SKIP/UNVERIFIED, never a guessed PASS.
- **Release channel:** per `RELEASING.md:11-15`, the ghcr push job lands with the image — user decision: **deferred to a follow-on slice** (this unit ships image build + CI validation only; `RELEASING.md` gets a note updating the deferral). Fits L5's sequence (PyPI → Docker image).
- **The suite in-image:** expected named-cause skips — macOS-only causes (`seatbelt-only`, `darwin-acl`, `macos-python3-shim`, `bsd-file-flags`, `replay-reinvokes-seatbelt`) plus runtime `landlock-unavailable` (host <5.13) and `reflink-unavailable` (overlayfs, expected). The named-cause gate test is substrate-neutral (AST scan) and inherits automatically.

## Risks & Open Questions

- **R8-adjacent — the container boundary is unmeasured today** (`THREAT_MODEL.md:319-321`): Landlock-in-Docker and seccomp-profile interplay were explicitly "must re-measure". Mitigation: the acceptance runs the real probes in-image; nothing ships as a claim before the measurement.
- **Host-kernel dependence:** an unprivileged container inherits the *host* kernel — on a pre-5.13 host the sandbox refuses at runtime (exit 2, named cause). This is correct behavior, but a user's first `docker run` on an old host will fail loudly; the README must say so (kernel ≥5.13 requirement carried over from `README.md:54`).
- **`dash` vs `bash` (L2 finding, `plan_20260815.md`):** coreutils/dash exit-code differences bit the escape matrix on real Linux. The slim image's shell must behave like the measured ubuntu-24.04 substrate or the matrix tests will skip/fail — verify in-image.
- **macOS host:** the image runs in Docker Desktop's Linux VM; the host's Seatbelt is irrelevant. The `docker run` claim is about the *container's* sandbox; the docs must not imply the image sandboxes the macOS host.
- **Open (resolved by user decisions):** compose scope (minimal engine-only, console hook named); release channel (build + validation only, ghcr deferred); container user (non-root default).
- **Open (carried):** ghcr push slice (follow-on); L4 PyPI publication remains separate.

## Out of Scope

- GHCR publish job / release-channel wiring (deferred follow-on slice; `RELEASING.md` note only).
- The console (C7/L6) and its compose service (named as the future hook).
- gVisor / firejail / container-runtime-based sandboxing (L2 decision: Landlock + seccomp is the boundary; other runtimes violate zero-dep, `linux-sandbox/prd.md:196-200`).
- Any new verdict axis, invariant, or verdict-surface change.
- Cross-substrate replay *support* (cases remain SKIP-with-cause across substrates — capability, not this unit's scope).
