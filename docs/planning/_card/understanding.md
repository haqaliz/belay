# Understanding — invariant-library

Unit: `feat/invariant-library` (bbf, 2026-09-12). Source: inline brief
(`docs/planning/_card/issue.md`). No GitHub issue exists.

## What the work is really asking

R3 ("nobody authors the invariant — A1 works but only if someone declares the policy",
`docs/ROADMAP.md` R3, High/High) has three named mitigations: annotation-inferred
(shipped inside C5), **a library of common invariants (NOT shipped)**, and an explicit
Phase-2 authoring experiment (later unit). The launch gate is TRUE
(`docs/planning/launch-readiness/CHECKLIST.md`); the Phase-1 success metric is external
"real catches" — strangers who will not write JSON policy. This unit makes A1 usable by
name: named, pre-authored, user-selectable invariant declarations.

## The seam (from code mapping)

- `src/belay/verify/invariants.py`: fail-closed `load_invariants(path)` is the ONLY
  producer of `Invariant` policy, plus `default_invariants()` (zero args, pinned).
  `tests/test_invariants.py` **structurally pins the producer set** — any new callable
  annotated `-> list[Invariant]` breaks the build. The library must be module-level
  **plain data** (name → declaration dicts) resolved **at the CLI boundary in
  `cli.py`**, before `Path(args.invariants)` — today `--invariants no-create` already
  exits 2 (no such file), which is the baseline an unknown name must keep.
- **Grounding sets partition `_KNOWN_RULES`** (pinned by
  `tests/test_invariant_trajectory_plumbing.py`): every rule lands in exactly one of
  CONTENT_GROUNDED / DELTA_GROUNDED / INSTANCE_LEVEL, or the build breaks. The two new
  rules (`no-create`, `no-delete`) are **delta-grounded** — decidable from the BTH-1
  `FieldDiff` alone (`field is None and left is None` = created; `right is None` =
  deleted) — no content trees, no signature change (`evaluate_invariant` is pinned to
  `["inv", "delta", "turn_index", "roots"]`).
- **Scope asymmetry is load-bearing and must be preserved exactly** (`read-only` =
  byte-prefix, `no-assertion-weakening` = path segment; the module docstring forbids
  unification). New delta-grounded siblings follow `read-only`'s byte-prefix semantics.
- **Network-egress cannot be grounded**: prior decision
  (`docs/planning/invariant-verdict-a1/prd.md:110-113`, M4; `invariants.py:225-229`)
  — Belay has no egress instrument, so a network entry is UNVERIFIED-only by
  construction. The brief's "network-egress entry" must ship as an **honest
  UNVERIFIED-only named declaration** (or be deferred — interview decision).
- **destructive-tool-scope cannot read tool annotations** (A1 has no annotation
  channel; tool-annotation conformance is C4/A2 effect, already shipped). A
  destructive-scope entry must be re-expressed as a delta-expressible filesystem
  policy — which is what `no-create`/`no-delete` are.
- `--invariants` surfaces: `verify` / `corpus add` / `phase0 run` (`cli.py:2522, 2651,
  2895`), pinned by `tests/test_cli_flag_parity.py` — a new flag must be declared
  there. Fail-closed: malformed file / unknown rule = exit 2, never a silent
  no-policy run (pinned on all three surfaces).

## Corpus compounding

C5's promise: every violation is a labeled corrupt-success case
(`CAPABILITY_ROADMAP.md:377-378`). House fixture pattern: real trees + BTH-1
`diff_records` for pure rule tests; `TraceWriter` + fixture stdio server
(`tests/fixtures/*_server.py`, darwin-gated) for CLI-level tests; banked-case
round trip via real `add_case` + `corpus run` MATCH (pattern in
`tests/test_corpus_trajectory_run.py`). Note: `corrupt_success_case()` in
invariants.py is a dead seam (no src caller) — fixture cases bank through
`add_case` directly. Per-entry fixture corrupt-success cases prove the
compounding.

## Open questions for the interview

1. Entry list and per-entry default scopes (which named presets ship in v1?).
2. Selection surface: `--invariants <name>` resolution vs a new `--invariant-library`
   flag vs `lib:<name>` syntax; and a `belay invariant-library list` discovery command?
3. Network-egress entry: ship as honest UNVERIFIED-only declaration, or defer with a
   named reason?
4. Provenance-guard amendment: the producer-set test must be **deliberately amended**
   (library = operator-chosen policy, module data, never from a trace — the guard's
   purpose survives, its producer set grows by one named member) vs data-only dodge.
   House precedent for deliberate guard amendments exists (flipped compose test).

## Constraints that must not move

- `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00` — unedited.
- Defaults unchanged (`default_invariants()` zero-arg, default-on behavior).
- UNVERIFIED-never-PASS; fail-closed loader; provenance boundary (policy never from a
  trace); scope asymmetry; flag parity; suite-before-success-claim framing as "the
  first invariant-library entry" (`docs/planning/trajectory-success-invariant/prd.md:53`).