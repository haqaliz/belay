# Aspect — `claude-cli-model`

**Unit:** `subscription-model-client` · **Order: FIRST.** Blocks both other aspects.
**Supersedes in scope (not in record):**
`docs/planning/phase0-mint-resilience/subscription-model-client/spec.md` (2026-07-28, never built).
That file stays as the historical record; its 12 criteria are carried forward **verbatim** below as
1–12, and everything added since is numbered 13+ and marked **NEW**.

---

## Problem slice

The mint driver has no client that can run on subscription credentials. Its two clients
(`clients/anthropic_client.py`, `clients/local_client.py`) both take an API key, and
`entrypoint.py:90` registers exactly `("openai-compat", "anthropic")`.

## User outcome

The mint runs without a metered API key, on credentials the operator already has, with **every**
verifiability property of the existing path preserved.

## In scope

- **`ClaudeCliModel`, implementing the `Model` protocol** (`model.py:46-54`), driving `claude -p`
  as a subprocess:
  - `--output-format json` for a parseable envelope;
  - **no tools granted** — `--tools ""` **and** `--strict-mcp-config`; the MCP tool schemas are
    passed as *data in the prompt*;
  - `--no-session-persistence`;
  - explicit model selection, recorded per instance;
  - a **timeout owned by the client** (see criterion 5 and the P3 note below).
- **Strict response parsing** into `ToolCall | Done`, tolerant of prose around a JSON payload but
  never *guessing*: an unparseable response is a **named error**, never a fabricated `Done`.
- **Honest error classification** reusing `resilience.classify_error`: spawn failure, non-zero
  exit, timeout, malformed JSON, and schema-invalid tool calls each map to a named kind.
  **Subscription rate/usage limits classify `quota`** where their shape can be recognised and
  `terminal` where it cannot — **never `transient`**.
- **Registration as a provider** alongside `openai-compat` and `anthropic`, as an explicit
  `--provider` choice, never selected by sniffing the environment.
- **No API key read or required** on this path, and none passed to the subprocess.
- **Per-instance accounting** mirroring `anthropic_client.py:150-183` — `provider`, `model`,
  `request_count` (incremented **before** the call), `usage` (**`None` until reported**).
- **Docs:** `eval/README.md` gains the subscription path, its setup, and its stated limits.

## Out of scope

- **Option A** — Claude Code as the agent (`prd.md` §3). Do not drift into it.
- Changing `loop.py` or `batch.py`. If this aspect needs either, the design is wrong.
- Any concurrency; any agent sophistication.
- Removing or changing the existing API-key clients.
- Dollar cost accounting (`prd.md` D-1).
- Any change to `src/belay/`.
- Running any instance — that is `live-smoke-confirmation`.

## Acceptance criteria

All of 1–12 run behind a **faked subprocess boundary** — no `claude` binary, no network, no
subscription. The seam is a **`runner=` callable** defaulting to `subprocess.run`.

**Carried forward verbatim from the 2026-07-28 spec:**

1. **A well-formed response maps to a `ToolCall`** with the right name and arguments.
2. **A completion response maps to `Done`.**
3. **An unparseable response raises a named error** — never a fabricated `Done`, never a
   silently-dropped turn.
4. **A tool call naming a tool not in the provided schemas is an error**, not passed through.
5. **A non-zero exit / spawn failure / timeout each classify** to their named kind via the shared
   classifier.
6. **An unrecognised failure classifies `terminal`**, never `transient`.
7. **No API key is read from the environment or passed to the subprocess** — asserted, because
   silently falling back to a metered key would defeat the entire point.
8. **No tools are granted to the subprocess** — asserted on the constructed argv. *(This is the
   R6/R7 guarantee in code: if this test ever weakens, the mint's verifiability claim weakens with
   it.)*
9. **The model id is explicit in the argv and recorded**; the client cannot run on an implicit
   default.
10. **Cross-turn conversation is threaded correctly** — a second `propose_next` includes the first
    turn's tool result, mirroring the existing clients' `tool_call_id` tests.
11. **`loop.py` and `batch.py` are unmodified**, and the existing sequential / single-in-flight /
    containment tests pass unchanged.
12. **The live smoke is `manual`-marked** and excluded by the default
    `addopts = "-m 'not manual'"` (`pyproject.toml:83`).

**NEW — added 2026-08-05 from the dig and the live probes:**

13. **NEW — criterion 7 is asserted on the constructed CHILD ENV, not only the argv.**
    `ANTHROPIC_API_KEY` **is set** on this operator's box (`prd.md` P0b). A key leaked via
    inherited env produces a run that *succeeds and looks identical* while silently billing a
    metered key. Argv-only assertion does not catch it.
14. **NEW — `--strict-mcp-config` is present in the argv**, asserted separately from `--tools ""`.
    Without it the operator's own MCP servers are inherited into the oracle — a filesystem path
    that bypasses the proxy, i.e. an **R6 hole**. The 2026-07-28 spec did not know this flag.
15. **NEW — `--bare` is absent from the argv**, asserted. Its help states *"OAuth and keychain are
    never read"*: it looks like the isolation flag and would break the subscription path outright.
    This is a **negative** assertion and is deliberate — the failure it prevents is a plausible
    future "improvement".
16. **NEW — the client does not rely on `--max-turns`.** It is absent from `--help`, accepted
    silently, and did **not** bound a run (`--max-turns 1` → `num_turns: 2`). The bound is the
    harness's `DEFAULT_MAX_STEPS` plus the client-owned subprocess timeout.
17. **NEW — `total_cost_usd` is never read, stored, or surfaced** (`prd.md` D-1), asserted against
    a fake envelope that contains it.
18. **NEW — `usage` is absent-never-zero**: an envelope reporting no usage leaves `usage` as
    `None`, and one reporting partial fields records only those fields.
19. **NEW — `permission_denials` non-empty is an error, not a silent pass.** The envelope exposes
    it, and a non-empty value means the oracle *attempted a tool* — which under `--tools ""` should
    be impossible. Treat it as an instrument fault rather than discarding the signal.
20. **NEW — the default model constant is a full id, not an alias.** `claude-opus-5`, never
    `opus`: an alias silently drifts to whatever is newest, which is exactly what criterion 9
    forbids.

## Dependencies & sequencing

- **Depends on:** `quota-circuit-breaker` (`resilience.classify_error`, **built**) and
  `run-accounting` (per-instance provenance, **built**). The audit-gate precondition is
  **discharged** — `prd.md` §1.
- **Blocks:** `live-smoke-confirmation` (hard), and the follow-on mint unit.
- **Independent of:** `exposure-forecast`, which touches no client code and can run in parallel.

## Open questions

1. **Does the CLI accept a full `claude-opus-5` id, or only aliases?** `--help` documents both;
   the probe exercised only `sonnet`. **Verify in the first task**, not at smoke time.
2. **Does `--safe-mode` belong in the argv?** It isolates from the operator's hooks, plugins, and
   `CLAUDE.md` without touching auth — probably right for reproducibility (an oracle inheriting the
   operator's `CLAUDE.md` is not reproducible on another box) — but **it was not probed**, so it is
   an open question, not a decision.
3. **What shape does a subscription usage limit actually take?** Undocumented. The `terminal`
   fallback keeps it safe; the first real limit encountered is a finding for the mint unit.
