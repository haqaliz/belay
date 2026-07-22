# Aspect spec — `record-workspace-root`

**Parent PRD:** `docs/planning/replay-absolute-path-fidelity/prd.md` (must-have 1)
**Sequencing:** FIRST. The prerequisite — relocation cannot remap without a trustworthy
FROM-prefix, and the original root is recorded nowhere today.

## Problem slice

The gate knows the original workspace root (`TurnGate._scope`, `gate.py:298`, from
`BELAY_SANDBOX_SCOPE`) but uses it only as the clone source (`gate.py:424`) and **never
persists it**. The snapshot manifest records the *clone* location (`tree_path`), not the
source (`persist.py:106-116`). So replay has no trustworthy original prefix to relocate
from. This aspect records it — and nothing else. It is a pure capture-side, backward-
compatible addition with no verdict behavior change on its own.

## In scope

1. **Write the original workspace root into the snapshot manifest** at persist time —
   `persist_snapshot` gains the field, fed from `gate._scope` at the call site
   (`gate.py:429`). Store the **realpath'd** absolute root (same normalization the scratch
   root uses), so the later prefix match is consistent.
2. **Read it back in `load_snapshot`** (`persist.py:119-148`) and expose it on the loaded
   snapshot object, defaulting to `None` when the field is absent.
3. **Thread it into `replay_turn`** (`engine.py` / `client.py`) so a later relocation step
   can consume it. This aspect only *plumbs* it through; it changes no verdict.
4. **Backward compatibility**, per the fail-closed manifest loader's style: a manifest
   written before this field existed loads cleanly with `root = None`. A present field must
   be a non-empty absolute string or it's a named `ValueError` (never a silent `None` from a
   malformed value — distinguish absent from malformed).
5. Field name + JSON shape decided here (proposal: `source_root`), consistent with the
   existing manifest schema and its validation.

## Out of scope

- **Any relocation / remap logic** — that's `replay-relocation`. This aspect must not change
  a single verdict; threading the root through unused is correct here.
- Recording the root in the trace (decided against — manifest, per-turn, is the home).
- The absolute-path fixture server (lives in `replay-relocation`, where it's exercised).

## Acceptance criteria (test-first)

1. `test_manifest_records_the_source_root` — a snapshot persisted through the gate/persist
   path carries the realpath'd original workspace root; round-trips through
   `persist_snapshot` → `load_snapshot`.
2. `test_manifest_without_source_root_loads_as_none` — a manifest JSON lacking the field
   (an old capture) loads with `root = None`, no error. **Backward compat.**
3. `test_malformed_source_root_is_a_named_error` — a present-but-non-absolute / blank
   `source_root` raises a named `ValueError`, not a silent `None`.
4. `test_source_root_is_realpathed` — a root passed with a symlink / non-canonical form is
   stored realpath'd, matching how the scratch root is normalized.
5. `test_replay_turn_threads_the_root_without_changing_any_verdict` — every existing replay
   verdict is **byte-identical** with the root plumbed through (it is recorded and passed but
   not yet consumed). Guards the "no behavior change" contract.
6. Existing manifest/persist/replay tests stay green — especially
   `test_persist_relative_tree.py` (the `tree_path` absolute-vs-relative backward-compat
   pattern this mirrors).

All deterministic, offline, CI-safe.

## Dependencies

None beyond the existing engine. Blocks `replay-relocation`.

## Open questions / risks

- **Per-turn vs per-run:** each turn's manifest gets the root. If the root is constant across
  a run (it is, for one mint instance), that's redundant but harmless and keeps replay's
  per-turn manifest self-contained. Confirm no code assumes a single run-level root.
- **Manifest schema validation:** match the existing loader's fail-closed idiom exactly
  (`persist.py` / the manifest dataclass), including how unknown/extra keys are treated, so
  forward-compat is preserved.
