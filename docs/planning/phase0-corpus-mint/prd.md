# PRD — `phase0-corpus-mint`

> **READ THIS FIRST. This is NOT a gate run and produces NO Phase-0 number.** The
> pre-registered PROCEED clause requires a denominator **≥50**, and that clause counts
> *instances minted*, so it is detector-independent (`PHASE0_RESULTS.md:781-784`). This
> unit does not reach it and does not try: the safely-eligible pool is **30** instances
> (**measured**, §1.2 — and see §1.2.1, which corrects an earlier overstatement that
> ≥50 was *impossible*). It produces **banked corpus cases**, not a violation rate.
> `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00` and `3/93` stand
> **unedited**.
>
> **Status: DRAFT — six scope decisions are PROVISIONAL** (§7). They were taken by the
> implementer on a "GTG" and are listed for confirmation at the review gate. Nothing
> irreversible happens before that gate.

Source: `docs/planning/_card/issue.md` (brief + measured substrate state),
`docs/planning/_card/understanding.md` (Phase-2 dig, four agents, all cited).

---

## 1. Problem Statement

### 1.1 The problem

**Three shipped capabilities are labelled "a capability, not a result", and the corpus —
moat #2 — holds zero true positives.**

| Capability | The record's own words | Source |
|---|---|---|
| A3 claim axis (C8) | *"no real intent-drift case exists yet — the fixture is synthetic, the mint's next run fills the A3 column"* | `CHECKLIST.md:407` |
| Trajectory banking | *"nothing backfilled (s6 captures gone) — the value is forward-looking: the next mint's trajectory FAILs bank"* | `CHECKLIST.md:408` |
| Recall / recorded miss | *"No miss has been banked, so recall remains unmeasured and precision still reads `n/a`"* | `CAPABILITY_ROADMAP.md` C6 |

`CLAUDE.md` states the standard this fails: *"every caught failure becomes a labeled case
that sharpens detection over time (this is moat #2, and **it must grow with each
feature**)."* Six capabilities have shipped since the last mint (2026-08-12) — the corpus
has not grown at all.

**Measured baseline** (`belay corpus score`, 2026-09-19):

```
TP 0 · FP 0 · FN 0 · TN 7 · precision n/a · recall n/a · coverage 1.00
independent findings: 0 distinct root-cause keys
```

Seven cases, all 2026-07 A1 false-positive negatives. No trajectory case, no claim case,
no true positive, no recorded miss.

### 1.2 Evidence the constraint is real (measured, not assumed)

> **CORRECTED 2026-09-19.** An earlier draft labelled the figure below *"FRESH (never
> driven) — 30"*. **That label was wrong.** 30 counts instances never drawn into any
> *registry*, which is not the same as never *driven* — an instance can be drawn and
> never run. Both measures are given; §1.2.1 says why the **conservative** one is
> nevertheless the one this unit uses.

Two measures, both **measured** this session:

| Measure | Fresh | Counts |
|---|---|---|
| **Conservative** — pool minus every committed registry's real ids | **30** (django 23, sympy 7) | never *drawn* |
| **Derived** — pool minus `observed.json` ∪ all 12 committed ledgers' real trace ids | **83** (django 53, sympy 30) | never *captured* |

```
pool reals ................. 166
union of registry reals .... 137   -> conservative fresh: 30
observed.json ............... 23
ledger-derived driven ....... 82   -> derived fresh: 83
```

**Both are ~100% django+sympy.** The small-repo block is exhausted — a construction
property stated by the gate generator itself: *"the committed pool has 28 small-repo
records and stage3's 80-real draw takes **every one of them** (the small-repo block is
exhausted before the large-repo top-up)"* (`eval/scripts/build_gate_registries.py`).

#### 1.2.1 Why this unit uses the conservative 30

The gap between 30 and 83 is **attrition** — drawn into `s6stage3.json`, never captured.
Some were *attempted and failed*; the rest were never reached. **A failed attempt is an
observation**, and the anti-re-roll contract is explicit: *"an instance that produced an
observation is never re-armable"* (`checkpoint.py:18-21`).

Telling the two apart requires the s6 **checkpoint** (which records `failed` vs
`no_observation`). **Measured: no s6 checkpoint survives** —
`~/dev/at/holder/belay/mint/` holds only `s1 s1b s1p s2 s3 live-smoke-claude-cli`. The
ledgers record only instances that produced a trace, so an attempted-and-failed instance
appears in no surviving record at all.

**So the 83 cannot be used without risking a silent contract violation on an
unidentifiable subset.** The conservative 30 is provably safe and, at n≈12, ample — the
uncertainty costs this unit nothing. A decision, not an oversight.

**Correction to a second claim:** an earlier draft said n≥50 is *impossible*. On the
derived measure it is not. The honest statement: **n≥50 is not reachable *safely*, and is
not attempted.** Q1's "publish no rate" never rested on the count — it rests on the
**monoculture**, which both measures share.

`eval/minting_driver/selection.py:3-24` records why the stratified draw exists: *~83% of
the eligible pool is django+sympy, so a uniform draw of 50 would publish a django/sympy
rate as an agent rate.* **The residue is ~100% django+sympy — worse than the concentration
the draw was built to correct.** This is the single fact that most shapes this PRD.

### 1.3 Who it is for

The maintainer, and any future reader of `PHASE0_RESULTS.md`. Directly: the next person
who asks *"does Belay's detection improve as the corpus grows?"* — the Phase-2 → Phase-3
gate question (`ROADMAP.md:320-322`), which today cannot be asked at all because the
corpus has no positives to improve against.

---

## 2. Goals & Success Metrics

### 2.1 Goals

1. **Bank real corpus cases** from a live mint under the current engine composition —
   per-turn, trajectory, and (if producible) A3 claim.
2. **Exercise, for the first time on real data**, the three capabilities that shipped
   unexercised.
3. **Record honestly what the run could not produce**, with named causes.

### 2.2 Success metrics

Split by evidence grade. The first group is deterministic and test-first; the second is a
live stochastic run and is **measured, never asserted**.

**Deterministic (testable, RED before GREEN):**

| # | Criterion |
|---|---|
| D1 | An A3 reference author exists, is offline-testable, and scrubs `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL` **by absence, never `""`** |
| D2 | The mint's `--verify` path can reach A3 (today it structurally cannot — §4.3) |
| D3 | A registry of the fresh instances builds reproducibly, seed recorded in `SEED_HISTORY` |
| D4 | The frozen invocation scripts contain **no result** (grep-checked, per `mint-run/spec.md:42`) |
| D5 | Full suite stays green (baseline **measured**: 2540 passed / 25 skipped / 12 deselected) |

**Measured (observed once, under the freeze protocol, reported whatever it says):**

| # | Criterion |
|---|---|
| M1 | Captures produced, with the capture rate and its denominator stated |
| M2 | Every trajectory FAIL **banks** as `trace-<instance>-trajectory` and recomputes MATCH under `corpus run` |
| M3 | Per-turn FAILs bank, or are reported as `flagged-but-unaddable` **with named causes** |
| M4 | The A3 column is **filled** — a verdict or a named UNVERIFIED cause, never "claim unrecorded" |
| M5 | `corpus run` over the grown corpus is 0 REGRESSION |

### 2.3 Explicit non-metrics

- **No violation rate.** (Provisional Q1 — §7.) Any rate from a ~100% django+sympy draw is
  precisely the artifact `selection.py` exists to prevent.
- **`precision` will still read `n/a`.** Banked cases are written `human_label="pending"`
  (`runner.py:459/541/592`) and `score()` excludes pending **first**
  (`metrics.py:219-221`). Only a human may label (`curate.py:46-146`), and rule **S-1**
  makes that the **owner's** work: *"The auditor is the owner; agents prepare evidence,
  never judgments"* (`phase0-remint/audit-and-publish/plan_20260809.md:24-29`).
  **The brief's line "precision and recall with real denominators" is NOT achievable by
  this unit** and is withdrawn here rather than quietly missed.
- **A3 may stay empty of FAILs.** See R-A below.

---

## 3. Requirements

### Must-have

| # | Requirement |
|---|---|
| MH-1 | The mint writes to an **absolute `--root` outside any worktree** (`~/dev/at/holder/belay/mint/<stage>`). `--root` is cwd-relative (`entrypoint.py:224-236`); a worktree-relative root embeds a path that dies with the worktree — **this defect has now bitten twice** (§4.1) |
| MH-2 | **Recorded paths are never rewritten.** Measured: rewriting breaks replay 0/11 → 7/11 |
| MH-3 | Freeze protocol (Rule D): tooling committed first **in a commit containing no result**; each stage run **once**; verbatim output committed next, whatever it says; a second run only if **declared** (`phase0-mint-run/prd.md:97-101`) |
| MH-4 | Rule A stage gating with controls **first**; D-3 — a FAILing control **VOIDS the run** regardless of later adjudication (`phase0-remint/prd.md:215`) |
| MH-5 | `INSTRUMENT SUSPECT` → **STOP**, never rendered as 0% (`report.py:6-12`) |
| MH-6 | The write-up's **first paragraph** states what this is not — *"three places, because two have not been enough before"* (`miss-measurement/spec.md:97-99`) |
| MH-7 | No published number is re-derived or edited |
| MH-8 | The A3 column is filled with a verdict or a **named cause** — never left "claim unrecorded" |

### Should-have

| # | Requirement |
|---|---|
| SH-1 | An A3 reference author shipped as a reusable artifact, not a throwaway script |
| SH-2 | The `--verify` / printed-CLI A3 asymmetry fixed or **documented by name** (§4.3) |
| SH-3 | The exposure line reported per instance (a zero-exposure clean verdict carries no information) |

### Nice-to-have

| # | Requirement |
|---|---|
| NH-1 | A banked **recorded miss**, if adjudication finds one — would measure recall for the first time. Depends entirely on owner adjudication; cannot be planned for |

---

## 4. Technical Considerations

### 4.1 Where the mint writes — the recurrence this unit must not repeat

**Found and repaired during the dig, before planning:** the three load-bearing eval
symlinks were **missing**, leaving **1,344** recorded path references dead and the entire
banked eval substrate unreplayable. Restored with the recorded recipe (which rewrites no
recorded byte), then **verified by running it**: `corpus run` → **7/7 MATCH**; `s1p` →
**`VERIFIED_CLEAN`, 0/11 UNVERIFIED**.

The cause is structural: manifests record an absolute `source_root`, and `--root` resolves
against cwd. **MH-1 removes the cause** rather than adding a fourth stub symlink.

### 4.2 The composition to reuse

The 2026-08-12 shell-toolset composition — the only one **measured** to produce TPs
(`mint-run/acceptance-stage3.sh:5-12`): `--provider claude-cli --model claude-opus-5
--max-steps 20 --request-timeout 120 --toolset filesystem+shell`, composite transport,
tool names merged **verbatim** so `run_process` stays `run_process` (`composite.py:171-192`).

Verify side: **`--shell-server` MUST precede `--server`** — `--server` is
`nargs=REMAINDER` and swallows everything after it (`eval/README.md:790-793`). **Measured:
I hit this defect myself** — `--server -- node …` fails with `unrecognized arguments`.

Environment delta to state, not hide: local `claude` is **2.1.277**; the gate run used
**2.1.228**.

### 4.3 The A3 seam — one real blocker, one corrected non-blocker

**Real blocker.** `eval/minting_driver/entrypoint.py:1029-1035` calls `run_batch(...)`
**without `claim_author=`**; the default is `None` (`runner.py:153`) and A3 engages only
when it is not None (`runner.py:419`). So the mint's in-process `--verify` path **can
never fill the A3 column**, whatever the env says. The printed CLI command *can*
(`cli.py:2593`). `eval/README.md:727-729` presents the two as equivalent — **they are
not.** Fix: run the CLI with `BELAY_CLAIM_AUTHOR` exported, or thread `author_from_env()`
into `run_verify` (respecting the lazy-import constraint at `entrypoint.py:1011-1018`).

**Corrected non-blocker.** The brief called the missing `phase0 run --claim-author` *"the
same defect class the parity guard exists to catch."* **It is not a defect.** It is a
recorded decision: surface set declared with its reason in-line
(`tests/test_cli_flag_parity.py:131-137`), open question at
`claim-re-derivation-a3/author/spec.md:53-55`, decided at `.../surfaces/plan_20260902.md:19-22`,
and **pinned by a test asserting the flag exits 2** (`tests/test_verify_claim_surfaces.py:202-219`).
Adding it would turn two guards RED and reverse a decision. **Do not add it.**

### 4.4 No A3 reference author exists

Nothing in `src/` authors an A3 check — only a `python3 -c` example (`README.md:155-161`),
a manual live gate, and a CI fake. Precedents to model on, both using the
**scrub-by-absence** idiom (`env.pop(name, None)`, never `""`):
`src/belay/authoring/reference_author.py:60-64, 177-190` and
`eval/minting_driver/clients/claude_cli_client.py:117-121, 709-723`. Note
`SubprocessAuthor` passes no `env=` (`author.py:107-113`) — scrubbing is the author's job.

### 4.5 Verdict impact — none, and that is a requirement

No axis, status, default, coverage line, trace field or reduction rule changes. A3 still
can never emit PASS (`tests/test_verify_claims.py:333-340`); the `--no-claim-axis`
refutation stays byte-identical. **Sharpening any rule so the mint produces more hits is
out of scope and would invalidate the run** — that is fitting the detector to the
measurement.

Capability: **C6** (failure corpus) exercised via **C8** (A3) and the A1 trajectory rule.

---

## 5. Risks & Open Questions

| id | Risk | Prob | Impact | Mitigation |
|---|---|---|---|---|
| **R-A** | **A real intent-drift case may not be producible.** The launch demo ran 18 drives across two frontier models and got **zero** corrupt successes (`DRIVES.md`) | **High** | High | Acceptance treats an empty A3 column as a **recorded result**, not a red test — the rule `invariant-authoring` applied to a model producing nothing calibratable. M4 requires a *named cause*, not a FAIL |
| **R-B** | **D-3 void** — a control FAILs and the whole run is void. Killed the 2026-08-09 re-mint exactly here | Med | High | Controls first; CTL-2/3 carry the anti-D-3 steering sentence (`controls.py:111-114`), which *lowers* the probability, never guarantees |
| **R-C** | **Zero exposure** — agents edit source, not tests. Killed `phase0-mint-run` (0/8 judged) | Med | Med | Exposure gate (D-1 trajectory reading) stops before the largest stage |
| **R-D** | **Banked cases stay `pending`** so nothing measurable improves | **High** | Med | Accepted and stated in §2.3. Owner labeling is a separate, later act |
| **R-E** | django/sympy monoculture makes cases unrepresentative | **High** | Med | Q1: publish no rate; state pool composition beside every count (honesty property 5) |
| **R-F** | Live spend on subscription | Med | Low | Rule A stop-loss; quota breaker writes `no_observation` and re-arms |
| **R1** (roadmap) | Corrupt-success premise | — | — | **Untouched.** This unit adds no evidence for or against R1 |
| **R6** (roadmap) | Failures don't cross MCP | — | — | `INSTRUMENT SUSPECT` is the false-zero defense; MH-5 |

### Open questions

- **OQ-1 — is this still the right unit?** *(the live challenge)* The dig materially
  shrank what it can deliver: no rate, no precision movement, and A3 may stay empty. The
  honest floor is *"banked `pending` cases + three capabilities exercised once on real
  data"*. That is real but thinner than the brief implied. The alternative highest-leverage
  use of the session is **fixing and merging PR #38, which is RED**. I am not recommending
  a switch — the ledger entries are real and only a mint closes them — but the owner should
  choose with this in view.
- **OQ-2** — mint size. 30 is the ceiling; provisional n≈12.
- **OQ-3** — if adjudication later finds a **miss**, banking it would measure recall for
  the first time. Out of scope here; worth a follow-up.
- **OQ-4** — should `eval/README.md`'s "`--verify` ≡ printed command" claim be corrected
  as part of this unit, or filed separately?

---

## 6. Out of Scope

- **Any published number moving.** `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
  `recall 0.00`, `3/93` stand unedited.
- **A violation rate from this run** (provisional Q1).
- **Owner adjudication / labeling** — S-1 makes it owner work (provisional Q3).
- **Adding `--claim-author` to `phase0 run`** — a pinned decision (§4.3).
- **Any rule, axis, status or threshold change.**
- **Backfilling the s6 captures** — gone; `mint/` holds only
  `s1 s1b s1p s2 s3 live-smoke-claude-cli`.
- **PR #38** (`feat/corpus-shell-routing`) — separate open branch, currently RED.
- **Re-driving already-banked instances** — `CaseExistsError`, fail-closed, no
  `--overwrite` (`corpus/add.py:364-368`).

---

## 7. Scope decisions — CONFIRMED 2026-09-19 ✅

Presented at the review gate with OQ-1 (*"is this still the right unit?"*) and the note
that **Q6 is live spend**. Owner approved the set. Recorded as the owner's decision, not
the implementer's.

| Q | Decision | If later reversed |
|---|---|---|
| Q1 | Publish **no** violation rate | §2.3, §5 R-E and the aspect split all change |
| Q2 | n ≈ **12**, staged per Rule A | Registry aspect resizes |
| Q3 | Owner labeling **out of scope** | Adds an owner-blocking aspect; precision could move |
| Q4 | **Write** an A3 reference author | Drop the `a3-author` aspect; A3 stays dark |
| Q5 | `--root` **absolute** under the holder | MH-1 changes; recurrence risk returns |
| Q6 | Live `claude-opus-5` spend **authorized** | The unit cannot run at all |
| OQ-1 | **Proceed** with this unit (not a pivot to PR #38) | — |

**Sequencing consequence of Rule D (MH-3), binding on the implementer.** The live run is
*unrepeatable* and must be preceded by a commit containing **no result**. Therefore
aspects 1–2 are built and green, and the frozen scripts committed, **before any spend**.
The transition into aspect 3 is the point where authorization is exercised — the frozen
script will exist and be reviewable at that moment.

---

## 8. Proposed aspect decomposition

Sequenced; each buildable by one agent. **The live run is one aspect and is gated behind
the deterministic ones** — nothing spends until the instrument is proven.

| # | Aspect | Boundary | Grade |
|---|---|---|---|
| 1 | `a3-author` | An A3 reference author + the `run_verify` threading, so A3 is reachable at all. Offline tests, scrub-by-absence | deterministic |
| 2 | `mint-registry` | The fresh-instance registry from the 30, reproducible, seed in `SEED_HISTORY`, controls included | deterministic |
| 3 | `mint-run` | Frozen scripts (no result), staged live drive under Rule A + D-3, verbatim outputs | **measured** |
| 4 | `corpus-banking` | Verify → bank → `corpus run` recompute; unaddable causes named | **measured** |
| 5 | `audit-and-publish` | Evidence pack for owner adjudication (S-1: evidence, never judgments), `PHASE0_RESULTS.md` entry opening with the not-a-gate-run paragraph, STATUS/CLAUDE blocks | docs |

Aspects 1–2 can run in parallel. Aspect 3 must not start until 1, 2 and D4 are green.

---

## 9. Self-critique

- 🟢 **Moat alignment** — squarely moat #2; no framework drift, no LLM judge (execution
  decides by exit code), no egress.
- 🟢 **Honesty** — the unit withdraws one of its own brief's acceptance lines (§2.3) and
  corrects one of its own factual claims (§4.3) rather than carrying them forward.
- 🔴 **The value is thinner than the brief implied.** OQ-1 is unresolved and is the one
  thing the owner should rule on before any spend.
- 🔴 **R-A is high-probability and the unit's headline depends on it.** The launch demo is
  direct evidence that this shape resists production on demand. Mitigated by framing, not
  by capability — which is honest, but means M4 may land as a named abstention.
- 🟡 **Stochastic acceptance.** Aspects 3–4 cannot be TDD'd in the normal sense; they are
  measured once under the freeze protocol. The deterministic aspects carry the test-first
  weight, exactly as prior mint units were structured.
- 🟡 **`--verify` vs printed-CLI asymmetry** (§4.3) is a real documentation defect this
  unit merely discovered; OQ-4 asks whether fixing it belongs here.
