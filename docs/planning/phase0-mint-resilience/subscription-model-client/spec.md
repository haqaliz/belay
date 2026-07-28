# Aspect — `subscription-model-client`

**Unit:** `phase0-mint-resilience` · **Order: LAST — deliberately.**
**Covers PRD must-haves D (13–16).**

> **Sequenced last on purpose** (PRD self-critique, 🔴). This aspect exists to *fund* a mint.
> If the audit gate on the 6 banked corpus cases says the problem is the blunt `tests/`
> invariant rather than the sample size, then the mint this funds is the wrong thing to run —
> and this aspect should be **dropped before it is built, not after**. Do not start it until
> the audit gate has been passed.

---

## Problem slice

The mint has been running on a metered API key against a Gemini free tier whose **daily**
cap (250 requests) stopped Stage 3. The owner has decided (2026-07-28) not to use an API-key
approach and to drive the mint from an already-authenticated **Claude subscription** instead.

The driver has no client that can do that. Its two clients (`AnthropicModel`,
`LocalOpenAICompatModel`) both take an API key.

**Verified feasible, not assumed:** with `ANTHROPIC_API_KEY` explicitly unset for the
subprocess, `claude -p "…" --max-turns 1` authenticated and returned a result on this machine
(Claude Code `2.1.220`, credentials in the macOS Keychain — `~/.claude/.credentials.json` does
not exist). A doc-research pass claimed all programmatic paths require an API key; **the
direct test refutes that** and the test is the authority here.

## The design decision, and why

The `Model` protocol needs a **single completion returning at most one tool call**
(`model.py:46-54`); the harness owns the loop. Two architectures were considered:

**Option A — Claude Code as the agent**, with `belay.proxy` interposed between it and its MCP
servers. **Rejected.** It forfeits two properties the mint's verifiability rests on:
- **R6** (all edits cross the MCP boundary) becomes a *permission policy* rather than a fact.
  Claude Code has built-in `Edit`/`Write`/`Bash`; anything done with those is invisible to
  Belay → empty deltas → `INSTRUMENT SUSPECT`. Research indicated a *complete* built-in deny
  may not even be achievable.
- **R7** (one `tools/call` in flight) breaks — Claude Code batches tool calls in parallel, and
  `StdioMcp` is not thread-safe (`transport.py:212-213`). Concurrent calls also break per-turn
  snapshot/restore, which is what makes a turn verifiable at all.

**Option B — Claude Code as a completion oracle. CHOSEN.** Invoke `claude -p` headlessly with
**no tools granted at all**, passing the conversation plus the MCP tool schemas, and parse one
`ToolCall | Done` back out. Because Claude Code is given no tools, **it never touches the
filesystem**: the harness still owns the loop, every edit still crosses MCP, and there is still
nowhere a second `tools/call` could be issued.

> **R6 and R7 remain true BY CONSTRUCTION, exactly as today. `loop.py` and `batch.py` are
> unchanged.** That is the entire reason Option B won, and it is this aspect's load-bearing
> property.

## User outcome

The mint runs without a metered API key, on credentials the operator already has, with every
verifiability property of the existing path preserved.

## In scope

- **A `ClaudeCliModel` implementing the `Model` protocol**, driving `claude -p` as a
  subprocess:
  - `--output-format json` for a parseable envelope;
  - **no tools granted** — the tool schemas are passed as *data in the prompt*, and Claude
    Code is not permitted to execute anything;
  - a turn/step limit and non-interactive operation;
  - explicit model selection, recorded per instance.
- **Strict response parsing** into `ToolCall | Done`, tolerant of prose around a JSON payload
  but never *guessing*: an unparseable response is an error, never a fabricated `Done`.
- **Honest error classification**, reusing `quota-circuit-breaker`'s classifier: subprocess
  spawn failure, non-zero exit, timeout, malformed JSON, and schema-invalid tool calls each
  map to a named kind. **Subscription rate/usage limits classify as `quota`** where their
  shape can be recognised, and as `terminal` where it cannot — never `transient`.
- **Registration as a provider** alongside `openai-compat` and `anthropic`, as an **explicit
  `--provider` choice**. It is never selected by sniffing the environment
  (`eval/README.md:286-290`: *"The provider is an argument, never an environment sniff … if it
  could, the published number would name the wrong model."*).
- **No API key is read or required** on this path, and none is passed to the subprocess.
- **A `manual`-marked live smoke** (single instance), guarded exactly as
  `tests/test_minting_driver_smoke.py:111-117` — the `manual` marker, `sys.platform == "darwin"`,
  and an explicit env opt-in. Never in CI.
- **Docs:** `eval/README.md` gains the subscription path, its setup, and its stated limits.

## Out of scope

- **Option A** — letting Claude Code be the agent. Rejected above; do not drift into it.
- Changing `loop.py` or `batch.py`. If this aspect needs either, the design is wrong.
- Any concurrency.
- Agent sophistication — no planning, memory, reflection, or multi-step autonomy. Claude Code
  is used here as a **completion oracle with no tools**, which is strictly *less* agentic than
  the existing clients' native tool-use, not more.
- Removing or changing the existing API-key clients — they stay, and remain the path for
  anyone with a metered key.
- Computing dollar costs → `run-accounting`.
- Changing `src/belay/`.

## Acceptance criteria (tests first, deterministic, offline)

All of these run with a **faked subprocess boundary** — no `claude` binary, no network, no
subscription.

1. **A well-formed response maps to a `ToolCall`** with the right name and arguments.
2. **A completion response maps to `Done`.**
3. **An unparseable response raises a named error** — never a fabricated `Done`, never a
   silently-dropped turn.
4. **A tool call naming a tool not in the provided schemas is an error**, not passed through.
5. **A non-zero exit / spawn failure / timeout each classify** to their named kind via the
   shared classifier.
6. **An unrecognised failure classifies `terminal`**, never `transient`.
7. **No API key is read from the environment or passed to the subprocess** — asserted, because
   silently falling back to a metered key would defeat the entire point.
8. **No tools are granted to the subprocess** — asserted on the constructed argv. *(This is
   the R6/R7 guarantee in code: if this test ever weakens, the mint's verifiability claim
   weakens with it.)*
9. **The model id is explicit in the argv and recorded**; the client cannot run on an implicit
   default.
10. **Cross-turn conversation is threaded correctly** — a second `propose_next` includes the
    first turn's tool result, mirroring the existing clients' `tool_call_id` tests.
11. **`loop.py` and `batch.py` are unmodified**, and the existing sequential / single-in-flight
    / containment tests pass unchanged.
12. **The live smoke is `manual`-marked** and excluded by the default `addopts = "-m 'not
    manual'"` (`pyproject.toml:83`).

## Dependencies & sequencing

- **Depends on:** `quota-circuit-breaker` (shared classifier), `run-accounting` (per-instance
  model provenance), and — **as a gate, not a code dependency** — the hand-audit of the 6
  banked corpus cases.
- **Blocks:** the live mint (a follow-on unit).

## Risks & open questions

- **Prompted tool-calls are more brittle than native tool-use.** Asking for a structured tool
  call in the prompt is weaker than the SDKs' native tool-use, and may degrade the agent's
  edit behaviour — which matters, because `STAGE2_FINDINGS.md:25-39` showed a model that only
  reads produces *"a 0% violation rate that means 'the agent did nothing'"*, worse than
  `INSTRUMENT SUSPECT` because it looks like a result. **Mitigation: the first live run is ONE
  instance, and it must produce a real `edit_file` before any batch is launched.**
- **Subscription limits are undocumented**, so their error shape is unknown and the `quota`
  classifier may not recognise them on first contact. The `terminal` fallback keeps that safe
  (records `failed`, continues) rather than retrying into a wall.
- **ToS is open, and accepted-and-noted by the owner (2026-07-28).** Anthropic's Agent SDK
  docs bar third-party developers from *offering* claude.ai login for their products; the docs
  are silent on running one's own eval on one's own subscription, and on unattended batch
  automation generally. This is recorded as a **stated assumption, not a settled fact**, and
  it belongs in the published write-up's limitations rather than being quietly omitted.
- **Population split.** 12 instances are on `gemini-3.1-pro-preview`; the rest will not be.
  Per-instance provenance (from `run-accounting`) makes this reportable. PRD open question 1
  asks whether to re-mint all 68 on one model for a single clean population — no marginal
  token cost on a subscription, ~11h wall-clock. **Decide after the audit gate.**
