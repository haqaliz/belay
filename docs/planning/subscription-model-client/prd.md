# PRD — `subscription-model-client`

**Unit:** `feat/subscription-model-client` · **Owner:** aliz · **Date:** 2026-08-05
**Base:** `origin/master` @ `d4c7647` (v0.12.0 + 2 doc commits)
**Baseline, re-confirmed by dig:** `1342 passed, 1 skipped, 1 deselected` (1343/1344 collected).
`CLAUDE.md`'s claimed *"1238 tests"* is **stale** — it is not re-derived here, only superseded going forward.
**Card:** `docs/planning/_card/issue.md`

> **Predecessor aspect spec, and its status.** The client half of this unit was specified on
> 2026-07-28 at `docs/planning/phase0-mint-resilience/subscription-model-client/spec.md` and never
> built. **That file is not rewritten by this PRD** — it is the historical record, and its 12
> acceptance criteria are carried forward verbatim into `claude-cli-model/spec.md` with additions
> named as additions. Where this PRD contradicts it, the contradiction is stated, not silently
> resolved.

---

## 1. Problem statement

**The Phase-0 mint has no funding path, and without one the gate can never be run.**

`eval/minting_driver/entrypoint.py:90` registers exactly two providers —
`PROVIDERS = ("openai-compat", "anthropic")` — and both are API-key clients
(`clients/` contains only `anthropic_client.py` and `local_client.py`). Stage 3 of the live mint
stopped at **12 captured / 56 failed of 68** on a Gemini free-tier **daily** cap, and the owner
decided on 2026-07-28 to stop using a metered key and drive the mint from an already-authenticated
Claude subscription instead. Nothing in the driver can do that.

**Why that blocks the gate specifically.** The pre-registered PROCEED clause requires a denominator
of **≥50 instances minted**. It counts *instances minted*, is **detector-independent**, and
`PHASE0_RESULTS.md:25-38` records that *"no re-verification of banked captures can ever satisfy
it."* `docs/ROADMAP.md:310` (R1) closes the loop: *"The nine zero-exposure instances **cannot be
rescued by any re-verification of banked captures**; only a re-mint reaches them."*

So the chain is: no subscription client → no affordable mint → no denominator ≥50 → **R1's
quantitative form stays untested indefinitely.** That is the cost of the status quo, and it is not
a cost that decays — it is a permanent ceiling on what Phase 0 can conclude.

### Why now — the drop-gate is discharged, and the discharge must be checkable

`spec.md:6-10` sequenced this aspect **last on purpose** and pre-committed to dropping it:

> *"If the audit gate on the 6 banked corpus cases says the problem is the blunt `tests/`
> invariant rather than the sample size, then the mint this funds is the wrong thing to run —
> and this aspect should be **dropped before it is built, not after**."*

The audit **did** say that (2026-07-29: `precision 0.00`, 0 TP / 7 FP → PIVOT). The condition is
nonetheless discharged, because the defect it protected against was then fixed and measured twice:

| Step | What it established | Where |
|---|---|---|
| `invariant-test-mutation-shape` (v0.10.0) | the blunt rule was **replaced** by `no-assertion-weakening`; **both** the precision defect and the `b"tests/"` scope defect fixed | `CLAUDE.md` status block |
| `phase0-reverify-banked` (v0.11.0) | re-measured under the shipped rule: **1/15 = 6.7%**, and **zero** flags on the 7 turns the old rule fired on — the over-firing fix holds at scale | `docs/planning/phase0-reverify-banked/` |
| `under-firing-measurable` (v0.12.0) | **9 of 15 instances compared ZERO in-scope files**; the whole held-out un-adjudicated set was **2 turns, both adjudicated clean** | `docs/planning/under-firing-measurable/prd.md:131-146` |

**The bottleneck has moved from the rule to the data.** That sentence is the entire argument for
building this now, and a reader must be able to check it against the three rows above rather than
take it on trust.

### The ICP

Unchanged from every Phase-0 unit: whoever must answer *"did this run actually do the right
thing?"* and today cannot. This unit does not serve them directly — it removes the last blocker
between them and a number that has a denominator.

---

## 2. Goals & success metrics

| # | Metric | How it is judged |
|---|---|---|
| **M0** | **The headline deliverable:** `run_mint` drives a real instance end-to-end on subscription credentials, with **no API key read or passed**, and produces a capture the stock `belay phase0 run` resolves | the live smoke (M6) — not a unit test |
| M1 | `ClaudeCliModel` satisfies the `Model` protocol and maps one completion to exactly one `ToolCall \| Done` | the 12 offline criteria, faked subprocess boundary |
| M2 | **No API key is read from the environment or passed to the child** — asserted on the **constructed env**, not only the argv | dedicated test; see §5 R-1 for why this is load-bearing and not hygiene |
| M3 | **No tools are granted to the child** — asserted on the constructed argv (`--tools ""` **and** `--strict-mcp-config`) | dedicated test per flag; this is R6/R7 in code |
| M4 | **`loop.py` and `batch.py` are byte-unmodified**, and the existing sequential / single-in-flight / containment tests pass unchanged | `git diff --stat` assertion + existing suite |
| M5 | **Exposure is forecast before the mint is funded**, with its denominator and an explicit statement that it forecasts a property of the **task description**, never agent behaviour | the forecast artifact + its pre-registered reading rule (§2.1 Rule B) |
| M6 | **One** live instance runs and produces a **real `edit_file`** crossing the MCP boundary | the manual smoke, run once, output committed verbatim |
| M7 | Baseline holds: `1342 passed, 1 skipped, 1 deselected` plus this unit's new tests; **zero runtime dependencies** unchanged | `uv run pytest` |
| M8 | `eval/README.md` documents the subscription path, its setup, and its **stated limits** | doc review against the shipped argv |

**Explicit non-metric — no violation rate is produced here.** This unit cannot produce a Phase-0
number, cannot clear the gate, and does not attempt to. A rate quoted from the single smoke
instance would be **n=1 and not a base rate**, exactly as `ROADMAP.md:280` records for the previous
n=1.

### 2.1 Pre-registered reading rules — fixed BEFORE anything is run

Two separate rules, for two separate artifacts. Both are committed before the runs they govern, or
they are post-hoc and worthless.

**Rule A — the live smoke (M6).**

| Observed | Reading | Action |
|---|---|---|
| A real `edit_file` crosses the MCP boundary and the capture replays | the prompted-tool-call path **works on a real repo at n=1** | Proceed to fund the mint. **Never** read as "edit quality is good" — one instance is not a quality measure |
| The model only reads, or emits no tool call | **the STAGE2 failure, reproduced** (`STAGE2_FINDINGS.md:25-39` — *"a 0% violation rate that means 'the agent did nothing'"*) | **Do not launch a batch.** Fix the prompt or the client first. This is the outcome the mitigation exists to catch |
| The response is unparseable | a client defect, **not** a model verdict | Fix the parser. An unparseable response must already have raised — if it silently became a `Done`, criterion 3 has regressed |
| A capture is produced but `belay phase0 run` reads `INSTRUMENT SUSPECT` | a **bridge/wiring** failure, never a result | Fix the wiring. `bridge_capture` is the load-bearing test for exactly this |

**Rule B — the exposure forecast (M5).**

| Observed | Reading | Action |
|---|---|---|
| A **substantial share** of the 166 describe tests / tracebacks / reproductions | the population contains many tasks that plausibly induce test edits; a near-zero mint result would then be informative about **agents**, not about the corpus | Fund the mint |
| **Very few** do | a mint on this population would likely return **another uninterpretable near-zero**, at ~11 h | **Stop and re-scope the population before spending.** But weigh it against the asymmetry below before acting |
| Forecast is high but v0.12.0's *measured* exposure was low | the gap is **agent behaviour**, not task supply — the agents did not touch what the tasks invited | Report the gap explicitly; a finding about the driver, and it does **not** by itself block the mint |

**The asymmetry, pre-registered.** The signal **under-counts by construction**: flask scores
**0/1**, yet `flask-4992` wrote to a test file **four times**, because *adding* a test is normal
correct behaviour a problem statement never has to mention. So a **high** score is reasonable
evidence the population can produce exposure, while a **low** score is **weaker** evidence that it
cannot. The stop-branch must be read with that asymmetry, not as a symmetric threshold.

**What the forecast is NOT.** It measures a property of the **task description** — text the agent is
handed anyway. It **cannot** predict whether an agent will write to a test file, and any sentence
implying otherwise is a misreading. It is **not comparable** to v0.12.0's 17 judgments, which
counted *observed writes* by a *specific model* on a *different population*. Publishing the two side
by side without that sentence attached is the failure mode this rule exists to prevent.

*(The first version of this rule was built on a test-directory **surface count**. Self-critique
established that it would return ≈166/166 and that its stop-branch could never fire; it was
replaced before anything was run — `prd.md` D-6, `exposure-forecast/spec.md`.)*

---

## 3. What is being built, and what it is not

Three aspects. The first is the original spec; the other two exist because of what v0.12.0 measured
and what the challenge phase surfaced.

| Aspect | One-line boundary | Rough size |
|---|---|---|
| `claude-cli-model` | A `Model` implementation driving `claude -p` as a subprocess with **no tools granted and no API key**, registered as an explicit `--provider` choice | **~4–6 h** |
| `exposure-forecast` | An **offline** forecast, from each instance's own problem statement, of how many of the 166 registry instances describe a task that plausibly induces test-file edits — published with its denominator before the mint is funded | **~1.5–2 h** |
| `live-smoke-confirmation` | **One** instance, run live, that must produce a real `edit_file` — the unit's exit criterion and the mint's go/no-go | **~1–2 h** |

**Rough total: ~7–10 h**, and every number above is a guess made before a plan exists — treat it as
something to push back on, not as data. Sizing rationale: `claude-cli-model` is the bulk (20
criteria, a new provider branch, an argv/env surface, docs) but has a very close template in
`anthropic_client.py` and needs no SDK; `exposure-forecast` reads two committed JSON files and
needs no clones or network after the re-spec (D-6); `live-smoke-confirmation` is mostly wall-clock
on one instance plus the freeze-protocol commits. **For comparison, the thing this unblocks — the
mint itself — is ~11 h of wall-clock on its own.**

### The architecture, and the alternative that is forbidden

`spec.md:34-52` considered two designs and rejected one. The rejection is restated here because it
is the property everything else rests on.

**Option A — Claude Code as the *agent*, with `belay.proxy` between it and its MCP servers.
REJECTED.** It forfeits both properties that make a mint capture verifiable at all:

- **R6** (*all edits cross the MCP boundary*) degrades from a **fact** to a **permission policy**.
  Claude Code has built-in `Edit`/`Write`/`Bash`; anything done with those is invisible to Belay →
  empty deltas → `INSTRUMENT SUSPECT`. Research indicated a *complete* built-in deny may not even
  be achievable.
- **R7** (*one `tools/call` in flight*) breaks outright — Claude Code batches tool calls in
  parallel, `StdioMcp` is not thread-safe (`transport.py:212-213`), and concurrent calls break the
  per-turn snapshot/restore that makes a turn verifiable.

**Option B — Claude Code as a *completion oracle with no tools*. CHOSEN.** Invoke `claude -p`
headlessly, pass the MCP tool schemas as **data in the prompt**, parse one `ToolCall | Done` back
out. Because the child is granted no tools, it never touches the filesystem: the harness still owns
the loop, every edit still crosses MCP, and there is nowhere a second `tools/call` could be issued.

> **R6 and R7 remain true BY CONSTRUCTION, exactly as today. `loop.py` and `batch.py` are
> unchanged.** That is why Option B won, and it is this unit's load-bearing property. If an
> implementation needs to touch either file, **the design is wrong** — stop and re-derive.

*(These R6/R7 are the mint's requirement ids from `phase0-live-mint/prd.md`. They are **distinct**
from the `ROADMAP.md` risk-register R6/R7, which are different claims entirely.)*

---

## 4. Feasibility — measured on this machine, 2026-08-05

The 2026-07-28 spec recorded a feasibility test against Claude Code **2.1.220**. It was re-run today
against **2.1.221**, plus four further probes. Full notes:
`scratchpad/cli-probe-findings.md`. Five paid calls, ~$0.5 total.

| # | Finding | Consequence for the build |
|---|---|---|
| **P0** | `env -u ANTHROPIC_API_KEY claude -p … --output-format json` → `is_error:false`, `subtype:"success"`, `result:"OK"` | The spec's core premise **still holds today**. `~/.claude/.credentials.json` does not exist; Keychain-backed OAuth answers |
| **P0b** | ⚠️ `ANTHROPIC_API_KEY` **is set** in this operator's environment. Re-verified the harness-shaped path from a **scrubbed** env (`env -i HOME PATH USER`) via `subprocess.run([...])` → exit 0, `result:"OK"`, key confirmed absent from the child | Auth survives env scrubbing and does **not** depend on being launched from a Claude Code session. **And** criterion 7 is load-bearing, not hygiene — see §5 R-1 |
| **P1** | `--tools ""` — *"Use `""` to disable all tools"* — accepted | This, not a denylist, is the criterion-8 flag. An **allowlist emptied** beats an enumerated denylist |
| **P1b** | `--strict-mcp-config` — *"Only use MCP servers from `--mcp-config`"* | **Required and unmentioned by the spec.** Without it the operator's own MCP servers are inherited into the oracle — a filesystem path that bypasses the proxy, i.e. an **R6 hole** |
| **P2** | ⚠️ `--bare` disables hooks/plugins/CLAUDE.md but states *"OAuth and keychain are **never** read"* | It looks like the isolation flag and would **break the entire subscription path**. `--safe-mode` is the safe alternative (*"Auth … work[s] normally"*) |
| **P3** | ⚠️ `--max-turns` is **absent from `--help`**, is accepted silently, and did **not** bound a run (`--max-turns 1` → envelope `num_turns: 2`) | Treat as a **no-op**. The harness's `DEFAULT_MAX_STEPS` is the real bound; do not rely on a tolerated-and-ignored flag |
| **P4** | `--model sonnet` → `modelUsage` keyed `claude-sonnet-5`. **Omitting `--model` inherited the ambient session model** (`claude-opus-5[1m]`) | Criterion 9 with live evidence: the implicit default is **real, silent, and wrong** |
| **P5** | Envelope keys include `result`, `usage` (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`), `is_error`, `subtype`, `api_error_status`, `permission_denials`, `num_turns`, **and `total_cost_usd`** | `usage` feeds `run-accounting` directly. `permission_denials: []` is a **checkable assertion that no tool was attempted**. `total_cost_usd` → **dropped**, see §6 D-1 |
| **P6** | Tool schemas in the prompt + `--tools ""` returned, verbatim: `{"kind":"tool_call","name":"read_file","arguments":{"path":"/repo/setup.py"}}`; `num_turns:1`, `stop_reason:"end_turn"`, `permission_denials:[]` | The prompted-tool-call path parses cleanly. **One toy data point — NOT evidence that edit behaviour survives.** That is precisely what M6 exists to test |
| **P7** | `--json-schema` exists (the 2026-07-28 spec could not have known). The one probe using it took `duration_api_ms` **88981 (~89 s)** vs ~6–9 s without, returning `stop_reason:"tool_use"`, `num_turns:2` | **Rejected, with the measurement as the reason** — at 68 instances × ≤12 steps that is hours. Strict hand-parsing remains the contract |
| **P8** | `--no-session-persistence` — *"sessions will not be saved to disk"* | Adopt. A 68 × ≤12 mint would otherwise leave ~800 session files on the operator's box. It forfeits inspection of the *oracle's* sessions only — the mint's evidence is the Belay trace |

---

## 5. Risks & open questions

| # | Risk | Standing |
|---|---|---|
| **R-1** | **A leaked `ANTHROPIC_API_KEY` silently bills a metered key.** P0b confirms the key **is set** on this box. If it reaches the child env, the run *succeeds*, looks identical, and defeats the aspect's entire purpose **with no visible symptom** | **Mitigated by test, on the constructed env** — argv-only assertion is insufficient |
| **R-2** | **Prompted tool-calls are more brittle than native tool-use** and may degrade edit behaviour. `STAGE2_FINDINGS.md:25-39`: a read-only model produced *"a 0% violation rate that means 'the agent did nothing'"* — **worse than `INSTRUMENT SUSPECT`, because it looks like a result** | **Open, and it is the reason M6 is an exit criterion.** P6 is one toy data point and does not retire it |
| **R-3** | **The population may have no exposure to give.** v0.12.0: 9/15 instances compared **zero** files; 17 judgments over **7 distinct files** from **2 instances**. If that is a property of SWE-bench-lite, an ~11 h mint returns another uninterpretable near-zero | **Open — this is why `exposure-forecast` exists.** It converts an ~11 h gamble into a pre-registered decision. **Partly de-risked already:** the signal was measured before being specified — 59/166 = 36%, spread 0/4 to 3/3 per repo — so the forecast will at least discriminate, unlike the surface count it replaced (D-6) |
| **R-9** | **The forecast is a proxy that under-counts**, and a reader may treat it as a prediction of agent behaviour | Named in the reading rule's asymmetry clause and in `exposure-forecast` criterion 8, with `flask-4992` cited as the concrete false negative. **Residual and accepted:** no offline signal can predict conduct |
| **R-4** | **Subscription rate/usage limit shapes are undocumented**, so `classify_error` may not recognise them on first contact | Accepted: unrecognised → **`terminal`, never `transient`**. Recording `failed` and continuing beats retrying into a wall |
| **R-5** | **ToS is an open, owner-accepted assumption** (2026-07-28, `spec.md:142-146`). Anthropic's docs bar third-party developers from *offering* claude.ai login for their products, and are **silent** on running one's own eval on one's own subscription and on unattended batch automation | **Recorded as a stated assumption, not a settled fact**, and it belongs in the published write-up's limitations. **Re-affirmed by the owner 2026-08-05** at the review gate, with the first outward-facing act (the live smoke) explicitly in view. Still an assumption; the re-affirmation does not convert it into a settled fact |
| **R-6** | **Population split.** 12 instances ran on `gemini-3.1-pro-preview`; the rest will not. Per-instance provenance makes it reportable | **Open, and deferred to the mint unit by decision.** No marginal token cost on a subscription makes a single-model re-mint of all 68 (~11 h wall-clock) affordable — but that is the mint's call, not this unit's |
| **R-7** | **Undocumented CLI surface can change under us.** P3 shows `--max-turns` is accepted-but-absent-from-help and does not bound; a future release could change `--tools ""` semantics | Partially mitigated: every flag the client depends on is **asserted in a test on the constructed argv**, so a semantic change surfaces as a failing test rather than a silent behaviour change. **It does not protect against the flag still being accepted while meaning something new** — that is residual and named |
| **R-8** | **The corpus stays machine-bound through the server.** Each case's `server_command` is an absolute path into `eval/servers/` | Pre-existing, **neither created nor fixed here**. Named so it is not mistaken for a regression of this unit |

### Open questions

1. **Which model does the mint itself run on?** The smoke defaults to `claude-opus-5` (§6 D-2).
   The mint's model is the mint unit's decision and interacts with R-6.
2. **Does `--safe-mode` belong in the shipped argv?** It isolates from the operator's hooks,
   plugins, and `CLAUDE.md` without touching auth (P2). It is *probably* right for reproducibility
   — a mint whose oracle inherits the operator's `CLAUDE.md` is not reproducible on another box —
   but it was not probed, so it is an open question, not a decision.
3. **Does the `claude` CLI accept a full `claude-opus-5` id, or only aliases?** `--help` documents
   both (*"or a model's full name (e.g. 'claude-fable-5')"*) and P4 exercised only the `sonnet`
   alias. **Verify in the first task, not at smoke time.**

---

## 6. Decisions taken (owner-confirmed 2026-08-05)

| # | Decision | Reasoning |
|---|---|---|
| **D-1** | **`total_cost_usd` is dropped entirely.** Only token counts are recorded | `run-accounting`'s rule — *"no dollar amount is ever computed or stored"* — stays literally true. The field read **$0.248 on a subscription run where no money was spent**; recording it unqualified would put a fabricated cost in a published write-up |
| **D-2** | **The smoke's default model is `claude-opus-5`**, written as a **full id, never the `opus` alias** | Mirrors the intent of `DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"` (`tests/test_minting_driver_smoke.py:127`) at the current Opus. An alias silently drifts to whatever is newest — which is exactly what criterion 9 forbids |
| **D-3** | **`--json-schema` is rejected**, with P7's timing as the stated reason | Measured, not assumed: ~89 s vs ~6–9 s per call is hours across the mint. Criterion 3 demands an error-never-a-guess either way, so the schema buys little |
| **D-4** | **The exposure forecast is built from repo surface + measured base rate**, not from gold patches | The registry stores no `patch`/`test_patch` (verified: `pool.json`/`selected.json` carry only `base_commit`, `instance_id`, `is_control`, `problem_statement`, `repo`, `task_string`). Downloading gold patches would put **an answer key next to the eval** — a mint-voiding contamination hazard — and add a network dependency the repo does not have |
| **D-5** | **The live smoke is this unit's exit criterion**, not a deferred nicety | R-2 is the headline risk and is cheapest to fix now. A client that passes 12 offline tests and cannot drive a real edit is not a deliverable |
| **D-6** | **The exposure forecast is built from each instance's own `problem_statement` / `task_string`**, not from a test-directory surface count | Self-critique caught that a surface count returns **≈166/166** — all seven repos have a `tests`/`testing` directory — so its *"stop and re-scope"* branch could **never fire**. The text signal was **measured before being specified**: `59/166 = 36%`, spread 0/4 (requests) to 3/3 (pylint). It also drops the aspect's clone/network cost to zero. See `exposure-forecast/spec.md` |
| **D-7** | **If the live smoke comes back red, `claude-cli-model` still merges; the mint stays unfunded** | The client is independently correct and tested — a red smoke is a finding about *prompted-tool-call behaviour*, not a client defect. Recording the red result verbatim and merging keeps the freeze protocol honest (the result is published either way) and removes the incentive to re-run the smoke until it passes, which is the anti-re-roll hazard. **Decided before the run, on purpose** |

---

## 7. Technical considerations

- **Capability:** none. This is **`eval/`-only** — it is not a C1–C9 engine capability, not a
  product surface, and **not** the `belay` CLI. It changes **no** verdict on **any** axis.
- **No `src/belay/` change.** If a task needs one, stop and re-derive: the driver is a consumer of
  the engine, and a client that needs the engine to change is reaching across the boundary.
- **Zero runtime dependencies preserved, trivially.** `clients/__init__.py:8-14` exists to keep
  SDKs out of the core import graph — each client lazily imports its SDK inside `__init__`.
  `ClaudeCliModel` needs **no SDK at all** (stdlib `subprocess`), so it satisfies that boundary by
  construction rather than by discipline. `tests/test_minting_driver_clients_import.py` is the
  guard and must stay green.
- **The seam, and how it differs from its siblings.** `AnthropicModel`/`LocalOpenAICompatModel`
  take `client=` (an injected SDK object). `ClaudeCliModel`'s boundary is a **subprocess**, so its
  seam is a **`runner=` callable** defaulting to `subprocess.run`. Every offline test drives that
  seam — no `claude` binary, no network, no subscription.
- **Per-instance construction is mandatory.** `make_model_factory` (`entrypoint.py:319-379`) builds
  a **fresh** client *and* a fresh `RetryingModel` **per instance**, and the docstring records why:
  clients accumulate conversation state, so a hoisted client hands instance N instance N−1's
  conversation, and a hoisted wrapper bills *"instance 1's retries to instance 40."*
  *"Cache the client, it's the same config"* is the obvious refactor and it is **wrong**.
- **Accounting contract** (mirrored from `anthropic_client.py:150-183`): `request_count` is
  incremented **before** the call — a request that comes back a 429 still spent quota — and `usage`
  stays `None` until a response reports it. **Absent is never zero.**
- **Credentials:** `resolve_credentials` (`entrypoint.py:280-316`) is *"the only place the entry
  point touches the environment."* `claude-cli` returns `{}` and — unlike `anthropic`, which
  returns `{}` because the SDK reads its own key — reads **nothing**, which is the difference the
  test must pin.

---

## 8. Out of scope

- **Running the mint.** This unit builds the client and proves it on **one** instance. The ~11 h
  batch is a **separate follow-on unit**. This unit cannot clear the gate and does not try.
- **Option A** — Claude Code as the agent. Rejected in §3; do not drift into it.
- **Changing `loop.py` or `batch.py`.** If the design needs either, the design is wrong.
- **Any concurrency.** `StdioMcp` is not thread-safe and R7 is by construction.
- **Agent sophistication** — no planning, memory, reflection, or multi-step autonomy. The oracle is
  strictly *less* agentic than the existing clients' native tool-use, not more.
- **Removing or changing the existing API-key clients.** They stay, and remain the path for anyone
  with a metered key.
- **Dollar cost accounting** → D-1, and `run-accounting` is already built.
- **Any change to `src/belay/`**, to A1/A2/A3 semantics, to `verdict.reduce`, or to the
  `NOT_COVERED` boundary.
- **C7** (live console), **C8** (A3), **C9** export-back.
- **Re-deriving any published number.** `4/16`, `precision 0.00`, `3/93`, `recall 0.00`, `1/15`,
  and the 17-judgment exposure figure all stand unedited.
