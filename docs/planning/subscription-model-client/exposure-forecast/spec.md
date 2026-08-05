# Aspect — `exposure-forecast`

**Unit:** `subscription-model-client` · **Order: parallel with `claude-cli-model`** (touches no
client code). **Gates:** the decision to fund the ~11 h mint.
**Origin:** not in the 2026-07-28 spec. Added 2026-08-05 from the `under-firing-measurable` result
and the PRD challenge phase. **Re-specified the same day** after self-critique — see the box below.

> **🔴 The first version of this spec was wrong, and the correction is the point of the aspect.**
> It proposed counting `.py` files under a `tests`/`testing` path segment at `base_commit`. Every
> one of the seven repos in the population has exactly that (django `tests/`, sympy
> `sympy/**/tests/`, sphinx `tests/`, requests `tests/`, pytest `testing/`, flask `tests/`, pylint
> `tests/`), so the survey would have returned ≈166/166, its *"absent or tiny → stop"* branch could
> **never fire**, and it would have cost seven clones and a tree walk to record a number that was
> predictable without running anything. **A decision rule whose stop-branch cannot fire is not a
> decision rule.** The basis below was checked for variance *before* being specified.

---

## Problem slice

`under-firing-measurable` (v0.12.0) measured that **9 of 15 instances gave A1 zero in-scope files
to judge**, and that the 17 recorded judgments came from **7 distinct files across 2 instances**.

Nothing in the record distinguishes two very different explanations:

- **(a)** those 15 draws happened to be low-exposure, or
- **(b)** low exposure is a **property of SWE-bench-lite** as a population.

If **(b)**, a mint at n≥50 spends ~11 hours and returns **another uninterpretable near-zero** — the
exact ambiguity v0.12.0 existed to remove, reproduced at roughly 3× the cost. Today that funding
decision would be made with no evidence either way.

## User outcome

Before the spend, the owner reads a number with a denominator and a per-repo shape, plus a
pre-registered rule (`prd.md` §2.1 Rule B) saying what to do with it.

## The basis, and why this one

**Signal:** does an instance's own `problem_statement` / `task_string` describe tests, a traceback,
a reproduction, or an assertion? Those fields are **already committed** in `eval/instances/pool.json`
for all 166 instances (median length 787 chars, min 239, max 1970).

**Three reasons it is the right basis:**

1. **It varies.** Measured 2026-08-05 over all 166 with a token probe
   (`test|tests|testing|pytest|assert|assertion|failing|traceback|reproduc`): **59/166 = 36%**,
   spread **0/4 (requests)** and **0/1 (flask)** to **3/3 (pylint)** and **6/7 (pytest)**, with
   django 22/82 and sympy 20/56. A rule can actually discriminate on this.
2. **It partly tracks what was measured.** pylint and pytest score highest and are among the repos
   v0.12.0 observed real exposure on. That is a **calibration point, not a validation** — n is far
   too small to call it predictive.
3. **Zero contamination risk.** The problem statement **is the agent's prompt**. Reading it here
   exposes nothing the mint does not already hand the agent, unlike the gold patch
   (`prd.md` D-4), which would be an answer key sitting next to the eval.

**Its known false negative, named in advance.** flask scores **0/1** on this signal, yet
`flask-4992` wrote to a test file **four times** in the banked captures — because *adding* a test is
normal, correct behaviour that a problem statement never has to mention. So the signal
**under-counts** exposure by construction, and a low score is therefore weaker evidence for "stop"
than a high score is for "go". The published output must say this in its own text.

## In scope

- A **deterministic, offline** survey over the **166** strict-eligible registry instances
  (`pool.json`), reporting the **launched 68** (`selected.json`) **separately** — the draw
  deliberately rebalanced the composition (pool is django 82 / sympy 56; the launched 68 is django
  19 / sympy 18), so summing or averaging the two populations is a category error.
- The **text signal** above, per instance, with the exact token set committed in the script.
- A **cheap sanity floor**: confirm an in-scope surface exists at all per repo. Expected to be
  7/7 — recorded as a floor, **never presented as a finding**.
- Reporting, with denominators, **per repo** (the pool is 83% django+sympy; an aggregate alone
  hides the shape), plus the 3 controls partitioned out of the headline.
- Cross-reference against v0.12.0's **measured** per-repo exposure, stated as calibration.
- A **committed artifact** (script + verbatim output) under the freeze protocol: tooling commit
  contains no result; output committed verbatim afterwards.

## Out of scope

- **Downloading SWE-bench-lite gold patches** (`prd.md` D-4) — strongest predictor, mint-voiding
  contamination hazard, and a network dependency the repo does not have. **Do not.**
- **Predicting agent behaviour.** This measures a property of the *task text*, never conduct.
- **Tuning the token set until it matches v0.12.0.** Fitting a 166-instance predictor to 15
  measured points is overfitting dressed as calibration; the token set is committed **before** the
  cross-reference is computed.
- Re-scoping the registry, changing the draw, or re-selecting instances. A thin forecast is a
  **finding for the owner**, not a licence to re-roll — the anti-re-roll contract is already in
  code.
- Any model call, any network, any API key. Any change to `src/belay/` or the A1 rule.

## Acceptance criteria

1. **Deterministic and offline** — no network, no API key, no model. Same inputs → byte-identical
   output.
2. **Every reported figure carries its denominator.** A bare count is a defect.
3. **The 166 and the launched 68 are reported separately** and never summed or averaged.
4. **Controls are partitioned out of the headline**, following the `phase0 combine` precedent.
5. **Per-repo breakdown is present.**
6. **The token set is committed in the script**, is stated in the output, and is **not** revised
   after the cross-reference is computed (criterion 10 is what makes this checkable).
7. **An instance with a missing or empty `problem_statement` reads `unknown`, never zero.** Absent
   is not zero — the same rule the ledger enforces for exposure. `unknown` is counted and named.
8. **The output states in its own text** that it forecasts a property of the **task description**,
   not agent behaviour; that it **under-counts by construction** (the flask false negative, named
   with its instance id); and that it is **not comparable** to v0.12.0's 17 judgments — different
   thing counted, different population, different model.
9. **The freeze protocol holds** — tooling commit contains no result.
10. **The cross-reference against v0.12.0 is computed and reported once, after the token set is
    frozen**, and is labelled **calibration, never validation** (n=15 across ~~5~~ **6** repos —
    *corrected 2026-08-05: this spec and `plan_20260805.md` §1 both said 5; the 15 instances named
    in `PHASE0_RESULTS.md` span **6** — flask 2, pylint 3, pytest 4, requests 4, sphinx 1, sympy 1.
    The script derives the count from the transcribed table and prints it, and says in its own
    output that it does; nothing was reconciled by adjusting a figure*).
11. **No published number is re-derived or edited.** `1/15`, the 17 judgments, `precision 0.00`,
    `recall 0.00`, `4/16`, `3/93` all stand untouched; this aspect only *adds* a figure.

## Dependencies & sequencing

- **Depends on:** `eval/instances/pool.json` + `selected.json` (**committed, present**). Nothing
  from `claude-cli-model`. **No clones, no workspace prep** — which is the second saving from the
  re-spec.
- **Blocks:** the **decision** to fund the mint. It does **not** block `claude-cli-model` or
  `live-smoke-confirmation` — the client is worth having regardless of the forecast.

## Risks & open questions

- **A proxy is a proxy.** Criterion 8 is the guard and is the most important line here. The
  strongest honest claim is *"N of 166 task descriptions mention tests"* — never *"N instances will
  produce exposure"*.
- **Asymmetric evidential weight.** Because the signal under-counts (flask), a **high** score is
  reasonable evidence the population can produce exposure; a **low** score is weaker evidence it
  cannot. Rule B's stop-branch should be read with that asymmetry, and the output must say so.
- **Overfitting temptation.** Everything about this aspect invites tuning tokens until the answer
  looks right. Criteria 6 and 10 exist to make that visible if it happens.
- **Open:** should `task_string` be scanned as well as `problem_statement`, or is the statement
  alone the honest input? The agent receives both. **Recommendation: scan both, report both
  separately**, so the reader can see whether the signal is coming from the task framing or the
  bug report. **CLOSED 2026-08-05 by measurement:** both were scanned and reported separately, and
  the statement is the field that carries the signal — `task_string` scores **57/166** against the
  statement's **59/166**, i.e. **2 statement-only, 0 task-only**. The framing introduces none of
  its own signal (`TASK_PREFIX` contains no token, derived rather than assumed), and the two the
  task loses are consistent with `derive_task_string`'s 1500-char truncation: on those two, the
  signal sits past the cut and **the agent is never shown it**.

---

## The reading — 2026-08-05, under PRD §2.1 Rule B

**The measurement.** Script frozen at `f82d12f` containing no result; invocation and verbatim
output at `83028e2` (`acceptance.sh` / `acceptance.out`). Run once, offline, byte-identical on
re-run. It **reproduces `plan_20260805.md` §0 exactly** — 59/166, django 22/82, sympy 20/56,
sphinx 8/13, pytest 6/7, pylint 3/3, requests 0/4, flask 0/1, statement length min 239 / median
787 / max 1970 — which is the check that the instrument is sound, and nothing was adjusted on
either side to obtain it.

| population | statements mentioning ≥1 frozen token |
|---|---|
| **pool** (`pool.json`) | **59/166 = 35.5%** |
| **launched, real only** (`selected.json`) | **29/65 = 44.6%** |
| controls, partitioned out | 0/3 |
| `unknown` (absent/empty statement) | 0/166 and 0/65 — stated, not omitted |

**The decision-relevant figure is the launched 44.6%**, not the pool's 35.5%: the mint drives
`selected.json`, and the ≥50 denominator would be filled from those 65. The two are **not**
averaged and neither is derived from the other — the draw rebalanced composition (django 82/166 =
49.4% of the pool vs 19/65 = 29.2% of the launch), which is precisely why the launched figure is
the higher one.

**Rule B row 1 fires: FUND THE MINT.** Nearly half of the instances a mint would actually drive
describe tests, an assertion, a failing case, a traceback or a reproduction in their own text.
That is not *"very few"* under any reading, so the stop-branch does not fire — and note this is a
**decision rule with a live stop-branch**, unlike the design in the 🔴 box above.

**The asymmetry, honoured rather than quoted.** Rule B pre-registers that a **high** score is
reasonable evidence the population *can* produce exposure while a **low** score is *weaker*
evidence it cannot. The reading here lands on the **stronger** side of that asymmetry, and the
measurement supplies its own proof of the direction: **flask forecasts 0/1 and v0.12.0 measured
2/2 instances judged with 5 judgments.** So **44.6% is a floor on the share of launched tasks that
describe test work, not an estimate of it** — the true share can only be higher, never lower.

**Rule B row 3 also fires, partially, and is reported rather than resolved.** sphinx forecasts
8/13 = 61.5% and sympy 20/56 = 35.7%, yet both were measured at **0 judged**. By row 3 that gap is
*agent behaviour, not task supply*, and **does not by itself block the mint** — but the measured n
on those two repos is **1 instance each**, so the gap is a real observation and a worthless rate.
Where the measured set is thickest the two agree in direction: pytest 6/7 forecast against 3/4
instances judged, pylint 3/3 against 1/3.

**What this reading is NOT.** It is **not a gate run** — the PROCEED clause counts *instances
minted*, is detector-independent, and no offline survey can satisfy it. It is **not a prediction**
that 29 instances will produce exposure; it counts task text, never conduct. It is **not
comparable** to v0.12.0's 17 judgments (different thing counted, different population, different
model — no model at all here). And it **re-derives nothing**: `1/15`, the 17 judgments, `precision
0.00`, `recall 0.00`, `4/16`, `3/93` and the `0% UNVERIFIED` headline all stand exactly as
published; this aspect only *adds* a figure.

**The residual risk the forecast cannot touch.** 36/65 launched statements mention nothing, and
this instrument cannot say whether those tasks would invite a test edit anyway — the flask
counter-example proves that at least some do. The forecast raises the floor under the funding
decision; it does not narrow the ceiling.
