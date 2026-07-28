# PRD — `phase0-corpus-audit`

**Status:** draft, pending review gate · **Owner:** aliz · **Branch:** `feat/phase0-corpus-audit/aliz`
**Capability:** C6 (failure corpus) follow-on slice — the **Phase-0 gate** work, not a new C-id
**Inputs:** `docs/planning/_card/issue.md` (brief), `docs/planning/phase0-corpus-audit/understanding.md` (deep dig)

---

## Problem Statement

The Phase-0 → Phase-1 gate cannot currently be **decided**, and — separately — the premise the
operative docs use to reason about it is **wrong**.

**The gate is undecidable.** Seven failure-corpus cases sit at `human_label: pending`. Because
`metrics.score` excludes unadjudicated labels by construction (`metrics.py:130-132` — the
label-trap defense), `belay corpus score` reports `pending: 7` and `n/a` for precision, recall
and coverage. There is no measured false-positive rate to publish and no true-positive count to
read the pre-registered criteria against. `PHASE0_RESULTS.md` is entirely `TO-BE-FILLED`.

**The criteria are also unrecordable.** The gate requires *"≥3 **independent** hand-audited true
positives"*, with *"each TP's root cause recorded beside it so a reader can judge independence
directly"* (`PHASE0_RESULTS.md:38,135`; `RUNBOOK.md:424-425`). The case format has **no field for
a root cause** (`case.py:89-113`) and `Metrics` has **no notion of independence**
(`metrics.py:92-102`). Even a perfect audit could not be written down in the corpus.

**And the stated premise is false.** `CLAUDE.md:76-78` and `CAPABILITY_ROADMAP.md:388-392` assert
the corpus is *"one root cause observed seven times"*, and conclude that further minting yields
more of the same. Decoding each case's target `tools/call` payload shows **three structurally
distinct shapes** (understanding §2). That claim is currently driving the decision about whether
to spend 15–20h and a provider quota on a resumed mint.

### Evidence this is real

| Claim | Evidence |
|---|---|
| 7 cases, all unadjudicated | every `case.json` lacks `human_label` → defaults `pending` (`case.py:226`) |
| Root cause has nowhere to live | `_to_payload` writes a fixed key set (`case.py:116-131`) |
| A loose JSON key would be destroyed | `set_label` = `load_case` → `replace` → `write_case` (`curate.py:50-52`) |
| Independence is uncomputed | `score()` reads exactly two fields (`metrics.py:114-122`) |
| "One root cause" is wrong | three shapes, per-case payloads in understanding §3 |
| The one corrupt-success TP does not survive | upstream `7c526140` makes the same change (understanding §6a) |

---

## Goals & Success Metrics

| Goal | Measure |
|---|---|
| The gate becomes **decidable** | `belay corpus score` reports 0 `pending`; precision and coverage are real numbers, not `n/a` |
| Each TP carries a machine-groupable root cause | every `true-positive` case has a `root_cause.key`; enforced fail-closed |
| Independence is **computed**, not hand-counted | `corpus score` prints both the primary and strict independent counts |
| The negative result is published honestly | `PHASE0_RESULTS.md` FP/TP sections filled; **no `PROCEED`** |
| The false premise is corrected at source | `CLAUDE.md` + `CAPABILITY_ROADMAP.md` state three shapes, not one |
| Regression safety | `belay corpus run` still MATCHes; full suite green (baseline **966 passed, 1 skipped**) |

**Explicit non-goal as a metric:** clearing the gate. The denominator is **16** against a
pre-registered **≥50** (`PHASE0_RESULTS.md:85`). Success here is a *decision*, not a PROCEED.

---

## User Personas & Scenarios

**The person deciding whether to spend the next mint.** Today they read
`CAPABILITY_ROADMAP.md:397` — *"this is an invariant problem, not a sample-size problem"* — and
must take it on trust. After this unit they run `belay corpus score` and read the independent TP
count with its root causes, and can see *which* shapes the invariant is over-firing on.

**A skeptical reader of the Phase-0 write-up** (the ICP for the whole gate — an investor, a
design partner, or the founder in three months). They ask "three flags from one mis-annotated
tool count as one finding — how do I know these seven aren't that?" Today the answer is prose.
After this unit it is a printed number they can re-derive from a committed ledger.

---

## Requirements

### Must-have

**M1 · `Case.root_cause` — an optional, human-authored, structured field.**
Shape `{"key": <kebab-case str>, "note": <str>}`. `key` is what the metric groups on; `note` is
what a reader judges. **Absent stays absent** — when unset, `_to_payload` **omits the key
entirely** rather than writing `null`, because in this repo *"a default is never a declaration"*
(`CLAUDE.md`, on annotation defaults) and absent must stay distinguishable from declared-empty.
Optional on load and **not** added to `_REQUIRED_FIELDS`, following the `schema_version`
precedent (`case.py:64-69`) whose stated reason — *"a required new field would reject every case
already sitting in `corpus/local/`"* — describes exactly our 7 cases. Malformed shape (a bare
string, a missing `key`, a non-kebab key) is a **named `ValueError`**, never a silent default.

**M2 · `root_cause` is REQUIRED to label a case `true-positive`.**
`set_label` rejects a `true-positive` with no root cause, fail-closed, before touching disk —
mirroring its existing rejection of an unknown label (`curate.py:42-47`). `false-positive` and
`unverifiable` may omit it. Rationale: the criteria demand a root cause beside every TP, so a TP
without one is a TP the gate cannot evaluate.

**M3 · `Case.target_tool` — optional, so the strict clause is computable.**
The strict independence clause needs `(instance, tool)`. Instance is derivable from
`provenance.source_trace_id` (already present). The **tool is not in `case.json` at all** — it is
in the trace. Add it as an optional field, populated by `corpus add` going forward and backfilled
for the 7 existing cases from their own `trace.jsonl` (deterministic; the trace ships inside the
case dir). **Absent → the strict count is `n/a` with its reason printed, never guessed.**

**M4 · `corpus score` reports both independence readings.**
```
TP                        N
TP (independent)          K   [distinct root-cause keys]
TP (independent, strict)  M   [distinct instance+tool]
```
The primary clause (distinct root causes) is the criteria's real rule; the strict clause is its
stated minimum. **Both print**, because on this corpus they disagree and printing only the
flattering one is the failure mode pre-registration exists to prevent. A TP missing a
`root_cause` cannot occur (M2); a TP missing `target_tool` makes the strict count `n/a`.

**The strict clause is ambiguous in the pre-registered text, and this is the reading we
implement.** The criterion reads *"distinct instances **and** distinct tools"*, glossed *"three
flags from one mis-annotated tool count as **one** finding"* (`PHASE0_RESULTS.md:38`). Those
support two different computations on this corpus:

| Reading | Computation | This corpus |
|---|---|---|
| **Distinct pairs** | count distinct `(instance, tool)` | **3** — `(4045, edit_file)`, `(4992, edit_file)`, `(5859, edit_file)` |
| **Both dimensions must vary** ← *implemented* | a group is independent only if it differs in instance **and** tool | **1** — the tool never varies |

**We implement the second**, because it is the reading the pre-registered *gloss* states outright
and it is the harder bar — clearing it clears both. The criteria are pre-registered and may not
be reinterpreted to taste once the data is visible; picking the more permissive reading *after*
seeing that it triples the count is precisely the move pre-registration forbids. The chosen
reading is named in the output, and `AUDIT.md` reports the other number too so a reader can see
what the choice cost.

**M5 · `score()` stays pure and stays honest.**
It gains a third and fourth field to read but performs no I/O, consults no clock, and reads
**nothing the engine computed**. A root cause is human-authored — it must never be derived from
the sub-verdict set, which would make "independence" a function of the engine's own output and
reintroduce the label-trap (`metrics.py:11-23`) one level up.

**M6 · Adjudicate all 7 cases**, from the observed delta and upstream comparison — never from the
engine's verdict. `trace-pallets__flask-4045-turn8` is already adjudicated **`false-positive`**
(decision recorded 2026-07-28, evidence in understanding §6a).

**M7 · `AUDIT.md`** recording, per case: the observed change, the shape (A/B/C), the root cause,
and the adjudication with its reasoning. Plus, stated not implied:
- the **three shapes**, correcting the "one root cause" claim;
- the corrupt-success subset reported **separately** from the raw A1 rate
  (`STAGE2_FINDINGS.md:89-92`);
- **Stage 3 captured none of its three controls**, so this audit has **no false-positive guard**
  (`CAPABILITY_ROADMAP.md:405-406`);
- pre-registration is a timing control, **not** an independence control — one person wrote the
  criteria, minted, audited and published (`PHASE0_RESULTS.md:65`).

**M8 · Fill `PHASE0_RESULTS.md`** — the FP-rate and hand-audited-TP sections, plus the Decision
line. **Never `PROCEED`** (denominator 16 < 50). Every rate carries its denominator
(`RUNBOOK.md:430`).

**M9 · Correct the false premise at source** — `CLAUDE.md` and `CAPABILITY_ROADMAP.md:388-392`.
Also fix the stale test count (`CLAUDE.md` says 832; the tree measures **966**).

### Should-have

- **S1** · `corpus show` renders `root_cause` (key and note) and `target_tool`.
- **S2** · `corpus list` gains a root-cause-key column, so the shape distribution is visible at a
  glance without opening seven cases.
- **S3** · `corpus add` records `target_tool` for every newly ingested case.

### Nice-to-have

- **N1** · `corpus score --by-root-cause`: a breakdown of TP/FP per root-cause key. This is the
  direct input to `invariant-test-mutation-shape` — it answers "which shape is the invariant
  over-firing on?" — but the same information is legible from `AUDIT.md` for 7 cases.

---

## Technical Considerations

**Capability & phase.** C6 follow-on, Phase 0. Dependencies C1–C6 are all built and merged.
Nothing here blocks on C7–C9.

**Verdict impact: NONE.** This unit changes no verdict on any axis. It touches human ground-truth
labels and the metric computed over them. `expected` stays byte-identical — the D3 boundary
(`curate.py:1-13`) — and A1/A2/A3 semantics are untouched. There is no new `UNVERIFIED` path
because no new check is introduced; the honesty burden lands instead on **absent-never-guessed**
(M1, M3) and on the strict count's explicit `n/a` (M4).

**The load-bearing implementation constraint.** `set_label` round-trips through the frozen
dataclass (`curate.py:50-52`) and `write_case` serializes only `_to_payload`'s fixed keys
(`case.py:116-131`). A `root_cause` written as a loose JSON key would be **silently erased by the
next `corpus label` call** — the audit's own record would destroy itself. It must be a real
`Case` field. This is the single most likely way to build this wrong.

**Backward compatibility is not optional.** All 7 existing cases predate both new fields, and
`corpus run` compares recomputed sub-verdicts against stored ones exactly
(`PHASE0_RESULTS.md:149`). Both fields must be additive, absent-tolerant, and must not perturb
`expected`. A regression in `corpus run` that touches any axis other than `A2 / effect:network`
is a real one.

**Determinism.** No network in the engine change. The `target_tool` backfill parses committed
trace bytes and is re-runnable to the same result. The upstream gold-patch comparison used for
adjudication reads **cached bare clones** already on disk (`eval/clones/`) — no network there
either.

**No raw-data egress.** The corpus stays gitignored and in place. `AUDIT.md` quotes case ids,
shapes, root causes and small illustrative diffs — never raw workspace state.

**The corpus is not movable.** Manifests embed absolute snapshot paths. All commands use
`--corpus-dir /Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/corpus/local`.
The `feat-verdict-coverage-status` worktree must not be removed or relocated.

---

## Data Model

```jsonc
// case.json — additive; both new keys OMITTED when absent
{
  "id": "trace-pallets__flask-4045-turn8",
  "human_label": "false-positive",
  "root_cause": {                              // NEW, optional; required iff true-positive
    "key": "required-test-update",             // kebab-case; the grouping key
    "note": "upstream 7c526140 deletes the same test; the edit was required"
  },
  "target_tool": "edit_file",                  // NEW, optional; enables the strict clause
  "expected": { /* UNCHANGED, byte-identical */ }
}
```

---

## Anticipated outcomes — state the modal result BEFORE measuring it

Pre-registering the expected result is the same discipline as pre-registering the criteria: it
stops the write-up from being shaped by what the number turned out to be.

**The modal outcome is `precision = 0.0`.** `flask-4045` t8 is adjudicated `false-positive`
(understanding §6a). Shapes **B** and **C** — five of the remaining six — are additive or
self-scratch edits with no plausible integrity violation. Only `pylint-5859` t6 is a live TP
candidate, and it is contestable in both directions. So the likely landing is **TP=0, FP=7**:

```
precision = TP/(TP+FP) = 0/7 = 0.0
recall    = TP/(TP+FN) = 0/0 = n/a
TP (independent)         0
TP (independent, strict) 0
```

That is a **defined, publishable number**, not a degenerate one — and it is the most consequential
sentence this unit can produce: *the A1 default `tests/` read-only invariant has **zero measured
precision** on the only real mint data Belay has.* If it lands, it must be reported plainly, in
those terms.

**What an all-FP corpus does to `corpus run` — the consequence most likely to be missed.**
`belay corpus run` replays every case and asserts it still reaches its stored verdict, and the
stored verdict for all 7 is `FAIL`. The corpus **is** the regression suite
(`CAPABILITY_ROADMAP.md:420-422`). If all 7 are false positives, that suite is pinning behavior we
believe to be **wrong**: a green `corpus run` would then certify only that Belay still
mis-fires the same way, which is regression safety in the literal sense and evidence of
correctness in no sense at all.

This unit does **not** resolve that — deleting or re-storing the cases would destroy the very
evidence the audit produced, and changing the invariant mid-corpus is forbidden
(`CAPABILITY_ROADMAP.md:402-403`). What it must do is **say so**: `AUDIT.md` records that the
regression suite's cases are human-labeled false positives, so the next reader of a green
`corpus run` is not misled. Resolving it belongs to `invariant-test-mutation-shape`, which will
need these cases as its *negative* fixtures — they are more valuable labeled-wrong than deleted.

**If instead ≥1 TP survives** (t6 the only candidate), the tally is 1 TP against a required ≥3
independent, and the conclusion is unchanged: not a PROCEED, and the next unit is the sharper
invariant. **No adjudication of these 7 cases can produce a PROCEED**, because the denominator is
16. Stating that in advance is what stops the audit from being run until it produces one.

---

## Risks & Open Questions

| Risk | R-id | Mitigation |
|---|---|---|
| **The audit labels its way to ≥3 TPs.** Same person sets criteria, mints, adjudicates, wants a PROCEED. | R1 | Adjudicate from observed delta + upstream gold patch, both citable and re-checkable. t8 already went the costly way. AUDIT.md states the independence limit explicitly. |
| **The result is negative** — likely ≤1 TP survives, against ≥3 required. | R1 | This is a finding, not a failure. It is the documented likeliest outcome (benign-flag skew, `phase0-gate-readiness/prd.md:209`). Publish it. |
| **No false-positive guard.** Stage 3 captured zero of three controls. | R1 | Stated in AUDIT.md and `PHASE0_RESULTS.md`, not implied. A resumed mint drives controls **first**. |
| **Root-cause keys drift**, splitting one cause across two spellings and inflating independence. | — | 7 cases, one auditor, one sitting; keys listed together in AUDIT.md. Revisit a controlled vocabulary if the corpus grows. |
| **`target_tool` backfill misattributes a turn**, corrupting the strict count. | — | Backfill is a test-covered function over `target_turn_index`, not a hand edit; absent → `n/a`, never guessed. |
| A `corpus run` REGRESSION appears | — | Expected only on `A2 / effect:network` per `PHASE0_RESULTS.md:149`. Any other axis is real; investigate, don't relabel. |

### Open questions

1. **`pylint-5859` t6's adjudication is unresolved** and is the strongest remaining TP candidate.
   Upstream `a1df7685a` is **+10 −0 purely additive**, proving a purely additive change sufficed
   — yet the agent modified the pre-existing `test_other_present_codetag`, while *strengthening*
   it (1 → 3 assertions). Both sides are stated in understanding §6a; decided at Phase 6 with the
   evidence in hand.
2. **Do the remaining 5 need upstream comparison too?** Shapes B and C look benign on their face,
   but t8 showed a face-value reading can be wrong in the *favorable* direction. Cheap to check —
   the clones are local.
3. **Does `corpus score`'s output change break a test asserting exact text?** To be established by
   the first RED test in Phase 6.
4. **Should `tests/` read-only stop being ON by default if precision lands at 0.0?** It ships
   enabled (`--no-default-invariants` opts out) and `README.md`'s coverage claims rest on it.
   **Deliberately deferred until the labels exist** (decision, 2026-07-29): deciding it now would
   be reacting to the forecast in *Anticipated outcomes* rather than to a measurement, which is
   the substitution this project exists to refuse. Revisit as the first question after M8.

---

## Out of Scope

- **`invariant-test-mutation-shape`.** This unit *informs* it — the three shapes plus the two
  upstream comparisons are precisely the design input `STAGE2_FINDINGS.md:102-104` deferred it
  for — but does not build it. Changing the invariant mid-corpus makes banked instances
  incomparable (`CAPABILITY_ROADMAP.md:402-403`).
- **Resuming the mint to n≥50.** A separate, expensive unit; its go/no-go is what this audit
  informs. Controls first when it runs.
- **Clearing the gate.** Structurally impossible at n=16.
- **Re-verifying the 12 Stage-3 captures.** Already done: 10 CLEAN, 2 FLAGGED, no `INSTRUMENT
  SUSPECT`.
- **Any change to A1/A2/A3 semantics, `verdict.reduce`, or the `NOT_COVERED` boundary.**
- **C7 live console**, and any UI for the audit.
