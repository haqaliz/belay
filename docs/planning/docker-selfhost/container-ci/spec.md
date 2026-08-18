# Spec: Aspect A2 — container CI + in-image acceptance (`container-ci/`)

Part of `docs/planning/docker-selfhost/prd.md` (L3, Docker self-host).

## Problem slice

Proof that the image is what L3 promises: a CI job that builds the image and runs the four acceptance criteria **inside it**. The substrate claims in `THREAT_MODEL.md:315-321` ("nothing here is claimed about any other Linux image: a Docker image (L3) … must re-measure") become measured for the image.

## In-scope requirements

1. A CI job (in `ci.yml` or a new workflow) that: builds the wheel from the PR → builds the image → runs the acceptance inside the container.
2. In-image suite: full pytest run green, skips only with named causes (inherited gate test `tests/test_platform_gate_named_causes.py` is substrate-neutral — runs as-is in the container).
3. In-image escape matrix: the five vectors (direct write, `../`, symlink-out, `mv`-out, grandchild) + network deny-all — PASS with denial records; the PRD decision rule holds (failure on the chosen base = blocker, not skip).
4. In-image snapshot round-trip: byte-identical restore or named-cause degradation (`reflink-unavailable` on overlayfs / `landlock-unavailable` on old kernels) — never silent.
5. `docker run belay` parity: help, `sandbox check` (reports Landlock ABI), and a verify smoke whose trace is **generated deterministically in-image** (fake MCP server round-trip — never mounted run data).
6. Claim split enforced: Linux-host path is what CI asserts; macOS-host path stays a documented manual re-probe.

## Out-of-scope

- GHCR push / release wiring.
- macOS-host automated verification (impossible from Linux CI; Docker Desktop licensing/VM).
- Any change to the engine or the suite itself.

## Acceptance criteria (test-first)

- The CI job runs on every PR (or is a required check) and is green on the pinned `ubuntu-24.04` runner.
- The in-image pytest run's skip report is inspected: every skip has a named cause; the count matches the expected set (macOS-only causes + `landlock-unavailable`/`reflink-unavailable` as runtime allows).
- The in-image escape matrix passes with exact rc/stderr/denial-record assertions (reuse `tests/test_linux_containment.py` shapes).
- The in-image snapshot test reports copy-fidelity round-trip or the named `UNRESTORABLE_CAPABILITY_MISMATCH`/`reflink-unavailable` cause — never a bare failure.
- The parity smoke: `docker run belay verify` (or replay) on a generated fixture trace exits with the expected verdicts and prints the coverage line (`_VERIFY_COVERAGE` words, `cli.py:525-555`).
- CI artifacts record the image build (tag = commit sha) and the in-image results.

## Dependencies / sequencing

Second aspect — consumes `image/` (the Dockerfile). Depends on A1 being merged. The suite-in-image step reuses the existing test suite unchanged; no engine edits allowed here.

## Open questions / risks

- Docker-in-CI on GitHub runners: `docker build` + `docker run` are supported on ubuntu-24.04 runners out of the box; the runner's docker daemon seccomp/Landlock behavior is the same host-kernel story — if the runner kernel lacks Landlock (it doesn't, kernel 6.x), the matrix would skip with the named cause; that is a signal, not a pass.
- CI wall-clock budget: full suite in-image roughly doubles test time; consider a single job rather than a matrix.
