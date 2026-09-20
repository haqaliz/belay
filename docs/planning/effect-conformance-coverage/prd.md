# PRD — effect-conformance coverage for an absent annotation contract

**Status:** DRAFT, awaiting owner decision at the review gate · **not started**
**Branch:** `feat/effect-conformance-coverage/aliz` · **Base:** `origin/master` @ `472ce3b` (v0.34.0)
**Capability:** C4 (A2 replay-verify — effect-conformance). No new capability, no new axis.
**Card:** `docs/planning/_card/issue.md`
**Baseline measured on this branch:** 2575 passed, 25 skipped, 13 deselected (18m37s) — green.

---

## Problem Statement

**Who has the problem.** Two populations, and they are the same defect seen twice:

1. **Every self-hoster running Belay against a real MCP server.** The pinned reference server,
   npm `@modelcontextprotocol/server-filesystem`, declares **no annotations**. Effect-conformance
   therefore abstains (*not-declared → UNVERIFIED*), worst-status-wins drags the turn to
   UNVERIFIED **even where result-equivalence passed**, and the user sees a **permanent 100%
   UNVERIFIED rate**. `verdict-coverage-status` already named this exact shape, for the network
   dimension, as *"a permanent 0% verified rate for a dimension Belay never claimed to check in
   the first place"* (`src/belay/verify/effect.py:366-372`).
2. **The Phase-0 mint.** The 2026-09-19 corpus-filling mint stopped at its own pre-registered
   gate with `NO_VERIFIABLE_TURNS: 2`, `INSTRUMENT SUSPECT`, UNVERIFIED 3/3 = 100%.

**Evidence it is real, and that it is pre-existing rather than a regression.** The 2026-08-12 run
that PROCEEDed carries `replayed but effect unverified` 8 and `UNRESTORABLE_SNAPSHOT_FAILED`
16/122. What differs is **scale**: a long run absorbs the abstention rate across hundreds of
turns; a 3-turn probe has it consume everything. The recorded owner decision is open, with a
recorded recommendation — *"Fix the instrument first… arguably the more valuable unit than the
mint itself"* (`docs/planning/phase0-corpus-mint/mint-run/STAGE1_FINDINGS.md`, `docs/STATUS.md:71-73`).

### The mechanism, corrected (this PRD must not inherit the overstatement)

**`docs/STATUS.md:65-66` says *"against annotation-less servers a corpus-filling mint can never
bank a per-turn case."* That is not what the code does, and correcting it is a deliverable.**

`reduce` ranks `FAIL (3) > UNVERIFIED (2)` and takes the max (`verify/verdict.py:67-73`,
`:114-117`), so a turn whose effect dimension abstains but whose A1 or result-equivalence
**decides a FAIL** still reduces to FAIL, enters `flagged_turns` (`phase0/runner.py:378`) and
banks normally. `add_case` enforces **no status precondition at all** — *"It enforces NO
precondition on the turn's verdict"* (`corpus/add.py:4-8`).

**What the abstention actually blocks is `VERIFIED_CLEAN`, and therefore the denominator.**
`replayed_any` is set only for a decided, non-UNVERIFIED **reduced** status
(`phase0/runner.py:353-376`); `violation_denominator()` counts only
`VERIFIED_CLEAN | VERIFIED_FLAGGED` (`phase0/ledger.py:216-218`, `:41`); a zero denominator with
≥1 instance trips `instrument_suspect` **trigger A** (`phase0/report.py:65-89`). The mint banked
nothing for a plainer reason than the abstention: **its two controls were honest negatives with
no FAIL to bank**, plus one turn with no manifest (`STAGE1_FINDINGS.md:76-80`).

**So the harm, stated precisely:** an honest clean run cannot be distinguished from a broken
instrument, so **no rate can ever be printed**, and every real user of an annotation-less server
sees 100% UNVERIFIED. That is a **product** defect (R7, *"the product says 'shrug'"*), not only a
mint defect — which is why the fix belongs in the verdict, not in the mint's gate.

### The root cause: four different claims wearing one status

`annotation_for_turn` (`verify/effect.py:161-231`) produces *not-declared* from **four** distinct
producers, and they do not mean the same thing:

| # | producer | file:line | what it means | correct status by `CLAUDE.md`'s definition |
|---|---|---|---|---|
| i | no `tools/list` snapshot precedes the call | `:202-210` | *"not-declared **for want of observation** rather than by the server's choice"* | **UNVERIFIED** — tried, could not |
| ii | tool absent from the most recent snapshot | `:215-223` | no observed contract for this tool | **UNVERIFIED** — tried, could not |
| iii | no / unreadable request frame | `:180-191` | could not read the call | **UNVERIFIED** — tried, could not |
| iv | **snapshot seen, tool in it, server shipped no `annotations` object** | `:225-231` | **there is no contract** | **`NOT_COVERED`** — never in scope |

`CLAUDE.md`: *"`UNVERIFIED` means 'we tried to check this and could not'; `NOT_COVERED` means
'this was never inside what Belay claims to check'."* Producers i–iii are failed attempts.
Producer iv is not an attempt at all — **conformance-checking a tool that declares no contract is
definitionally outside the check**. Collapsing all four into UNVERIFIED (`effect.py:556-566`, the
fall-through with no `if`) is the defect.

Producer iv is the pinned-npm case, and it is the only one the reference server exhibits.

---

## Goals & Success Metrics

| Goal | Measure |
|---|---|
| A turn against an annotation-less server can reach a decided verdict | On a capture from the pinned npm filesystem server, a replayed turn with a reproducing reply reduces to **PASS** with an `effect` `NOT_COVERED` sub-verdict, not UNVERIFIED |
| `VERIFIED_CLEAN` becomes reachable, so a rate can be printed honestly | Such an instance's disposition is `VERIFIED_CLEAN`; `violation_denominator() ≥ 1`; `instrument_suspect` False — **and `turn_status_counts` agrees with the printed rate** (no two-stories ledger) |
| A2 keeps its teeth | All 13 protection tests below stay green, unmodified |
| Genuine abstentions stay abstentions | Producers i–iii still UNVERIFIED, each with its named cause |
| No PASS travels without its coverage line | A coverage test **per surface**, including the four that have none today |

**Explicitly NOT a goal:** a higher verified rate as an end in itself. This is a
**reclassification, not improved detection** (below).

---

## Users & Scenarios

**The self-hoster.** Runs `belay verify` against the reference filesystem server, sees every turn
UNVERIFIED, and reasonably concludes the tool is broken. The stranger-path validation already
found three runbook defects of exactly this "reads as *the tool is broken*" shape
(`CHECKLIST.md`, 2026-09-06).

**The owner running a mint.** Needs `INSTRUMENT SUSPECT` to mean *the instrument is suspect* — not
*the server you pointed it at declines to annotate*.

---

## Requirements

### Must

1. **Split the not-declared status by producer.** Producer **iv** → `NOT_COVERED`, kind `effect`.
   Producers **i–iii** → `UNVERIFIED`, unchanged, each keeping its named cause.
   **The discriminator already exists with zero plumbing:** `TurnAnnotation.cause` is
   `Optional[str] = None` (`effect.py:117-133`); producers i–iii each return early **with** a
   cause string, producer iv falls through to the final return and leaves `cause` as **`None`**.
   (`ann.snapshot_seq is not None` is an equivalent second discriminator.)
1b. **Make the discriminator EXPLICIT — do not ship a status distinction resting on an
   accidental default.** `ann.cause is None` works today only because producer iv is the one
   return path that omits `cause=` and inherits the dataclass default (`effect.py:225-231` vs
   `:180-191`, `:202-210`, `:215-223`). That is **load-bearing by accident**, documented nowhere,
   and a future edit adding a `cause=` to `:225-231` would **silently merge the two populations**
   — re-collapsing exactly the distinction this unit exists to draw, with no test to notice.
   The live proof that the signal is unowned is requirement 10's wart.
   **Therefore:** carry the distinction on an explicit field rather than an absence.
   `facts["annotations_object"]` (`"present"|"absent"`) is already computed
   (`src/belay/annotations.py:73-81`, value at `:78`) and `facts` is already in scope at
   `effect.py:213` — one new `Optional[str]` field on `TurnAnnotation` (`:116-133`), set at the
   single return site, left `None` on the four abstaining paths. **No trace-format change, no
   schema bump, no new derivation, no other call site touched.**
   *Note it answers a narrower question than the split does* (absent object vs *empty* object —
   both are "no `readOnlyHint`"), so the explicit marker for the split may need to be its own
   field or an enum rather than `annotations_object` alone. Decide in `tech-plan`; the
   requirement is that the discriminator be **named and tested**, not inferred from a default.

2. **The declared-vs-silent distinction survives in the message**, per the precedent's
   requirement 6 — *"A reader must still be able to see that this tool made a promise we did not
   check, distinct from nothing was promised"*
   (`verdict-coverage-status/prd.md:99-102`).
3. **`reduce` is untouched.** `NOT_COVERED` is dropped before ranking
   (`verify/verdict.py:114`), never a reduced status, never promotes. The `_RANK` comment's rule
   stands: *"the filter, not the rank, is the mechanism"* (`:62-66`).
4. **No surface may render a turn's status without its coverage line — a test per surface.** The
   precedent's own hard rule (`verdict-coverage-status/prd.md:203-209`). This covers the **four
   surfaces with no coverage disclosure and no coverage test**: `belay corpus list`
   (`cli.py:2303`), `belay corpus run` aggregate on a MATCH (`cli.py:2065-2072`),
   `belay corpus score` (`cli.py:2194-2197`), `belay phase0 combine` (`phase0/report.py:786`).
5. **Coverage must be a persisted ledger field, not a runtime computation** — `phase0 report` is a
   pure re-render (`verdict-coverage-status/prd.md:90-93`). Confirm `not_covered_turns` admits a
   second kind or bump the schema deliberately. **Open question below.**
6. **Add a `_COVERAGE_PROSE` entry for the `effect` kind** (`phase0/report.py:145`), which has one
   entry (`effect:network`) today; an unlisted kind falls back to anonymous *"outside what Belay
   observes"* (`:198`) and **no test forces an entry**.
7. **Correct `docs/STATUS.md`**, quoting what it replaces (house style for corrections).
8. **State the reclassification and non-comparability**, in the house wording:
   *"the UNVERIFIED rate before and after this change is **not comparable** — the drop is a
   reclassification of turns Belay never had an instrument for, **not** improved detection."*
9. **No published number moves:** `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
   `recall 0.00`, `3/93` stand unedited. Nothing is recomputed.
10. **Fix the `(None)` message wart.** Producer iv currently renders *"did not declare
    readOnlyHint (None)"* to users (`effect.py:563` interpolates `{ann.cause}`, which is `None`
    on that path). Pre-existing, user-visible, fix it here.

### Should

11. Update prose that goes stale: `CLAUDE.md`'s *"today exactly one"* `NOT_COVERED` dimension,
    `README.md:283`/`:306`/`:308`, `test_coverage_rendering.py:53-56` (*"the only NOT_COVERED
    sub-verdict that exists today"*), `cli.py:1552-1556`, and `effect.py`'s module docstring
    rule table (`:18-25`).
12. Rename or narrow the four incidental tests' **vehicle** (below) rather than their assertions.

### Nice to have

13. A test asserting the `NOT_COVERED` kind set is exactly `{"effect", "effect:network"}` —
    nothing pins the set today, in either direction.

---

## Technical Considerations

**Change site:** `src/belay/verify/effect.py:556-566` (the NOT_DECLARED fall-through). Nothing
else in `effect.py` moves; branches for declared-true/false/non-boolean are untouched.

**Why this is not a new mechanism — it is the pattern already shipped.** A turn with result PASS
plus an unobservable `openWorldHint` **already** reduces to PASS with a `NOT_COVERED` sub-verdict
and **already** counts as `VERIFIED_CLEAN`. This applies the same treatment to one further case.
The instance is verified **because result-equivalence decided**, never because of the boundary —
which is the direct answer to `tests/test_coverage_rendering.py:412`'s
*"A coverage boundary must never manufacture a verified instance."* No boundary manufactures
anything here; `reduce` drops it.

**No predicate change is needed.** Because the reduced status becomes PASS, the existing
`replayed_any` predicate (`phase0/runner.py:353-376`) sets True on its own. The ledger keeps
telling **one** story: reduced status PASS, rate printed on genuinely decided turns.

### Measured blast radius (mutation-tested, not estimated)

A representative mutation (NOT_DECLARED → `NOT_COVERED`, kind unchanged) run against the full
suite: **exactly 9 new failures, 0 newly-green.** Under the narrower producer split, fewer — #2
below is expected to stay green.

**Pins the rule — revisit deliberately (4):**

| test | note |
|---|---|
| `tests/test_verify_effect.py:103` `test_a5_unannotated_tool_is_unverified_for_effect` | the rule's headline; producer iv |
| `tests/test_verify_effect.py:119` `test_a_call_with_no_preceding_snapshot_is_unverified` | producer **i** — **expected to stay green under the split**; *"A missing snapshot is not a permissive one"* |
| `tests/test_verify_effect.py:244` `test_effect_is_independent_of_result_equivalence` | subject is independence; needs rewording, not deletion |
| `tests/test_verify_turn.py:184` `test_result_pass_effect_unverified_reduces_to_unverified` | the turn-level flip. Exact analogue of `tests/test_verify_network.py:166`, whose docstring records inverting it as *"the deliberate act of this change"* — **use that as the template** |

**Incidental — not-declared is only a vehicle for manufacturing a replayed-then-UNVERIFIED turn
(5).** Fix = swap the vehicle to declared-non-boolean (`effect.py:545`) or declared-true with
`delta=None` (`:506`), both still UNVERIFIED. `tests/test_replayed_cause.py:94`, `:111`, `:144`,
`:165`; `tests/test_interop_attach.py:391`.

**Protection list — must stay green, unmodified (13).** These are the artifact proving A2's
semantics were untouched: `tests/test_verify_effect.py:79`, `:103`, `:119`, `:145`, `:161`,
`:244`, `:256`; `tests/test_verify_tool_not_offered.py:1189` (whole-`Verdict` equality
**including the message**, the anti-overreach guard); `tests/test_verdict_not_covered.py:91`,
`:135`, `:165`; `tests/test_verify_turn.py:184`; `tests/test_coverage_rendering.py:412`.

**The coverage sentence is duplicated across 8 render sites**; only the *data* helper
`verify/json.coverage_record` is shared (`json.py:196`, reused solely by `gate/check.py:64,331`).
The 8: `cli.py:1478-1487`, `cli.py:1567-1572`, `cli.py:751`+`:798`,
`interop/report.py:108-111`, `phase0/report.py:169-176`, `gate/check.py:422-432`,
`interop/export.py:109`, `console/src/components/CoverageLine.vue`. A new cause must reach each.

**The console is clean and is the model to copy** — fully pinned, renders `null` as *"coverage
unavailable"*, never a fabricated status (`TurnRow.vue`, `TraceView.vue`, `ReplayDialog.vue`).

### Verdict-contract impact

- **Axis:** A2 effect-conformance only. **No new axis, no new status** (`NOT_COVERED` exists),
  no change to A1, A3, or the reduction rule.
- **`UNVERIFIED` path preserved:** producers i–iii, declared-non-boolean, declared-true with no
  observed delta, and every boundary abstention keep their UNVERIFIED verdicts and named causes.
- **FAIL still reachable:** declared-true + non-empty delta is still a grounded FAIL
  (`tests/test_verify_effect.py:79` is a protection test).

---

## Risks & Open Questions

| # | Risk | Assessment |
|---|---|---|
| **R-A** | **It rewards server silence.** A server omitting `readOnlyHint` gets PASS where it got UNVERIFIED, and `CLAUDE.md:965-972` records omission as the **adversarial** move | **The named cost of this unit, and the owner's decision.** Mitigation: the coverage line is non-suppressible, so declaring still buys a verdict with nothing withheld. Argument it is acceptable: `CLAUDE.md` already states this axis *"catches nothing adversarial"* and that *"user-declared invariants remain the load-bearing A1 mechanism"* — so a turn-wide UNVERIFIED was never functioning as that defense. **Nothing in any document anticipates this inversion; state it as a new argument, not a re-litigation.** |
| **R-B** | The precedent points the other way mechanically — `network_subverdict` emits **nothing** for not-declared, *"so a turn's sub-verdict list is not padded with a boundary nobody asked about"* (`effect.py:337-347`) | Real. But emitting nothing means the coverage line carries nothing and a reader never learns the dimension went unjudged — which requirement 4 forbids. Emitting `NOT_COVERED` is the deliberate opposite choice, defensible on the precedent's other half (`reduce` drops it, the record keeps it, every surface renders it). **Record it as a choice, not a port.** |
| **R7** | UNVERIFIED dominates → *"the product says shrug"*; mitigation *"if it dominates, that's a gate signal"* | It dominated at 3/3 = 100%. This unit is the response to that signal. |
| **R5** | Over-claiming what A2 proves | The whole risk of getting this wrong; answered by requirement 4 and the protection list. |
| **R3** | *"Infer from MCP annotations first (free, zero-friction)"* is measurably hollow when the reference server declares none | Worth recording; **not this unit's job to fix.** |
| **R6** | False zero | **Not engaged by this design** (the reduced status genuinely becomes PASS). It *is* engaged by rejected Option A — see below. |

### Open questions

1. **Ledger schema:** does `not_covered_turns` admit a second kind, or does persisting an
   `effect` coverage dimension need a field / version bump? (Requirement 5 — resolve in `tech-plan`.)
2. **Does producer ii (tool absent from snapshot) belong with i–iii or with iv?** Drafted as
   i–iii (a failed observation). Arguable: if the tool is genuinely absent from a snapshot we
   *did* observe, that may be "no contract" rather than "unobserved". Decide before coding.
3. **There is no test coverage of the `replayed_any` predicate in either direction** — the canned
   fixture builds `sub_verdicts=[]` (`tests/test_phase0_runner.py:78-83`). Not changed by this
   design, but a named blind spot worth a test while we are here.
4. **A stale snapshot is a THIRD category this split does not name, and it bears on the split's
   own premise.** `annotation_for_turn` filters to `d["kind"] == "annotation_snapshot"` only
   (`effect.py:193-196`) and **never reads `annotation_staleness`**, which `derive_annotations`
   also emits. So a snapshot invalidated by an unre-snapshotted
   `notifications/tools/list_changed` is used **as if live**, and a tool whose annotation may have
   changed reads as cleanly declared. The trajectory rule already handles exactly this case by
   name (`TOOLSET_UNKNOWN` — *never FAIL on stale or unobserved knowledge*); **A2's effect axis
   does not.**
   This matters here because the split's premise is *"was the contract actually observed"*: a
   stale snapshot is **observed but possibly out of date**, which is neither producer iv's
   *"there is no contract"* nor i–iii's *"we could not observe one"*.
   **Drafted as out of scope** — it is a pre-existing gap on a different input (a
   `list_changed` the mint's servers do not send), and folding it in would widen the unit. But it
   must be a **named follow-up**, not silence, and if producer iv's `NOT_COVERED` is later read
   as *"the server declares nothing"* the staleness gap could make that claim wrong.

---

## Rejected alternatives

**Option A — leave `effect.py` alone; make the verifiability predicate consult sub-verdicts.**
**REJECTED on measured evidence.** Implemented and run: it breaks **zero** of 2497 tests — not
because it is safe but because the suite is blind there. The liveness run on the target
population shows what it does:

```
PRISTINE runner:  NO_VERIFIABLE_TURNS   denominator 0   turn_status_counts {'UNVERIFIED': 1}
PROBED runner:    VERIFIED_CLEAN        denominator 1   turn_status_counts {'UNVERIFIED': 1}
```

Applied to the real `mint-run` scenario, `NO_VERIFIABLE_TURNS: 2` / UNVERIFIED 3/3 = 100% /
`INSTRUMENT SUSPECT` / pre-registered STOP becomes **a printed clean 0% violation rate** with
`INSTRUMENT SUSPECT` silent, while the turn tally still reads `{'UNVERIFIED': 3}`. One ledger
telling two opposite stories, and the printed one is the **false zero** `CLAUDE.md` names twice
(*"`INSTRUMENT SUSPECT` refuses to print a rate — the R6 false-zero defense"*; *"never a clean
0%"*). It also silently redefines a documented contract — `phase0/runner.py:40-45` defines
"decided" at the **turn** level twice. Making it safe would need a rate-line guard plus a
REPLAYED-boundary test, i.e. **bigger** than the chosen option.

**Option C — all four producers → `NOT_COVERED`.** Rejected: it mislabels three genuine
abstentions as coverage boundaries, directly contradicting `CLAUDE.md`'s definition and
`test_a_call_with_no_preceding_snapshot_is_unverified`'s *"A missing snapshot is not a permissive
one."*

---

## Out of Scope

- Re-running the mint, or producing any Phase-0 number.
- `UNRESTORABLE_SNAPSHOT_FAILED` (cause #3 in the findings) — a separate defect.
- The A3 `--json` coverage-legibility gap (an absent `claim` key is ambiguous) — recorded
  separately, adjacent but distinct.
- R3's annotation-inference mitigation.
- Any change to A1, A3, the reduction rule, the trace format, or the corpus case schema.
- Committed junk at the repo root (`err.txt`, `err2.txt`, from `9d7ead2`).

## Related in-flight work

**PR #38 is OPEN and RED** (`feat/corpus-shell-routing/aliz`), 2 failed / 2256 passed:
`AttributeError: 'types.SimpleNamespace' object has no attribute 'shell_server'`
(`src/belay/cli.py:2383`, 2 tests), and `test_docker_inimage` failing its own unknown-skip⇒FAIL
rule on `replay-reinvokes-seatbelt`. It touches the corpus recompute path this unit also touches
— **land it first.**
