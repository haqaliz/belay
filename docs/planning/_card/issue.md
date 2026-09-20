# Card — `feat/effect-conformance-coverage/aliz`

**Source:** no GitHub issue. Belay's tracker has exactly one open issue (#29, *A2A Handshake
Discovery & Capabilities Offer*), unrelated. This unit was picked by `belay-next` on
2026-09-20 from the repo's own open decision, so the brief below is the source of truth.

**Type:** feat · **Slug (provisional):** `effect-conformance-coverage` · **Owner:** aliz
**Base:** `origin/master` @ `472ce3b` (v0.34.0)

---

## Brief

Fix the instrument that stopped the 2026-09-19 corpus-filling mint at its own pre-registered
gate.

Against MCP servers that **declare no annotations**, A2 effect-conformance abstains by its own
rule — *not-declared → UNVERIFIED, no contract to check against* (`src/belay/verify/effect.py`,
the rule table in the module docstring). Worst-status-wins then drags the whole turn to
UNVERIFIED **even where result-equivalence passed**. The consequence, measured and recorded:

> "against annotation-less servers a corpus-filling mint can never bank a per-turn case"
> — `docs/STATUS.md:61-66`

The pinned reference server the mint actually drives — npm
`@modelcontextprotocol/server-filesystem` — declares none. The contrast is recorded too:
`demo/server.py` *does* declare annotations, which is the only reason demo turns reach PASS.

### CORRECTION (2026-09-20, established from code during Phase 2 — supersedes the quote above)

**`docs/STATUS.md:65-66` overstates its own finding, and this unit must not inherit the
overstatement.** *"Can never bank a per-turn case"* is not what the code does.

`reduce` ranks `FAIL (3) > UNVERIFIED (2)` and takes the max (`src/belay/verify/verdict.py:67-73`,
`:114-117`). So a turn whose effect dimension abstains but whose A1 or result-equivalence
**decides a FAIL** still reduces to FAIL, enters `flagged_turns` (`phase0/runner.py:378`) and
banks normally. `add_case` enforces **no status precondition at all** — *"It enforces NO
precondition on the turn's verdict"* (`corpus/add.py:4-8`); bankability gates on a restorable
pre-state and id-collision only (`add.py:333-368`).

**What the abstention actually blocks is `VERIFIED_CLEAN`, and therefore the denominator.**
`replayed_any` is set only for a decided, non-UNVERIFIED **reduced** status
(`phase0/runner.py:353-376`); `violation_denominator()` counts only
`VERIFIED_CLEAN | VERIFIED_FLAGGED` (`phase0/ledger.py:216-218`, `:41`); a zero denominator with
≥1 instance trips `instrument_suspect` **trigger A** (`phase0/report.py:65-89`). The
2026-09-19 mint tripped exactly that. It banked nothing for a plainer reason than the
abstention: **its two controls were honest negatives with no FAIL to bank**, plus one turn with
no manifest at all (`STAGE1_FINDINGS.md:76-80`).

**So the harm to state precisely:** an honest clean run cannot be distinguished from a broken
instrument, so **no rate can ever be printed**, and every real user of the reference filesystem
server sees 100% UNVERIFIED. That is a product defect (R7, *"the product says 'shrug'"*), not
merely a mint defect — which is why the fix belongs in the verdict, not in the mint's gate.

**Deliverable implied:** a correction to `docs/STATUS.md` quoting what it replaces, per this
repo's house style for corrections.

**This is the open owner decision, option (1), with the recorded recommendation:**

> "Fix the instrument first. The annotation-abstention interaction is the deeper issue …
> That is a real coverage-loss path and arguably the more valuable unit than the mint itself."
> — `docs/planning/phase0-corpus-mint/mint-run/STAGE1_FINDINGS.md` → *Decision required
> (owner — S-1)*, and `docs/STATUS.md:71-73`

## What the mint measured (the evidence, not a hypothesis)

- Stage 1 minted 2 captured / 0 failed, verified to `NO_VERIFIABLE_TURNS: 2`,
  `INSTRUMENT SUSPECT`, **UNVERIFIED 3/3 = 100%** → pre-registered STOP; stage 2 never launched.
- The capture contains **no `readOnlyHint` / `annotations` anywhere**.
- Causes are **pre-existing, not a regression** — the 2026-08-12 run that PROCEEDed carries
  `replayed but effect unverified` 8 and `UNRESTORABLE_SNAPSHOT_FAILED` 16/122. What differs is
  **scale**: s6c absorbed them across hundreds of turns; a 3-turn probe cannot.

## The design question this unit must settle FIRST (in the PRD, before any code)

### Three live behaviours in one annotation family, not two (established from the tree)

| | dimension · state | behaviour today | where |
|---|---|---|---|
| **(a)** | `openWorldHint` **not-declared** | **no sub-verdict at all** (returns `None`, composed conditionally) | `effect.py:382-385`, `turn.py:462-464` |
| **(b)** | `openWorldHint` declared-false / non-boolean | `NOT_COVERED`, dropped by `reduce` | `effect.py:382-385`, `verdict.py:114-117` |
| **(c)** | `readOnlyHint` **not-declared** | `UNVERIFIED`, folded **unconditionally** → always drags | `effect.py:556-567`, `turn.py:445` |

`turn.py:445` is `sub_verdicts = [result_verdict, effect_verdict]` — no `is not None` guard,
unlike the network path. That asymmetry is the whole mechanism.

### Two findings that cut AGAINST simply extending NOT_COVERED

**1. The precedent unit already considered and rejected folding a not-declared boundary into a
turn.** `render_openworld_verdict` returns `NOT_COVERED` for not-declared on the *standalone*
surface, but `network_subverdict` deliberately stays silent for it — *"so a turn's sub-verdict
list is not padded with a boundary nobody asked about"* (`effect.py:337-347`). That is a
recorded decision against design (b) for the not-declared case specifically.

**2. The perverse-incentive warrant RUNS BACKWARDS here.** The network change was justified
because honesty was punished: *"a server that **honestly declares** a closed posture gets a
strictly **worse** verdict than one that stays silent"*
(`verdict-coverage-status/prd.md:26-28`). For `readOnlyHint` the incentive currently points the
**right** way — declare `readOnlyHint: true` and honour it → PASS; declare nothing →
UNVERIFIED. **Making not-declared stop dragging would remove a working incentive for servers
to declare annotations**, which is the free A1 supplement the wedge leans on (`CLAUDE.md`:
annotations are *"a free supplement"*; R3's zero-friction mitigation). This cost does not exist
in the precedent case and must be priced explicitly.

### The original framing (kept — still the tension, now better grounded)

There is a shipped precedent and a documented counter-argument, and they disagree.

**For reclassifying *not-declared* → `NOT_COVERED`:** `verdict-coverage-status` already did
exactly this for the `openWorldHint` network dimension (`effect.py` `_openworld_verdict`), for
the identical reason — UNVERIFIED-forever made an honestly-declared posture strictly *worse*
than silence (declare nothing → PASS; declare truthfully → UNVERIFIED forever). `reduce` drops
`NOT_COVERED` before ranking, so it can never be a turn's reduced status, never lowers a turn
and never lifts one.

**Against:** `effect.py`'s own module docstring argues the opposite in its own voice —
*"an absent contract is NOT a permissive one. A tool that declared no `readOnlyHint` cannot be
verified for conformance — UNVERIFIED, never PASS. Defaulting an un-annotated tool to 'it never
claimed read-only, so a mutation is fine → PASS' is the exact false pass the tri-state (C1) was
built to prevent."* Because `reduce` drops `NOT_COVERED`, the reclassification **would** let
such turns reach PASS on result-equivalence alone.

**And the precedent is not perfectly analogous.** Per `CLAUDE.md`: UNVERIFIED = *"we tried to
check this and could not"*; NOT_COVERED = *"this was never inside what Belay claims to check"*.
For `openWorldHint` Belay has **no instrument at all** (no filesystem delta can confirm or
refute a network promise). For a not-declared `readOnlyHint` Belay **has** the instrument — it
observes the delta — and is missing only the *contract*. That asymmetry is the crux.

**Narrower alternative to weigh in the PRD:** leave the verdict semantics untouched and change
what the mint/corpus will **bank** — i.e. a turn with a *decided* result-equivalence becomes
bankable even while the effect dimension abstains. Moves the fix out of the verdict and into
the corpus/phase0 gate.

## Constraints this unit inherits (non-negotiable)

- **It is a RECLASSIFICATION, not improved detection.** Any UNVERIFIED-rate change crosses a
  population boundary; the two rates are **not comparable** and every write-up must say so.
  (The same rule `verdict-coverage-status` and R7 already established.)
- **No published number moves:** `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
  `recall 0.00`, `3/93` stand unedited. Nothing is recomputed.
- **`UNVERIFIED` is never rendered as `PASS`**, and if a PASS can newly arise where the effect
  dimension is uncovered, **the coverage line must travel with the status on every surface** —
  per-turn `belay verify`, `--json`, `belay corpus show`, `interop correlate`/`export`, the
  console. That rule is enforced per-surface by tests, not by review.
- **A declared-true-and-mutated turn must remain a FAIL.** A2 keeps its teeth; no widening of
  the abstention is acceptable.
- **A default is never a declaration** — absent must stay distinguishable from declared-false,
  or a default manufactures a false PASS (the C1 tri-state contract).

## Surface audit (established Phase 2) — the constraint on EVERY option

Today a `NOT_COVERED` dimension is **rare** (only where a tool declared `openWorldHint`). Any
change that makes one routine — i.e. every turn against the reference server — converts these
latent gaps into the live false-PASS-by-omission path the per-surface rule exists to prevent.

**Four surfaces would render a clean/PASS status with NO coverage disclosure whatsoever**, and
**none of them has any test pinning coverage**:

| Surface | file:line | Discloses? |
|---|---|---|
| `belay corpus list` | `cli.py:2303` | **No** — bare status column |
| `belay corpus run` aggregate | `cli.py:2065-2072` | **No** — a MATCH discloses nothing; only a divergence surfaces the kind |
| `belay corpus score` | `cli.py:2194-2197` | **No** — and its own `coverage` metric means *adjudicable labels*, a name collision |
| `belay phase0 combine` | `phase0/report.py:786` | **No** — `_coverage_section` never called on this path |

Two further weaknesses: `phase0 report`'s prose table `_COVERAGE_PROSE` has exactly **one**
entry (`effect:network`), so a new cause reads anonymously as *"outside what Belay observes"*
(`phase0/report.py:145`, `:198`); and `interop export` writes `belay.verdict.coverage` only
`if uncovered_kinds:`, kinds without the message (`export.py:109`).

**The coverage sentence is duplicated across 8 render sites** — only the *data* helper
`verify/json.coverage_record` is shared (`json.py:196`, reused solely by `gate/check.py:64,331`).
The 8: `cli.py:1478-1487`, `cli.py:1567-1572`, `cli.py:751`+`:798`, `interop/report.py:108-111`,
`phase0/report.py:169-176`, `gate/check.py:422-432`, `interop/export.py:109`,
`console/src/components/CoverageLine.vue`. A new cause must be added to each.

**Clean, and a model to copy:** the console (`TurnRow.vue`, `TraceView.vue`, `ReplayDialog.vue`,
the server seam) is fully pinned and renders `null` as *"coverage unavailable"*, never a
fabricated status.

## Risks this touches (`docs/ROADMAP.md` register)

- **R7** — *"Nondeterministic tools make UNVERIFIED the default verdict — the product says
  'shrug'"*; mitigation: *"if it dominates, that's a gate signal."* It dominated at 3/3 = 100%.
  This unit is the response to that signal.
- **R3** — *"infer from MCP annotations first (free, zero-friction)"* is measurably hollow when
  the reference server declares nothing. Worth recording; not this unit's job to fix.
- **R5** — over-claiming what A2 proves. The whole risk of getting this wrong.

## Out of scope (name it, don't drift into it)

- Re-running the mint or producing any Phase-0 number.
- `UNRESTORABLE_SNAPSHOT_FAILED` (cause #3 in the findings) — a separate defect.
- The A3 `--json` coverage-legibility gap (absent `claim` key is ambiguous) — recorded
  separately, adjacent but distinct.
- Committed junk at the repo root (`err.txt`, `err2.txt`, from `9d7ead2`) — incidental.

## Related in-flight work

**PR #38 is OPEN and RED** (`feat/corpus-shell-routing/aliz`), 2 failed / 2256 passed:
`AttributeError: 'types.SimpleNamespace' object has no attribute 'shell_server'` at
`src/belay/cli.py:2383` (2 tests), and `test_docker_inimage` failing its own unknown-skip⇒FAIL
rule on `replay-reinvokes-seatbelt`. It touches the corpus recompute path this unit also
touches — check for collision before landing.
