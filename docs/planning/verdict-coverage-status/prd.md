# PRD — `verdict-coverage-status`

**Unit:** feat/verdict-coverage-status · **Owner:** aliz · **Date:** 2026-07-23
**Branch:** `feat/verdict-coverage-status/aliz` (off `master`)
**Inputs:** `docs/planning/_card/issue.md`,
`docs/planning/phase0-mint-execution/mint-execution/STAGE1_REMINT_FINDINGS.md` §2

---

## Problem Statement

`UNVERIFIED` carries two different meanings and the second silently consumes the first:

- *"We tried to verify this and could not"* — an honest abstention.
- *"This was never inside what Belay claims to check"* — a **coverage boundary**.

Because the second is folded into worst-status-wins, a turn where **replay reproduced, the
filesystem effect conformed, and the A1 invariant held** still reduces to UNVERIFIED whenever
the tool declared `openWorldHint: false` — a network posture Belay structurally cannot observe.

The reference `@modelcontextprotocol/server-filesystem` declares exactly that. So **every turn
of every instance is permanently UNVERIFIED** for any user of the reference server. The
Phase-0 mint's denominator is **structurally zero** regardless of agent behavior; Stage 1
measured 12/12 UNVERIFIED, `NO_VERIFIABLE_TURNS`, `INSTRUMENT SUSPECT`.

**The perverse incentive** is the sharpest symptom: an un-annotated tool and a permissive
`openWorldHint: true` both return `None` and are *not* folded in, so a server that **honestly
declares** a closed posture gets a strictly **worse** verdict than one that stays silent.

**Cost of the status quo:** the Phase-0 gate cannot be cleared through the MCP filesystem
path at all, and every Belay user running the reference server sees 100% UNVERIFIED.

---

## The counter-argument, stated fairly before we build over it

The current behavior is **not an oversight**. `effect.py:317-324` defends it explicitly:

> "This asymmetry is load-bearing: folding an always-UNVERIFIED verdict into EVERY turn would
> drag every un-annotated turn (the common case) to UNVERIFIED. A turn is downgraded only when
> the tool made a network promise we genuinely could not check."

Put plainly: a tool that promised *"I do not reach the open world"* made a **checkable promise
Belay cannot check**, and a turn containing an unchecked promise is arguably not a verified
turn. Reclassifying it converts a *tool-specific unverified promise* into a *categorical
coverage boundary* — a genuinely different statement, and one that makes declared-false and
not-declared less distinguishable in the reduction.

**And the load-bearing risk:** under this change, a `read_text_file` turn against a server that
swore `openWorldHint: false` will print `PASS`. `README.md:48` and `CLAUDE.md:251` both say
*"UNVERIFIED is never rendered as PASS."* A status in the reduction cannot be scrolled past; a
banner can. **If the coverage statement is easy to miss, this change makes Belay less honest.**

**Why we proceed anyway:** `render_openworld_verdict` already returns UNVERIFIED for *every*
`openWorldHint` state, and `network_subverdict` already declines to fold that in for the
un-annotated case. The asymmetry the docstring calls load-bearing is *already* asserting that
an unobservable network dimension should not lower a turn — this change extends the same
reasoning to the honestly-declared case. But it **is a reversal of a stated decision, not a
bugfix**, and this document commits to it as such, with the mitigations below.

---

## Goals & Success Metrics

| Metric | Target |
|---|---|
| A clean turn against the reference filesystem server | **PASS**, not UNVERIFIED |
| Existing PASS / FAIL verdicts changed by this unit | **zero** (test-enforced) |
| `NOT_COVERED` rendered/reduced/summarized as PASS | **never** (test-enforced, exhaustive over the status enum) |
| Coverage statement reachable from a stored ledger | **always** — `belay phase0 report` must show it |
| UNVERIFIED turns with cause `unknown` | **zero** (gate requirement) |
| Suite | green, no existing test weakened |

---

## Requirements

### Must-have

1. **`NOT_COVERED` is a SUB-VERDICT-ONLY status. It can never be a turn's reduced status.**
   `reduce` filters it out; if nothing remains, the result is **`UNVERIFIED`**, never
   `NOT_COVERED`. This is the single most important design decision in this unit — see
   *Technical Considerations* for the three silent-false-PASS sites it defuses.
2. **Both orderings change together.** `verdict.reduce` (`verdict.py:73-82`) and the CLI's
   duplicate `_worst` (`cli.py:625-633`, which decides the **exit code** at `cli.py:550`).
   A divergence means the rendered verdict and the exit code disagree.
3. **The aggregate block must print it.** `cli.py:583-589` prints four hard-coded status
   lines; a `NOT_COVERED` sub-verdict currently appears **nowhere**. That is the #1
   false-PASS risk in the change.
4. **The coverage statement must be a LEDGER FIELD, not a runtime computation.**
   `belay phase0 report` (`cli.py:1076-1114`) is a pure re-render of the ledger, so anything
   not persisted cannot appear there — and a verdict rendered without its coverage boundary is
   exactly the failure this unit exists to prevent.
5. **The coverage statement is not suppressible** and travels with the verdict on every
   surface: `belay verify` per-turn + aggregate, the existing always-on coverage banner
   (`cli.py:430-449`), `phase0 run`, `phase0 report`, the ledger, and corpus cases.
   In `report.py` it must sit **outside** the `INSTRUMENT SUSPECT` branch (`:122-127`), which
   suppresses the headline.
6. **The declared-false vs not-declared distinction must survive** in the sub-verdict message
   even though it no longer moves the reduction — this is the direct answer to the
   counter-argument. A reader must still be able to see that *this tool made a promise we did
   not check*, distinct from *nothing was promised*.
7. **Cause on the REPLAYED path.** `turn.py:227-233` returns `cause=None` unconditionally, so
   every replayed-but-reduced-UNVERIFIED turn buckets as `unknown`. Fix requires **both** a
   cause on that path **and** a stable label in `_PREFIX_LABELS` (`replay/report.py:91-98`) —
   otherwise `canonical_cause` falls through (`report.py:117`) and produces one bucket per
   turn, which is no better than `unknown`.
8. **`phase0/runner.py` must decide `replayed_any` explicitly** (`runner.py:196-202`). Today
   a `NOT_COVERED` sub-verdict would set it `True` **by accident**; the direction is right but
   it must be written as a decision with a test.
9. **`belay phase0 run --ledger` must create parent dirs** (`cli.py:1067`) — the only
   unguarded write in the CLI, and it discards a completed verification run.
10. **Corpus compatibility, decided and stated:** `_KNOWN_STATUSES` (`corpus/case.py:50`) is
    fail-closed, so a case carrying `NOT_COVERED` in `sub_verdicts[]` raises on load by an
    older Belay. Add the status; **document that new cases are not readable by pre-change
    versions.** Additionally, stored cases whose network sub-verdict flips
    `UNVERIFIED → NOT_COVERED` become **REGRESSION** under `belay corpus run`
    (`corpus/run.py:198-201`, exact-set comparison) — expected, and it must be called out
    rather than discovered.

### Should-have

11. **A schema version decision.** There is **no version field anywhere** — not in the ledger
    (`ledger.py:140`), corpus cases (`case.py:92-105`), or the trace. `case.py`'s
    `_REQUIRED_FIELDS` is a closed tuple, so any new field must be optional-with-default or it
    breaks every existing case. Recommend: add an optional `schema_version` to corpus cases
    now, while the corpus is small and local.
12. **Update the doc-level enumerations**: `CLAUDE.md:143-145`, `README.md:149-151` axis
    tables, and the `belay verify` coverage banner wording (currently says egress "is
    UNVERIFIED"; must become NOT_COVERED **without weakening**).
13. **Add `NOT_COVERED` to the leakage guard** (`tests/test_containment.py:421`).

### Out of scope

- The `replay` engine's separate `REPLAYED`/`UNVERIFIED`/`NOT_VERIFIABLE` namespace
  (`replay/report.py:161-169`) and the `Disposition` enum — parallel, do not touch.
- Making network egress observable. That is a real capability, not a status rename.
- `replay-relocation-shell`; the mint itself.

---

## Technical Considerations

**Capability:** hardens C4 (A2 effect-conformance) and the verdict contract. No new axis.
**Verdict impact:** this changes *what a turn's status means* — the reason it is its own unit.

### Why sub-verdict-only is load-bearing (three silent false PASSes it defuses)

If `NOT_COVERED` could be a **reduced** status:

1. **`corpus/metrics.py:139-152`** — not FAIL, so `positive=False`; with a `false-positive`
   label it scores as **`tn`**, with `true-positive` as **`fn`**. That is the
   "could-not-check → checked-and-cleared" fold the module docstring at `:24-27` forbids.
2. **`corpus/case.py:164-169`** — fail-closed load; a case with that `reduced_status` raises.
3. **`phase0/ledger.py:109-114`** — `total_turns()` sums *all* `turn_status_counts` values with
   **no key validation**, so an older reader silently folds an unknown status into its
   denominator.

Filtering inside `reduce` (rather than at each call site) is required because there is already
one forgotten mirror of the ordering (`cli.py:630`); adding a filtering obligation to every
future caller guarantees another.

### Full enumeration-site list

The dig enumerated **18 sites** that match on `Status` exhaustively or enumerate it in prose;
they are recorded in the aspect spec and each needs an explicit decision. The dangerous class
is not the ones that raise `KeyError` (fail-loud, fine) but the ones that **silently drop**:
`cli.py:583-589` (aggregate counts), `cli.py:591-609` (detail lists), `cli.py:617-621`
(`_first_unverified_message` returns the literal `"unverified"`), and `report.py:139-158`.

---

## Risks & Open Questions

| Risk | Assessment |
|---|---|
| **A PASS reads as "network verified"** | **The top risk.** Mitigated by requirements 3, 4, 5, 6 and an exhaustive never-reads-as-PASS test. If we cannot make the coverage statement unmissable, we should not ship this. |
| Reversing a deliberately-argued decision | Acknowledged above and committed to explicitly; the `effect.py` docstring must be rewritten to state the new reasoning, not silently deleted. |
| Corpus REGRESSIONs on existing cases | Expected and stated (requirement 10). `corpus/local/` is gitignored and small. |
| Old Belay cannot read new corpus cases | Accepted; drives requirement 11. |
| R7 — UNVERIFIED rate | This *lowers* it legitimately. The gate must not read that as improved detection: the Phase-0 write-up must state that the UNVERIFIED rate before/after this change is not comparable. |

**Open questions**
1. Should `network_subverdict` now also emit `NOT_COVERED` for the **not-declared** and
   **declared-true** cases (currently `None`)? It would make coverage counting uniform, but
   changes far more turns. Recommend **no** for this unit — keep `None`, and revisit.
2. Does the coverage statement belong per-instance or per-run in the ledger? Per-instance is
   more precise; per-run is cheaper. Decide in the plan.

---

## Self-Critique

| Dimension | Score |
|---|---|
| Problem Definition | 🟢 measured, not theorized — Stage 1 produced the 12/12 |
| Success Metrics | 🟢 all testable; "zero existing verdicts changed" is enforceable |
| Scope Clarity | 🟢 explicit out-of-scope for the parallel status namespaces |
| Edge Cases & Risks | 🟢 18 enumeration sites catalogued; the counter-argument is quoted, not paraphrased |
| Feasibility | 🟢 no new dependency, deterministic, offline |
| Verdict Honesty | 🟡 **this is the unit that could damage it** — see gap 1 |

### 🟡 Gap 1 — the honesty claim now rests on a rendering, not a status

Before this change, "we did not verify the network" was enforced by the reduction. After, it
is enforced by a coverage statement that must appear on every surface. That is strictly weaker
unless requirement 5 is airtight. **Recommended hard rule for the plan: no surface may render a
turn's status without also rendering its coverage line — enforced by a test per surface, not by
review.**

### 🟡 Gap 2 — "zero existing verdicts changed" is untestable in the strong sense

We can assert it over the fixture corpus and the test suite, not over all possible traces. The
honest claim is "no test-covered verdict changed, and the network dimension is the only
dimension whose contribution changed" — say that, not more.
