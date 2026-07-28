# Understanding — `phase0-mint-resilience`

**Unit:** `feat/phase0-mint-resilience/aliz` · **Owner:** aliz · **Date:** 2026-07-28
**Base:** `origin/master` @ `91913a0` (v0.7.0)
**Inputs:** `docs/planning/_card/issue.md`, plus three read-only digs (driver call-path map,
mint failure forensics, doc-constraint extraction).

> **Note on a stale sibling.** `docs/planning/_card/understanding.md` is the *predecessor*
> unit's dig (titled `# Understanding — phase0-stage3-publish`). Its §5 (clone cache) and
> §7.1 (cost / abort threshold) remain accurate and load-bearing; its task-order sections
> describe work now merged. This file supersedes it for the current unit.

---

## 1. The headline correction: it was never a rate limit

The card was written against the summary "Stage 3 died on 429s, so add retry-with-backoff."
The forensics refute the mechanism, and the fix must change shape accordingly.

The verbatim error (all 56 failures, one signature):

```
Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_model_per_day,
limit: 250, model: gemini-3.1-pro
Please retry in 10h50m43.651927829s.
... 'status': 'RESOURCE_EXHAUSTED', 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel',
    'retryDelay': '39043s'
```

- It is a **per-day request cap** (250/day), not a per-minute rate limit.
- `retryDelay` across the 56 errors ranges **39037s–39250s** (≈10h50m).
- **Bounded exponential backoff in seconds or minutes cannot help.** Only an ~11-hour wait
  or a higher tier clears it.
- Both SDKs (`openai`, `anthropic`) **already retry internally** — `max_retries=2` honoring
  `retry-after`, and neither client overrides it (`local_client.py:76`,
  `anthropic_client.py:75`). So these 56 failures are *already* post-retry. Any retry added
  in `eval/` stacks on an invisible existing layer.

**What was actually lost is the queue, not the run.** After the first 429 at `16:35:31`,
the driver burned all **56 remaining instances in 3m48s at ~3s each**, one wasted request
apiece, each recorded `failed` — and `checkpoint.is_done` treats `failed` as done
(`checkpoint.py:82-88`), so they are permanently skipped on resume.

> **The correct primitive is a circuit breaker, not a retry loop:** on a quota-class error,
> **stop the batch** and leave the remaining instances *unrecorded* (still eligible), rather
> than feeding the whole queue into a wall. A bounded retry is still worth having for
> genuinely transient errors, but it is the secondary mechanism, not the primary one.

Independent corroboration of the ordering: the server-side `retryDelay` decreases
monotonically (39250 → 39037) in exactly the filesystem-mtime order — two independent
clocks agreeing.

---

## 2. What is actually banked

Nothing is corrupt. All 12 s3 captures are real: manifest count **equals** `tools/call`
count for every one, 216 turns total, `network_policy: deny-all` frames present, real tool
mix (`search_files`, `read_text_file`, `edit_file`, `write_file`), and 8 of 12 hit the
`--max-steps 20` ceiling still working.

| Quantity | count |
|---|---|
| Union of captured ids, all stages | 17 |
| … controls | 2 (`flask-read-only`, `flask-write-new-file`) |
| … unique non-control | 15 |
| **Distinct `selected.json` instances captured** | **16 / 68** |
| `selected.json` instances still uncaptured | **52** |

`ledger.violation_denominator()` = `VERIFIED_CLEAN + VERIFIED_FLAGGED` and does **not**
exclude controls, so the engine's own achievable denominator today is **16**.

**Gap to the pre-registered ≥50 is 34 more distinct instances**, from 52 remaining. At
250 req/day ÷ ~20 req/instance ≈ **12 instances/day**, that is **3–5 more days** on the
current free tier, or one session on a paid tier.

### The composition news is good

What died was the *concentrated* half. Captured: pallets 1/1, requests 4/4, pylint 3/3,
pytest 4/7, sphinx 1/13, sympy 1/18, **django 0/19**. The batch ran in registry order,
which front-loads the diverse stratum — so **the expensive-to-justify anti-concentration
instances are already banked**, and what remains is the bulk django+sympy top-up the draw
was designed to include. Worth saying in the write-up: the published composition shifts
toward the concentrated stratum as the denominator fills, which is the draw working as
designed, not drift.

The bad news is that the remainder is also **the expensive portion** — `STAGE2_FINDINGS.md:54-58`
records sympy `search_files` replies up to 455 KB and 1.26 MB accumulated in one session,
~15 min for 20 turns. Quota exhaustion will recur unless the key changes.

---

## 3. The binding constraint is the audit, not the quota

This is the most important finding in the dig, and it reorders the whole unit.

- **All 6 corpus cases are `human_label: "pending"` → 0 hand-audited TPs.** The gate needs
  **≥3 independent**. FP rate prints `n/a` until labels exist.
- **All 6 share one root cause**: `A2/replay PASS`, `A2/effect PASS`,
  `A2/effect:network NOT_COVERED`, **`A1/invariant FAIL`** on the default `tests/`
  read-only invariant. Under the pre-registered independence rule — *"Three flags from one
  mis-annotated tool count as one finding"* — these collapse toward **1–2 findings, not 3**.
- `phase0-gate-readiness/prd.md:137-140` already concedes this: *"Record the standing TP
  tally conservatively: 2 independent findings, not 3 … Stage 3 therefore needs ≥1 further
  independent finding."*
- And `prd.md:209` names it the likeliest failure: **benign-flag skew** — *"a 15–20h run
  could land <3 independent TPs and force a PIVOT on a premise never actually tested."*

**Minting 34 more instances does not fix this.** More instances under the same blunt
invariant most likely yield more `tests/`-write flags of the same root cause. The gate can
fail on independence even at a denominator of 68.

---

## 4. Free, unblocked work available right now (zero quota)

1. **7 of the 12 s3 captures have never been verified.** `runs/s3-partial.json` covers only
   the 5 day-1 instances (4 CLEAN, 1 FLAGGED, 90 PASS / 3 FAIL / 0 UNVERIFIED). The 7
   captured on 2026-07-24 have no ledger. Re-running `belay phase0 run` over the full s3
   batch is offline and costs nothing.
2. **Pre-registration** into `PHASE0_RESULTS.md` — required to precede further spend by a
   `git log`-verifiable commit, and cheapest item on the list.
3. **The doc corrections** (#18/#19). `audit-and-publish/spec.md:87-88` explicitly says
   these *"are **not** blocked by the mint and can land early — doing so de-risks the tail."*
4. **Hand-audit the 6 existing corpus cases.** Labeling is human work, not quota work.

---

## 5. Process debts already incurred (not hypothetical)

- **Pre-registration never happened, and Stage 3 already ran.** `git log -- docs/technical/PHASE0_RESULTS.md`
  shows only `ee12495` (template) and `05369c1` (NOT_COVERED docs). The must-have was
  *"Non-negotiable ordering: written down first, mint second"* (`phase0-live-mint/prd.md:137-139`).
  The criteria were fixed in `prd.md` on 2026-07-21 — **before** the mint — so the timing
  claim is still true and `git`-checkable; but it is true of `prd.md`, not of the document
  that will publish the number. This must be stated plainly, not quietly fixed.
- **Three divergent gate statements persist.** `ROADMAP.md:119-121` (adds "reproducible"),
  `PHASE0_RESULTS.md:97-107` (adds a non-zero-rate PROCEED clause, **drops** the ≥50
  denominator and the independence rule), and the canonical pre-registered block
  (`phase0-live-mint/prd.md:58-71`) — which is in neither downstream doc. Requirement #19
  says the pre-registered block becomes canonical and the others point at it. Not done.
- **`finding_kind` was specified but never built.** `grep -rn "finding_kind" src/belay/corpus/`
  is empty; `case.py:41` still has only the four labels. So `STAGE2_FINDINGS.md:89-92`'s
  requirement — report the raw A1 rate **and** the corrupt-success subset separately — is
  **mechanically unsatisfiable today**. This is a live blocker on the write-up, not on the
  mint.
- **The RUNBOOK's six defects are all still present**, including one that would actively
  corrupt a resumed mint: `RUNBOOK.md:94` *"**Parallelism is allowed**"* with a `for … &`
  loop at `:96-103`, directly contradicting sequential-by-design and `StdioMcp`
  thread-unsafety. Plus a stale BLOCKED banner at `:5-18` referring to a bug fixed in v0.4.0.
- **`eval/resume_mint.sh` destroys evidence.** It `rm -rf`s every non-`captured` instance
  dir and rewrites `checkpoint.json` to keep only `captured` before each attempt — which is
  why run A's failure diagnostics no longer exist. Its `.mint_key` convention is documented
  nowhere (`grep -rn "mint_key" docs/ eval/` → nothing; only two `.gitignore` lines).

---

## 6. The loaded-gun default

`entrypoint.py:69-70` sets `DEFAULT_PROVIDER = "openai-compat"`, `DEFAULT_MODEL =
"gemini-flash-latest"`. `STAGE2_FINDINGS.md:25-39` established that flash-class models hit
the step cap doing **only reads and searches**, never editing, and that this produces *"a 0%
violation rate that means 'the agent did nothing' … worse than `INSTRUMENT SUSPECT`, because
it looks like a result. The pre-registered gate would read it as a PIVOT on the premise, when
the premise was never tested."* → *"**Pro-class is required**, and the published number must
name the model."*

The CLI default is therefore a **known-bad default for a real mint** that was never updated.

**Consequence for a resume:** the 12 banked s3 instances ran on `gemini-3.1-pro-preview`. If
the remaining 34 are minted on a different model to dodge quota, **the 68 are no longer one
population**, and the write-up must record which model minted which instance.

---

## 7. Guardrail analysis — is retry "agent-framework drift"?

**No, and two documents pre-authorize it in writing.** The distinction must still be written
down explicitly, because six code/doc sites say "no retries".

Every "no retry" statement is scoped to the **agent loop / model behaviour** — none is about
transport, status codes, or provider errors:

| Site | Wording |
|---|---|
| `phase0-live-mint/prd.md:236-237` | *"**Agent sophistication** — no planning, memory, retry-with-reflection, or multi-step autonomy in the driver. That is agent-framework drift (guardrail #1)."* |
| `loop.py:11-12` | *"**This is not an agent framework.** One call in flight at a time, no planning, no memory strategy …, **no retries**."* |
| `eval/README.md:22-29` | *"…no multi-tool batching, **no retries**, no autonomy."* |
| `clients/__init__.py:5-6` | *"no **agentic** retry loop of their own"* |

The two that **permit** it:

| Site | Wording |
|---|---|
| `batch-harness/spec.md:52-53` | *"**Retrying a *failed instance* is fine; making the *agent* smarter is not.**"* |
| `batch.py:20-21` | *"**Retrying a *failed instance* is a later, explicit choice**; making the *agent* smarter is out of scope."* |

**This unit is that explicit choice.** The honest structural move: leave `run_task`
retry-free so `loop.py:11-12`'s claim stays literally true, and put resilience in the
model-call / client layer.

One document reads against us and must not be misread: `phase0-mint-execution/mint-execution/spec.md:52`
puts *"Retrying instances to improve the number"* out of scope. Its rationale (`:90-92`) is
unambiguous — *"silently re-rolling until the number looks good is precisely the dishonesty
this project exists to prevent."*

> **The defensibility of the re-arm rests entirely on this line:** it may retry only
> instances that produced **no observation at all** (a 429 before any turn), **never** an
> instance that produced an observation someone dislikes. That distinction must be enforced
> in code, not merely documented.

Relatedly, `eval/README.md:303-311` **bans `--force` on purpose**: *"There is deliberately
**no `--force`** and no way to forget a recorded disposition: both are ways to double-spend
by accident and to lose the record of what already ran."* The re-arm must therefore be
strictly narrower than a force — transient/quota `failed` only, `captured` never re-spent —
and must **preserve** the prior failure record rather than overwrite it.

---

## 8. Technical seams (from the call-path map)

- **Call chain:** `cli.main` → `mint_from_registry` → `mint_batch` → `run_mint` (`batch.py:123`)
  → `run_session` (`session.py:42`) → `run_task` (`loop.py:68`) → **`model.propose_next`**
  (`loop.py:111`). The MCP tool call is a *different* object at `loop.py:117`.
- **Client seam:** `Model` is a bare `typing.Protocol` with one method (`model.py:46-54`);
  `ModelFactory = Callable[[list[dict]], Model]` (`batch.py:75`), called **once per
  instance**. Wrapping the factory's product is the narrowest seam that (a) stays in
  `eval/`, (b) **structurally cannot** retry a `tools/call`, and (c) is trivially fakeable.
- **The live path is `LocalOpenAICompatModel`** (`local_client.py`), not the Anthropic
  client — Gemini via OpenAI-compat.
- **Containment is one bare `except Exception`** at `batch.py:219-225`, recording only
  `str(exc)`. **Zero error classification**; the ledger schema is exactly
  `{status, reason, trace_path}`, re-imposed by `_validate_entry` (`checkpoint.py:166-170`)
  which **drops unknown keys on load**.
- **No clock or sleep seam exists anywhere in `eval/`.** No `time.sleep` at all. The
  idiomatic pattern to introduce is a `sleep: Callable[[float], None] = time.sleep` kwarg,
  with tests asserting the **sequence of requested delays**, never elapsed wall time —
  mirroring how `TimeoutRecordingTransport` asserts the *value* of `request_timeout`.
- **Nothing records tokens, cost, or duration anywhere.** `response.usage` is present on
  both SDKs' responses and **silently discarded**; `batch.py:201` discards `run_session`'s
  return value entirely.
- **Retry hazard to pin with a test:** `propose_next` calls `_ingest_new_messages` (which
  mutates `self._seen` and the message list) *before* the API call. A retry is only safe
  because the mutation strictly precedes the throwing call. Assert that a retried
  `propose_next` sends a request **identical** to the first attempt — `FakeOpenAIClient.calls`
  already snapshots requests.
- **`entrypoint.py`'s "No clock, no randomness" rule** collides with cost/wall-clock
  recording. Put timing in the batch layer behind an injected clock, not in the config layer.
- **Fakes:** `ScriptedModel` (`fakes.py:22`) is the only shipped fake and **cannot raise a
  provider error**. A fault-injecting model/client fake and a recording `sleep` double are
  new scaffolding this unit must add.
- **`manual` marker:** `pyproject.toml:83` `addopts = "-m 'not manual'"`; the only marked
  file is `tests/test_minting_driver_smoke.py:111-117`, triple-guarded by the marker,
  `sys.platform == "darwin"`, and `BELAY_EVAL_LIVE=1`.

---

## 9. Verdict-axis placement

**None.** No axis is touched. The LLM only *acts*; A1 (invariants) and A2 (replay) decide,
unchanged. A3 is untouched. This unit feeds the axes real traces and does not alter what a
verdict claims. Consistent with `_card/issue.md:70` and the two predecessor PRDs.

**Guardrail check:** stays on the harness side. Nothing here makes the agent smarter — the
loop remains one-call-in-flight, no planning, no memory, no reflection. Sequential execution
is preserved (a blocking `sleep` on the single thread is safe; a threaded or async retry is
not, since `StdioMcp` is not thread-safe, `transport.py:212-213`).

---

## 10. Open questions for the interview

1. **Scope.** The dig shows the retry/re-arm work is *necessary but not sufficient*, and
   not the critical path. Does this unit stay narrow (harness resilience only), or absorb
   the unblocked gate-readiness work (pre-registration, verify the 7, doc corrections,
   audit)?
2. **Provider/spend.** Free tier caps at ~12 instances/day → 3–5 days for the remaining 34.
   Paid tier does it in one session. Which? This is a spend decision only the owner can make,
   and it gates the mint regardless of what code lands.
3. **Model consistency.** If the provider changes, does the model stay `gemini-3.1-pro-preview`
   so the 68 remain one population? If not, the split must be recorded per instance.
4. **The independence problem.** Even a full denominator may land <3 independent TPs. Is
   `invariant-test-mutation-shape` (deferred by `STAGE2_FINDINGS.md:94-104`) still deferred,
   accepting a possible PIVOT on benign-flag skew? Note that changing the invariant mid-mint
   would make the 12 banked instances incomparable with the rest.
5. **`finding_kind`.** Unbuilt, and it blocks the required corrupt-success-subset reporting.
   In scope here, a separate unit, or done by hand in the write-up?
6. **The `runs/` `FileNotFoundError`** (`STAGE1_REMINT_FINDINGS.md:104-105`) — discards a
   completed verification run if `runs/` is absent. Confirm fixed, or `mkdir -p` in the
   runbook. On a resumed Stage-3 verify pass this is hours of replay lost.
