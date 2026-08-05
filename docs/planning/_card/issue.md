# feat/subscription-model-client

**Type:** feat · **Id (slug):** `subscription-model-client` · **Owner:** aliz
**Source:** inline brief (no GitHub issue — the tracker has never been used; all PRs are
issue-free). Produced by `/belay-next` on 2026-08-05 and invoked as
`bbf feat subscription-model-client`.
**Base:** `origin/master` @ `d4c7647` (v0.12.0 + two doc commits).

> **Predecessor.** This card replaces the previous `_card/issue.md`, which described
> `feat/under-firing-measurable` (merged at `7bcd82b`, released v0.12.0). That unit made A1's
> silence interpretable: exposure is now structured data on the verdict, a ledger is committed
> so the number re-derives, and the corpus can declare and score a **recorded miss**. Its
> result — **17 file-comparisons over 7 distinct files; 6 instances judged something, 9
> compared ZERO; 0 misses found of 2 adjudicated** — is the decision input this unit acts on.
> **This unit is that follow-on**, named as such in
> `docs/planning/under-firing-measurable/prd.md:57` and `…/miss-measurement/spec.md:106`.

---

## Brief

Build **`ClaudeCliModel`** — the last unbuilt aspect of `phase0-mint-resilience`, fully
specified at `docs/planning/phase0-mint-resilience/subscription-model-client/spec.md`
(written 2026-07-28, never started).

It drives `claude -p --output-format json` as a subprocess with **no tools granted** (the MCP
tool schemas are passed as *data in the prompt*), parses exactly one `ToolCall | Done` back
out, registers as an explicit `--provider` choice alongside `openai-compat` and `anthropic`,
reads **no API key**, and reuses `resilience.py`'s `classify_error`.

**Why now.** The mint has no working funding path: `eval/minting_driver/entrypoint.py:90`
registers exactly `("openai-compat", "anthropic")`, both API-key clients
(`eval/minting_driver/clients/` holds only `anthropic_client.py` and `local_client.py`), and
Stage 3 died on a Gemini free-tier **daily** cap. The owner decided on 2026-07-28 to drive the
mint from an already-authenticated **Claude subscription** instead.

### The drop-gate is resolved in the affirmative, and the card must say why

`spec.md:6-10` sequences this aspect **last on purpose** and pre-commits to dropping it:

> *"If the audit gate on the 6 banked corpus cases says the problem is the blunt `tests/`
> invariant rather than the sample size, then the mint this funds is the wrong thing to run —
> and this aspect should be **dropped before it is built, not after**."*

The audit **did** say exactly that (2026-07-29, `precision 0.00`, 0 TP / 7 FP → PIVOT). The
condition is nonetheless discharged, because the thing it protected against has since been
fixed and measured twice:

| Step | What it established | Where |
|---|---|---|
| `invariant-test-mutation-shape` (v0.10.0) | the blunt rule was **replaced** by `no-assertion-weakening`, fixing **both** the precision defect and the `b"tests/"` scope defect | `CLAUDE.md` status block |
| `phase0-reverify-banked` (v0.11.0) | re-measured under the shipped rule: **1/15 = 6.7%**, and **zero** flags on the 7 turns the old rule fired on — the over-firing fix holds at scale | `docs/planning/phase0-reverify-banked/` |
| `under-firing-measurable` (v0.12.0) | **9 of 15 instances compared ZERO in-scope files**; the entire held-out un-adjudicated set was **2 turns, both adjudicated clean** | `docs/planning/under-firing-measurable/prd.md:131-146` |

`docs/ROADMAP.md:310` (R1) states the consequence directly: *"The nine zero-exposure instances
**cannot be rescued by any re-verification of banked captures**; only a re-mint reaches them."*
**The bottleneck has moved from the rule to the data.** That is the whole argument for
building this now, and it is an argument the reader must be able to check — not an assumption.

### Out of scope

- **Running the mint.** This unit builds the client; the ~11 h live mint is a **separate
  follow-on unit**. This unit cannot produce the Phase-0 number and cannot clear the gate.
- **Option A — Claude Code as the *agent*** (`spec.md:34-52`). Rejected: it forfeits R6 (all
  edits cross the MCP boundary) and R7 (one `tools/call` in flight), the two properties the
  mint's verifiability rests on. Do not drift into it.
- Changing `loop.py` or `batch.py`. If this aspect needs either, the design is wrong.
- Any concurrency; any agent sophistication (planning, memory, reflection).
- Removing or changing the existing API-key clients — they stay, and remain the path for
  anyone with a metered key.
- Computing dollar costs (→ `run-accounting`, already built).
- **Any change to `src/belay/`.** This is `eval/`-only.

---

## Why this unit, and why now

| File | Says |
|---|---|
| `docs/ROADMAP.md:310` (R1) | *"only a re-mint reaches them"* — the banked data is exhausted |
| `docs/ROADMAP.md:166-168` | the ≥50 PROCEED clause counts *instances minted* and is **detector-independent**, so no re-verification can ever satisfy it |
| `docs/planning/under-firing-measurable/prd.md:57` | *"The next unit is the funded re-mint (`subscription-model-client`, ~11 h)"* |
| `eval/minting_driver/entrypoint.py:90` | `PROVIDERS = ("openai-compat", "anthropic")` — both metered; there is no subscription path |
| `docs/planning/phase0-mint-resilience/subscription-model-client/spec.md` | the whole aspect, already specified: scope, 12 acceptance criteria, rejected alternative, risks |

---

## Logistics the dig must know

- **Dependencies are built and merged.** The shared classifier is
  `eval/minting_driver/resilience.py:220` (`classify_error`); per-instance provenance
  (`run-accounting`) is wired through `batch.py:72-89` and `checkpoint.py:121`. Both existing
  clients keep their own accounting (`clients/anthropic_client.py:16`,
  `clients/local_client.py:13`) — the new client must too.
- **`claude` is present on this machine**: `/Users/aliz/.local/bin/claude`, version **2.1.221**
  (the spec's feasibility test was run against **2.1.220** on 2026-07-28 with
  `ANTHROPIC_API_KEY` unset; credentials live in the macOS Keychain, `~/.claude/.credentials.json`
  does **not** exist). **That headless-auth test has not been re-run today** — re-running it is
  a dig task, not an assumption.
- **All acceptance tests run behind a faked subprocess boundary** — no `claude` binary, no
  network, no subscription. Only the `manual`-marked live smoke touches the real thing, guarded
  exactly as `tests/test_minting_driver_smoke.py:111-117` (`manual` marker +
  `sys.platform == "darwin"` + explicit env opt-in), and **never in CI**
  (`pyproject.toml:83`, `addopts = "-m 'not manual'"`).
- **The two mint worktrees may NOT be removed.** `feat-verdict-coverage-status` and
  `feat-phase0-mint-execution` hold ~5.5 GB of unregenerable, unmovable mint data (captures
  embed absolute snapshot paths) and the MCP server every trace names by absolute path.
- Baseline claimed by `CLAUDE.md`: **1238 tests, 1 platform-skip**, zero runtime dependencies.
  To be re-confirmed by the dig.

---

## Known caveats, carried forward from `/belay-next`

1. **This unit does not produce the number.** It builds the client. The mint is the follow-on,
   and the ≥50 gate clause stays unsatisfied until that mint runs. **R1 stays untested.**
2. **Prompted tool-calls are more brittle than native tool-use** (`spec.md:133-138`).
   `STAGE2_FINDINGS.md:25-39` already recorded a model that only reads producing *"a 0%
   violation rate that means 'the agent did nothing'"* — **worse than `INSTRUMENT SUSPECT`,
   because it looks like a result**. Binding mitigation: the first live run is **ONE** instance
   and must produce a real `edit_file` before any batch is launched.
3. **R6/R7 are the load-bearing property**, and they are preserved *by construction*: Claude
   Code is given no tools, so it never touches the filesystem; the harness still owns the loop;
   `loop.py`/`batch.py` are unmodified. Two acceptance criteria assert this on the constructed
   argv. If those tests ever weaken, the mint's verifiability claim weakens with them. *(These
   R6/R7 are the mint's requirement ids from `phase0-live-mint/prd.md`, **distinct** from the
   `ROADMAP.md` risk-register R6/R7.)*
4. **Subscription limit error shapes are undocumented.** An unrecognised failure classifies
   `terminal`, **never** `transient` — recording `failed` and continuing beats retrying into a
   wall.
5. **ToS is an open, owner-accepted assumption** (2026-07-28, `spec.md:142-146`): Anthropic's
   docs bar third-party developers from *offering* claude.ai login for their products, and are
   silent on running one's own eval on one's own subscription and on unattended batch
   automation. It is recorded as a **stated assumption, not a settled fact**, and belongs in the
   published write-up's limitations. Worth re-confirming with the owner before the live smoke.
6. **Population split, undecided.** 12 instances are on `gemini-3.1-pro-preview`; the rest will
   not be. Per-instance provenance makes this reportable. PRD open question 1 asks whether to
   re-mint all 68 on one model for a single clean population (no marginal token cost on a
   subscription, ~11 h wall-clock). **Decide in the dig / PRD, not mid-mint.**
