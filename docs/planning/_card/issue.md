# Brief — invariant-library

> Source: `belay-next` handoff (2026-09-12), run verbatim by the owner as
> `bbf feat invariant-library`. No GitHub issue exists; this is the inline brief.

**Build the common-invariant library that R3 names as the missing mitigation for
"nobody authors the invariant"** (`docs/ROADMAP.md` R3): a set of named, pre-authored,
user-selectable invariant declarations a stranger applies without writing JSON policy —
at minimum implementing the reserved names `no-create`/`no-delete` as real rules plus
network-egress and destructive-tool-scope entries, wired into the existing fail-closed
`load_invariants` loader (`src/belay/verify/invariants.py`) and `--invariants` on
`verify`/`phase0 run`/`corpus add`.

Acceptance tests first: every library entry loads and evaluates against a fixture trace
(no dead entries); a violating turn FAILs at the exact turn with the invariant and diff
named; each new entry ships a fixture corrupt-success case so the corpus compounds; an
unknown library name or unimplemented rule is exit 2, never a silent no-policy run.

Caveat: preserve the byte-prefix vs segment scope asymmetry between `read-only` and
`no-assertion-weakening` exactly, and do not touch any published number
(`11/60 = 18.3%`, `precision 0.00` stand unedited).

## Cross-references (from belay-next)

- `docs/ROADMAP.md` risk register, **R3**: *"Nobody authors the invariant — A1 works
  but only if someone declares the policy"* — High likelihood / High impact; mitigation:
  *"Infer from MCP annotations first (free, zero-friction); **ship a library of common
  invariants**; explicit Phase-2 experiment."* The annotation-inferred half shipped
  inside C5; the library half has not.
- `docs/ROADMAP.md` Phase 2 goals: *"The invariant-authoring problem (the known
  Phase-1 friction): who writes the invariant for a stranger's agent? … gets a real
  experiment, not an assumption."*
- `src/belay/verify/invariants.py`: the fail-closed `load_invariants` loader; three
  known rules today (`read-only`, `no-assertion-weakening`, `suite-before-success-claim`);
  `no-create`/`no-delete` are **reserved names, deliberately NOT accepted yet**, so an
  unimplemented rule cannot pass for an enforced one. Scope semantics are
  rule-dependent: `read-only` = raw byte-prefix, `no-assertion-weakening` = path segment.
- `src/belay/cli.py`: `--invariants` on `verify` / `corpus add` / `phase0 run`.
- `docs/technical/CAPABILITY_ROADMAP.md` C5: A1 is the axis that earns the 27–78%
  statistic; every violation is a labeled corrupt-success case — "the highest-value
  cases in the corpus".
- Launch checklist gate is TRUE (`docs/planning/launch-readiness/CHECKLIST.md`); the
  Phase-1 success metric is external "real catches" — the launch audience is strangers
  who will not write JSON policy. This unit is the Phase-1 half of R3; the
  "explicit Phase-2 experiment" on invariant authoring stays a later unit.