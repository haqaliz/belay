# Issue #51 — feat: GitHub Action wrapper and --strict-shape for belay gate

## Why
`belay gate baseline` / `belay gate check` shipped, but CI adoption still requires hand-writing YAML. The wrapper and `--strict-shape` were deferred by name at `ci-regression-gate` (2026-09-13).

## Scope
- A reusable GitHub Action wrapping baseline/check with the documented exit codes.
- `--strict-shape` for teams that want turn-count/tool-rename drift to fail.
- Docs + machine-checked quickstart.

## Exit criteria
- A sample workflow in `docs/` is machine-checked by a test.
- No verdict, axis or published number moves.

## Status
Deferred by name; not launch-blocking.
