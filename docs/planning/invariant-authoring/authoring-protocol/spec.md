# Spec: `authoring-protocol` — the infer subcommand, the author seam, calibration

**Parent:** `docs/planning/invariant-authoring/prd.md` (M1, M2, M3)
**Status:** draft, pending review gate

## Problem slice

A model proposes task-specific invariants from a task spec; the engine validates
them, calibrates them against a known-clean control **by execution**, and emits a
reviewable artifact. The author is an out-of-process BYOK command — the engine
never calls a model. Fail-closed at every step: a bad author, a bad candidate, or
a calibration failure must never produce a policy file.

## In scope

- `belay invariant infer` (new top-level group `invariant`, subcommand `infer`):
  `--task <spec-file> --author <cmd> [--repo <dir>] --control <trace>
  [--manifest-dir <dir>] --server -- <CMD...> [--timeout N] [--replays N]
  --out <file> [--json]`.
- The author protocol: JSON on stdin (task spec text, optional bounded repo
  inventory, the known rule vocabulary with grounding semantics, library entries),
  JSON on stdout (`{"candidates": [{"scope", "rule", "rationale"}, ...]}`).
  Subprocess seam, injectable runner for offline tests (the
  `SubprocessAuthor` / `ClaudeCliModel` pattern).
- Candidate validation: known rules only (unknown → named rejection, never
  emitted); scope normalization; deterministic ordering.
- **Calibration by execution:** replay the control **once** with the candidate set
  through the shipped verify composition (`belay verify`'s own path — no second
  evaluator); a candidate yielding FAIL on any control turn is rejected
  (`CALIBRATION_FAILED`); PASS/UNVERIFIED are accepted. No survivor → exit 2.
- Artifact emission (schema owned by `artifact-trust`): atomic write,
  deterministic for fixed inputs.
- Fail-closed failure modes with named causes: `AUTHOR_FAILED`,
  `AUTHOR_OUTPUT_UNPARSEABLE`, `UNKNOWN_RULE`, `CALIBRATION_FAILED`,
  `CONTROL_UNREPLAYABLE`, `NO_AUTHOR_CONFIGURED`.
- Flag-parity: the flags `infer` shares with replay-bearing surfaces are declared
  in `tests/test_cli_flag_parity.py:57-134`.

## Out of scope

- The artifact's loader/trust rules (`artifact-trust`).
- The reference author (`reference-author`); tests here use the fake-author seam.
- Any model call in CI; any network.

## Acceptance criteria (testable)

1. **RED/GREEN fixture pair.** With a fake author proposing a known-good invariant,
   `infer` emits an artifact; `belay verify --invariants <artifact>` FAILs the
   corrupt-success fixture **at the exact turn** naming the invariant and the diff,
   and PASSes or abstains the clean control.
2. **Author failure is fail-closed.** Non-zero exit, timeout, unparseable output,
   or a missing `candidates` key → exit 2 with the named cause, **no artifact
   written** (no partial/empty file, pinned by asserting the path does not exist).
3. **Unknown rules are rejected, never emitted.** A candidate naming a rule outside
   `_KNOWN_RULES` (including `network-egress`) is rejected with `UNKNOWN_RULE`; if
   no candidate survives validation + calibration → exit 2, never an empty
   artifact.
4. **Calibration is execution.** A candidate that FAILs any control turn is
   rejected with `CALIBRATION_FAILED`; a candidate that PASSes or abstains is kept.
   A structural pin asserts calibration and `belay verify` invoke the **same**
   composition function (no parallel evaluator).
5. **A vacuous calibration emits nothing.** A control that cannot be replayed to a
   decision (unrestorable pre-state, tool not offered, every turn UNVERIFIED) →
   exit 2 with `CONTROL_UNREPLAYABLE`, no artifact, and never a `"calibrated"`
   record.
6. **Hostile task spec cannot launder a broad invariant.** A fake author induced
   by a hostile task spec to propose an over-broad candidate (e.g. whole-tree
   `read-only`) is rejected by calibration; no FAIL is ever emitted from it.
7. **Determinism.** Fixed fake author + fixed control + fixed task → byte-identical
   artifact on re-run (no timestamps, no randomness in the canonical bytes).
8. **Dark by default.** `infer` without `--author` exits 2 with
   `NO_AUTHOR_CONFIGURED`; no fallback, no model import.
9. **`--json` surface.** Reports candidates, rejections with causes, calibration
   result, and the artifact path; the text surface reports the same drops so the
   operator can fix the task spec or the control.
10. **Flag parity green.** The shared flags are declared; the table test passes.

## Dependencies and sequencing

Depends on `artifact-trust` for the schema/canonical form (shared helper) and on
the shipped verify composition for calibration. `reference-author` and
`corpus-fixtures` depend on this aspect.

## Open questions

- Should `--control` accept a banked corpus case (clean, expected PASS) as an
  alternative to a raw trace? Deferred; a raw trace is the first slice.
- Should `infer` write a rejected-candidates report to a sidecar file? Deferred;
  the `--json` output carries them for the first slice.