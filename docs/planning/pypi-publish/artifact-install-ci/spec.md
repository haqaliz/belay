# Aspect: artifact-install-ci

Part of `docs/planning/pypi-publish/prd.md` (launch checklist L4). The load-bearing
acceptance: prove the **built artifact** installs and runs on both platforms.

## Problem slice

Every CI job runs the source tree via `uv sync`; nothing installs the *built* wheel.
L4's DONE — "`uv tool install belay-harness` / `pipx install` / `pip install` all work on a
clean macOS and Linux box" — has no CI surface asserting the artifact path. A wheel that
is malformed, carries a stale version, or accidentally grows a third-party dependency
would pass every existing job and fail a stranger's install.

## User outcome

The maintainer tags a release knowing the artifact is installable and stamps the right
version; a stranger's `pip install belay-harness` is backed by a CI-proven path.

## In-scope requirements (from PRD M1, M2, S3)

- A pytest module `tests/test_artifact_install.py` that:
  - builds the wheel (and sdist) from the checkout via `uv build --out-dir <tmp>` (never
    into the repo `dist/`, which the docker tests assert must stay wheel-free —
    `tests/test_docker_image.py:76-85`),
  - installs the wheel with `pip --no-index --no-deps` into a fresh stdlib `venv`
    (deterministic: no network; the empty `dependencies = []` means no deps to resolve),
  - asserts, from the **installed** artifact: `belay --help` exits 0 and lists the CLI
    surface; `belay.__version__` equals the pyproject version (the stamp check lifted
    from `tests/test_docker_image.py:63-68,111-119`); importing `belay`/`belay.cli`/
    `belay.proxy` pulls no third-party import roots into `sys.modules` (the zero-dep
    contract, enforced from the artifact rather than the source tree); `belay sandbox
    check --scope <tmp>` succeeds (named-cause skip when the substrate lacks the
    mechanism, mirroring `tests/test_docker_inimage.py:183-208`);
  - runs a **capture → verify roundtrip** through the installed proxy and the installed
    verify CLI, reusing the docker roundtrip fixtures
    (`tests/fixtures/docker_roundtrip_{server,trace,client}.py`) — the client spawns
    `sys.executable -m belay.proxy`, so invoking it with the venv's python drives the
    installed proxy;
  - optionally installs the sdist in a second venv and asserts `belay --help` works
    (PRD S3, should-have).
- A new `install` pytest marker, excluded from the default run via `addopts`
  (precedent: the `manual` marker, `pyproject.toml:76-84`), so the packaging test does
  not slow the regular suites.
- A dedicated CI job `install` running the module on **macos-latest** and pinned
  **ubuntu-24.04** (matrix), following the existing `setup-uv` + `uv python install
  3.12` pattern (`ci.yml`).

## Out of scope

- Publishing anything (the channel is live; `release.yml` does it on tag push).
- `uv tool install` / `pipx` verification in CI (operator step, PRD's documented-live-check
  decision).
- GHCR, Docker quickstart, any engine/verdict change.

## Acceptance criteria (test-first — the failing tests written before the code)

1. `tests/test_artifact_install.py` exists with `@pytest.mark.install` and is
   **deselected** from `uv run pytest` (default) and **selected** by
   `uv run pytest tests/test_artifact_install.py -m install`.
2. The stamp test fails on a wheel built with a deliberately stale version
   (RED proof), then passes against the real build.
3. The roundtrip test produces a verdict from the installed CLI: `turn 0 ... PASS`
   with the coverage line printed (the same shape as
   `tests/test_docker_inimage.py:210-260`), never `INSTRUMENT SUSPECT`.
4. The `install` CI job is green on both platforms; existing jobs unchanged and green.
5. Deterministic: no network (wheel is local, `pip --no-index`); no clock/random.

## Dependencies & sequencing

- Depends on the L3 docker work for the reusable fixtures and the stamp-check pattern —
  both exist at master.
- First aspect in the build order: `quickstart-flip` claims what this aspect proves.

## Open questions / risks

- Whether `uv build` is available in the CI runner's PATH via `setup-uv` (it is —
  `uv build` is part of uv) and locally (developers have uv; the test can also fall back
  to `python -m build` only if needed — do NOT add `build` to dev deps without noting
  it, the import-guard philosophy prefers no new dev deps unless required).
- The roundtrip on macOS CI requires the Seatbelt backend to work on the runner (it
  does — the macOS `test` job runs the full sandbox suite today).
- `belay sandbox check` on ubuntu-24.04 requires kernel ≥ 5.13 (Landlock) — the pinned
  runner satisfies it; keep the named-cause skip for hosts that do not.