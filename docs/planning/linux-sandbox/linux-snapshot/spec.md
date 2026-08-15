# Aspect A3 — Linux snapshot/restore backend

## Problem slice

Byte-identical per-turn pre-state snapshot/restore on Linux: the second
`SnapshotBackend` implementation behind the existing pattern, honest about the
fidelity it can provide on each substrate (ext4 has no reflink; GitHub runners are
ext4 — `docs/planning/sandbox-snapshot-restore/prd.md:244`).

## In-scope

- **Backend (M4):** a Linux backend on the `ClonefileBackend` pattern
  (`substrate.py:317-343`): probed `capabilities()`, new `name`, sidecar-manifest
  round-trip unchanged. Reflink (`FICLONE`) where available; the honest fallback
  (copy with sidecar fidelity — hardlinks, setuid/setgid/sticky, mtimes, xattrs
  via `os.listxattr` which already exists on Linux, symlink targets, `st_rdev`) is
  the CI-substrate path.
- **Byte-identical restore:** hash-of-tree equality for a restored tree, including
  the fidelity dimensions the sidecar tracks (same contract as the macOS
  acceptance).
- **Capability-mismatch refusal preserved:** `guarded_restore` refuses across
  differing capability sets (`UNRESTORABLE_CAPABILITY_MISMATCH`,
  `substrate.py:393-410`) — a case captured on clonefile/APFS stays
  UNVERIFIED/skip on Linux and vice versa, never a guessed restore.
- **`gc()` Linux path:** no `os.chflags` / `/bin/chmod -R -N`
  (`substrate.py:446-481`) — plain removal, with the Linux immutable-bit
  difference documented, not silently ignored.
- **Taxonomy reachability:** the causes the taxonomy already reserves for this
  slice (`UNRESTORABLE_CASE_COLLISION`, `UNRESTORABLE_INVALID_UTF8_NAME`,
  `UNRESTORABLE_NORMALIZATION_COLLISION` — `substrate.py:171-186`) become
  reachable on Linux and classified (the exhaustive-classification tests at
  `substrate.py:59-61` and `test_each_locally_raised_cause_is_actually_produced`
  enforce this).
- Ungated darwin-dependent snapshot tests (`test_snapshot.py`,
  `test_turn_gate.py`, `test_snapshot_persist.py`, `test_persist_relative_tree.py`,
  `test_substrate.py`) gain Linux coverage via the new backend.

## Out-of-scope

- Containment (A2).
- Docker/PyPI packaging (L3/L4).
- Cross-filesystem restore **attempts** — they stay refused, by the preserved
  capability-mismatch rule.

## Acceptance criteria (test-first)

1. Snapshot → restore on the Linux substrate yields hash-of-tree equality for a
   fixture tree containing: nested dirs, symlinks, hardlinks, setuid/setgid/sticky
   modes, non-ASCII and normalization-edge names, xattrs — the BTH-1 field set
   (`bth1.py:30-33`).
2. The reflink path and the fallback path both round-trip (on a machine with
   FICLONE support; the fallback runs in CI).
3. A restore across differing capability sets yields
   `UNRESTORABLE_CAPABILITY_MISMATCH` (never a silent restore) — pinned by test.
4. `gc()` removes a Linux snapshot tree fully, including trees with non-ASCII
   names; no `chflags`/`chmod -N` on Linux.
5. The three reserved taxonomy causes are produced by real Linux fixtures (not
   mocked) and classified exactly once.
6. Deterministic, no network, runs in CI.

## Dependencies / sequencing

Independent of A2 once A1 has decided the mechanism (A3 lives in `snapshot/`, the
mechanism lives in `sandbox/`). A4 needs both.
