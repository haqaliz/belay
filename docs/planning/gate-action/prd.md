# PRD — GitHub Action wrapper + `--strict-shape` for the CI regression gate

**Issue:** #51 · **Slug:** `gate-action` · **Branch:** `feat/51/aliz`

## Problem

`belay gate baseline` / `belay gate check` shipped (v0.26-era), but a team still hand-writes
the CI YAML, and shape drift (turn-count shrink, tool renames, new non-failing turns) never
fails a build. Both were deferred by name in `ci-regression-gate` (N1, N2).

## What ships

**1. `belay gate check --strict-shape`** (check-only flag; no `gate baseline` counterpart).

When set, the presence of **any** shape row makes the gate fail: `exit_reason` becomes the
existing `REGRESSION` (exit 1), reusing the current contract — no new exit code, no change to
the README exit table or `tests/test_gate_docs.py`. Drift rows stay report-only: they are
engine-change evidence, not agent behaviour.

**2. A composite GitHub Action** at the repo root (`action.yml`) that installs Belay when
asked and runs `belay gate check` with the same flags, argv built as a bash array so every
flag lands **before** `--server` (the REMAINDER defect class that already bit twice).

Inputs: `trace` (required), `run-id`, `server`, `strict-shape` (default false), `baselines`
(default `baselines/local`), `version` (pip spec; empty = use an already-installed `belay`).
No outputs: the exit code is the contract.

## Non-goals

- No new exit code, outcome value, JSON key/schema bump, or decision-table row.
- No change to what `gate baseline` banks or how policy is resolved.
- No Action outputs, no marketplace metadata, no per-turn overrides on `check`.
- No baseline storage: `/baselines/` stays gitignored; the workflow restores it (cache or
  artifact). The Action documents this, it does not solve it.
- No raw trace/snapshot upload.

## Acceptance criteria

1. `--strict-shape` with any of the three shape kinds → exit 1; without the flag → exit 0.
2. Drift rows alone → exit 0 even with `--strict-shape`.
3. A genuine regression → exit 1 with or without the flag (unchanged).
4. SKIP/preflight → exit 2 (unchanged).
5. JSON document key set unchanged (`GATE_SCHEMA` stays 1).
6. `action.yml` is a composite action; a YAML-parsing test asserts: every input is declared
   and referenced, `--strict-shape` is only passed when true, and every flag precedes
   `--server` in the script.
7. README documents both: the flag and `uses: haqaliz/belay@<tag>` with the baseline-restore
   note.
8. `STATUS.md` / `CHANGELOG.md` record the unit; no published number moves.

## Risks

- **R-a:** passing `--strict-shape` after `--server` silently becomes server argv. Mitigated
  by AC-6's ordering assertion in the Action test.
- **R-b:** teams with legitimate turn-count changes get a red build. Mitigated by the flag
  being opt-in; default behaviour is byte-unchanged.
- **R-c:** an unpinned `version` makes CI non-reproducible. Mitigated by defaulting to "use
  whatever is installed" and documenting a pinned tag.

## Open questions

- 🟡 **Q1:** report a shape-triggered failure as `REGRESSION` or add a distinct reason?
  Proposed: reuse `REGRESSION` (smallest contract change); the `shape` section already names
  the rows.
