# PRD — invariant-library

Slug: `invariant-library` · Unit: `feat/invariant-library` (bbf, 2026-09-12) ·
Owner: aliz. Source: inline brief (`docs/planning/_card/issue.md`) + interview
decisions (2026-09-12, all four confirmed with recommendations).

## Problem Statement

R3 ("nobody authors the invariant — A1 works but only if someone declares the
policy", `docs/ROADMAP.md` risk register, High/High) is the last High/High Phase-1
adoption risk with an unshipped mitigation. The register's mitigation has three
parts: annotation-inferred invariants (**shipped inside C5**), **a library of common
invariants (NOT shipped)**, and an explicit Phase-2 authoring experiment (later
unit). The launch gate is TRUE (`docs/planning/launch-readiness/CHECKLIST.md`) and
the Phase-1 success metric is external "real catches" — strangers who will not write
JSON policy. Today a stranger has exactly two default-on rules
(`no-assertion-weakening` on tests/testing segments, the trajectory rule) and no way
to apply a named, common policy — "don't create files", "don't delete files",
"nothing under `tests/` or `src/` is written" — without hand-authoring a JSON
declaration file. `--invariants no-create` today exits 2 with "could not read
invariant file" — the name exists nowhere.

## Goals & Success Metrics

- **Goal 1 — R3's library mitigation ships.** Named, pre-authored, user-selectable
  invariant declarations; a stranger applies a policy by name on `verify` /
  `phase0 run` / `corpus add`, zero JSON authoring.
- **Goal 2 — No dead entries.** Every grounded library entry is proven to fire:
  a violating turn FAILs at the exact turn naming the invariant and the diff, and
  each entry carries a fixture corrupt-success case that banks and recomputes MATCH
  (corpus compounding, per C5's "every violation is a labeled corrupt-success case",
  `docs/technical/CAPABILITY_ROADMAP.md:377-378`).
- **Goal 3 — Honest boundaries.** Network egress is declared as exactly what Belay
  can observe: nothing. The egress entry is UNVERIFIED-with-named-cause on every
  turn, never PASS, and its listing says why. Tool-annotation scoping stays C4's
  lane (A1 has no annotation channel).
- **Measured by:** entry count with fixture cases (≥4 grounded entries, each with
  RED/GREEN + banked MATCH), unknown-name exit 2 pinned on all three surfaces, flag
  parity table green, producer-guard amended and green, published numbers unedited.

## User Personas & Scenarios

- **The stranger (launch audience).** Installs Belay, points the proxy at their MCP
  server, runs `belay verify`. Their agent writes to `src/` and occasionally deletes
  scratch files. They type `belay verify --invariant-library source-read-only
  --invariant-library no-delete` — no JSON. A delete turn FAILs at the exact turn,
  naming the invariant and the path.
- **The Phase-0 operator.** Runs `belay phase0 run --invariant-library no-create`
  across a mint; per-turn FAILs ingest as corrupt-success cases exactly as
  `--invariants file` FAILs do.
- **The curious skeptic.** Runs `belay invariant-library list`; sees every entry,
  its rule, its grounding (delta/content/instance), its scope semantics
  (byte-prefix vs segment), and the egress entry flagged as unobservable.

## Requirements

### Must-have

- **M1 — Two new delta-grounded rules.** `no-create` and `no-delete` join
  `_KNOWN_RULES` and `_DELTA_GROUNDED_RULES` (`src/belay/verify/invariants.py`),
  decided from the BTH-1 `FieldDiff` alone (created: `field is None and left is
  None`; deleted: `field is None and right is None`), **byte-prefix scope semantics
  like `read-only`** (interview decision — the prefix-vs-segment asymmetry is
  preserved exactly). FAIL names the invariant and the violating path(s); `delta is
  None` → UNVERIFIED; messages are rule-generic, never hard-coded "read-only".
- **M2 — The library table and resolver.** Module-level plain-data table
  `LIBRARY: name → entry` (declarations + description + grounding metadata). The
  resolver is a **deliberately amended third producer** of `Invariant` policy
  (interview decision): `test_no_invariant_is_ever_sourced_from_a_trace` admits it
  by name, and a new pin asserts library selection can never come from a trace.
  v1 entries: `no-create`, `no-delete` (whole-tree), `tests-read-only`
  (`{"scope":"tests/","rule":"read-only"}`), `source-read-only`
  (`{"scope":"src/","rule":"read-only"}`), `network-egress` (honest
  UNVERIFIED-only curated entry — see M3).
- **M3 — The egress entry is honest, and operator files stay safe.**
  `network-egress` is a curated library entry whose declaration evaluates
  **UNVERIFIED with a named cause on every turn** (Belay has no egress instrument;
  prior decision `docs/planning/invariant-verdict-a1/prd.md:110-113`, M4). The rule
  name **stays out of `_KNOWN_RULES`**, so an operator *file* declaring it is still
  rejected (exit 2) — the abstention loophole ("accepted by loader, grounded by
  none") cannot open for operator files; the curated entry is the only path, and it
  is documented + listed as unobservable. The evaluation catch-all gains a named
  cause/message for it.
- **M4 — Selection surface.** Repeatable `--invariant-library <name>` on `verify`,
  `corpus add`, `phase0 run` (flag-parity table in
  `tests/test_cli_flag_parity.py` updated); `--invariants <file>` keeps meaning
  "path to a JSON file" unchanged; both compose on top of the defaults. An unknown
  library name is **exit 2**, fail-closed, never a silent no-policy run (same
  contract as a malformed file, pinned on all three surfaces).
- **M5 — Discovery.** `belay invariant-library list` prints each entry: name,
  rule(s), scope semantics, grounding status, and a one-line honesty note for
  `network-egress`.
- **M6 — Per-entry fixture corrupt-success cases.** Each grounded entry has a
  fixture proving FAIL-at-exact-turn, and a banked case round trip (`add_case` →
  `corpus run` MATCH, house pattern in `tests/test_corpus_trajectory_run.py`). The
  egress entry has a fixture asserting UNVERIFIED-with-cause, never PASS.

### Should-have

- **S1 — README + help coverage.** A "library" section in README (entry table,
  scope semantics, the egress honesty line) and `--invariant-library` in the
  `verify` coverage text; `_VERIFY_COVERAGE` help stays truthful.
- **S2 — `no-create`/`no-delete` scoped via operator files** work exactly like
  `read-only` scoping (byte-prefix), covered by one scoped-operator-file test.

### Nice-to-have

- **N1 — `list` output renders scope semantics per rule** (byte-prefix vs segment)
  so the asymmetry is visible to the stranger.

## Technical Considerations

- **Seam:** resolution happens at the three CLI call sites in `cli.py` *before*
  `Path(args.invariants)`; library declarations flow through the same
  `evaluate_invariant` path as file-loaded ones. Loader signature
  (`load_invariants(path)`) and `default_invariants()` zero-arg pin are untouched.
- **Guard amendments (both deliberate):** (1) producer set grows by the resolver,
  pinned by a trace-can't-select test; (2) none needed for the rules — they join
  existing grounding sets; the partition test
  (`tests/test_invariant_trajectory_plumbing.py:249`) stays green. The egress rule
  is deliberately **not** in `_KNOWN_RULES` so the partition and the loader's
  fail-closed rejection are untouched.
- **`evaluate_invariant` signature is pinned** to
  `["inv", "delta", "turn_index", "roots"]` — the new rules are delta-only, no
  signature change.
- **Fixture style:** pure rule tests use real trees + BTH-1 `diff_records`
  (`tests/test_inferred_invariants.py` pattern); CLI-level tests use `TraceWriter`
  + fixture stdio servers under `tests/fixtures/` (darwin-gated,
  `replay-reinvokes-seatbelt`).
- **No published numbers move:** `11/60 = 18.3%`, `precision 0.00`, `1/15`,
  `4/16`, `recall 0.00` stand unedited; no verdict axis, invariant default, or
  coverage line changes; defaults unchanged.

## Risks & Open Questions

- **R-A: entry usefulness without demand.** The library's real value is validated
  by external self-hosters, not by this unit. Mitigation: entries are curated from
  observed Phase-0/launch shapes (tests/, src/, create/delete), and `list` makes
  them discoverable; per-repo authoring remains `--invariants file`.
- **R-B: egress entry reads as useless teeth.** A stranger selecting it gets
  UNVERIFIED everywhere. Mitigation: the listing says so before selection
  (grounding column), and the selection error/behavior is a named-cause honest
  boundary statement, never a false PASS.
- **R-C: guard amendments weaken the provenance story.** Both amendments are
  deliberate, named in the PRD, and pinned by tests that keep the guard's purpose
  (policy never from a trace; operator files never accept unimplemented rules).
- **Open:** whether `list` should support `--json` (deferred; N2 if requested).

## Out of Scope

- The Phase-2 authoring experiment (inferred-from-task-spec, per-repo libraries, an
  authoring UI) — R3's third mitigation, later unit.
- Annotation-driven A1 (C4/A2 effect-conformance's lane — already shipped).
- Per-repo library authoring (that is `--invariants file`).
- Any new verdict axis, invariant *default* change, or change to
  `suite-before-success-claim` framing ("the first invariant-library entry",
  `docs/planning/trajectory-success-invariant/prd.md:53`).
- Changing `read-only` or `no-assertion-weakening` scope semantics.

## Dependencies

C1–C6, C8, C9 shipped (v0.30.1). This unit touches only `src/belay/verify/`,
`src/belay/cli.py`, `tests/`, README. No new runtime dependencies (stdlib only).

---

## Self-critique (prd-generator, 2026-09-12)

| Dimension | Grade |
|---|---|
| Problem Definition | 🟢 Strong — R3-grounded, register-cited, exit-2 baseline named |
| User Understanding | 🟡 Needs work — personas are archetypes; no validated external need yet (none can exist pre-launch; stated in R-A) |
| Success Metrics | 🟡 Needs work — capability-shaped, not adoption-shaped (see gap 2) |
| Scope Clarity | 🟢 Strong — in/out explicit, asymmetry + numbers frozen |
| Edge Cases & Risks | 🟡 Needs work — three edges below not yet pinned |
| Stakeholder Alignment | 🟢 Strong — single owner; the review gate is the checkpoint |
| Feasibility Signal | 🟢 Strong — code-mapped seams, guard amendments named, signature pins cited |
| Go-to-Market | 🟡 Needs work — engine capability; adoption measured only by Phase-1 external self-hosters |

### Top 3 gaps

1. **🟡 Banked-case recompute path (aspect 3 must pin it).** `add_case` stores the
   resolved `Invariant` objects on the case and `corpus run` recomputes with the
   case's own invariants — so recompute must **never re-resolve the library name**
   (an entry's declarations changing later must not silently re-judge a banked
   case). The round-trip fixtures in `entry-fixtures` must assert recompute uses
   the stored invariants. Why it matters: silent re-resolution is a staleness
   hazard that would REGRESSION a banked case for reasons unrelated to the
   detector.
2. **🟡 Success metrics are capability-shaped, not outcome-shaped.** This unit
   cannot measure R3's actual outcome (strangers selecting entries) — that is the
   Phase-1 external self-hoster reports. State it explicitly: this unit's metrics
   are the process ones (entries × fixture cases, exit-2 pins, guard green,
   numbers unedited); the adoption metric is downstream and named, not claimed.
3. **🟡 `phase0 run` ledger path.** The ledger records the detector; the library
   flag must reach `run_batch` and the ledger/report exactly as `--invariants`
   does, or a library-declared run is misrecorded as a different detector. The
   aspect-2 parity work must cover the ledger's detector record, not just the
   flag.

### The hard question (owner decision at the gate)

A stranger who selects `network-egress` gets UNVERIFIED on **every** turn — the
honesty contract holds (never PASS), but will a launch-audience user read
all-UNVERIFIED as "Belay is broken" rather than "Belay is honest"? The alternative:
selection itself fails closed (exit 2, message naming the boundary and pointing at
`list`), so the only way to see the entry is the listing — harder to misread, but
the entry stops being selectable. The PRD as written ships the selectable form
(interview decision); the gate decides whether that stands.