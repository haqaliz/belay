# `eval/` — the Phase-0 minting driver

**This is eval/mint infrastructure. It is not a product surface, not part of the
`belay` CLI, and not an agent framework.**

## What this is

The Phase-0 corpus mint (see `docs/planning/phase0-corpus-run/RUNBOOK.md`) needs traces
of a real agent doing real file/shell work, captured through Belay's MCP proxy. Nothing
in `src/belay/` drives an agent — Belay verifies traces, it does not produce them. The
minting driver (`eval/minting_driver/`) is the small program that produces them: it
drives an LLM through exactly two off-the-shelf MCP servers (filesystem, shell), placed
behind `python -m belay.proxy`, on one SWE-bench-lite instance at a time, and writes the
resulting trace to a directory that `belay phase0 run` can later verify.

## What this is NOT

- **Not a product surface.** Nothing here ships to a Belay user; it exists to generate
  the ≥50-instance corpus for `docs/technical/PHASE0_RESULTS.md`.
- **Not part of the `belay` CLI.** It is invoked directly as a Python module/test, never
  through `belay ...`.
- **Not an agent framework** (guardrail #1 in `CLAUDE.md`). The loop
  (`eval/minting_driver/loop.py`, `run_task`) is sequential and dumb on purpose: propose
  one tool call, send it, block for the reply, repeat, until the model says `Done` or
  `max_steps` is hit. No planning, no memory beyond a flat message list, no multi-tool
  batching, no retries, no autonomy. The in-flight invariant — never more than one
  `tools/call` outstanding — falls directly out of the control flow (`transport.request`
  blocks; `model.propose_next` is only called after the previous request returns), and
  `tests/test_minting_driver_loop.py` asserts it structurally with a re-entrancy counter.

The whole point of routing through MCP servers instead of giving the model native
file/shell tools is that MCP is Belay's locked ingest surface (`CLAUDE.md`, "Tech
direction"): every action the model takes this way crosses the proxy boundary and gets
recorded as a trace turn. Anything the model did through a built-in tool instead would be
invisible to Belay — this driver exists specifically so that doesn't happen.

## The MCP servers (pinned)

Two servers, each launched via a pinned `npx -y <pkg>@<version>` so a stale
`~/.npm/_npx` cache entry can never silently swap in a different version mid-mint.

Resolved by running `npm view <pkg> version` on 2026-07-21 (matches the versions found in
research — re-run this before minting in case newer versions have shipped since):

```bash
npm view @modelcontextprotocol/server-filesystem version   # 2026.7.10
npm view mcp-server-commands version                       # 0.8.2
```

### filesystem — `@modelcontextprotocol/server-filesystem@2026.7.10`

```bash
npx -y @modelcontextprotocol/server-filesystem@2026.7.10 <abs-allowed-dir>
```

- Write tools: `write_file`, `edit_file`.
- This server **declares MCP annotations** (`readOnlyHint` / `destructiveHint` / etc.) on
  its tools, so it feeds Belay's **A2** effect-conformance check for free — a
  `readOnlyHint: true` tool call that mutates state is a grounded FAIL with zero LLM
  involvement (`CLAUDE.md`, "Tech direction": annotations are self-declared, not a
  guarantee, but a real supplement).
- `<abs-allowed-dir>` must be an **absolute path** — this is the filesystem server's own
  sandbox boundary, separate from (and in addition to) Belay's Seatbelt scope. See
  "macOS gotchas" below for where to point it.

### shell — `mcp-server-commands@0.8.2`

```bash
npx -y mcp-server-commands@0.8.2
```

- Tool: `run_process`.
- **This server declares no MCP annotations.** There is no `readOnlyHint`/
  `destructiveHint`/etc. on `run_process`, so absent-vs-declared-false matters here
  exactly as `CLAUDE.md` warns: a missing annotation is not a declaration, and Belay must
  not manufacture a false PASS from it. For shell, **user-declared invariants (A1) are
  the load-bearing check** — annotation-based A2 conformance has nothing to check against.

**Judgement call, flagged explicitly:** there is no official/canonical MCP shell server.
`mcp-server-commands` is a reasonable, actively-maintained third-party choice (single
`run_process` tool, minimal surface), but it is not an MCP-project-blessed server the way
`@modelcontextprotocol/server-filesystem` is. Revisit this choice if a better-maintained
or officially-adopted alternative appears before scaling past the smoke instance.

## The gated capture env (why all three vars, not just the trace dir)

The driver always runs the proxy with the **gated** sandbox path, not capture-only:

```bash
export BELAY_TRACE_DIR=./traces          # record every tools/call as a trace turn
export BELAY_SANDBOX_SCOPE=./workspace   # the write-allowed Seatbelt boundary
export BELAY_SNAPSHOT_DIR=./snapshots    # pre-state snapshot taken before each turn
```

`eval/minting_driver/capture.py`'s `gated_env` builds exactly this environment (coercing
`Path`s to `str`, never mutating the caller's `base`/`os.environ`). Its companion
`proxy_command` builds `[sys.executable, "-m", "belay.proxy", *server_command]` — note
there is **no `--` separator**: everything after `-m belay.proxy` in argv IS the
downstream server command (`src/belay/proxy.py`), so inserting one would hand the proxy a
literal `"--"` token as part of the command it tries to spawn.

**Why gated, and not just `BELAY_TRACE_DIR` alone:** `python -m belay.proxy` will run
capture-only (byte-pump + trace, no sandbox, no snapshot) if `BELAY_SANDBOX_SCOPE` is
unset — that is a legitimate mode, but not this driver's mode. Capture-only traces have
no pre-state snapshot for any turn, so every turn `belay phase0 run` verifies against them
comes back `UNVERIFIED` (no snapshot to restore and replay against). A whole mint built on
capture-only traces would verify 0 turns and read as `INSTRUMENT SUSPECT` — the Phase-0
runner's explicit false-zero defense (R6, `CLAUDE.md`) against exactly this: a mint that
captured ~no verifiable turns must never render as a clean 0% violation rate. Setting all
three vars up front is what makes each captured turn *verifiable*, not merely recorded.

`gated_env` also fails fast, in-process, with a clear `ValueError`, on the one
combination the proxy itself refuses at startup: `BELAY_SANDBOX_SCOPE` set without
`BELAY_SNAPSHOT_DIR` (`src/belay/proxy.py`, `main()`). Without that check, a driver finds
out only after the subprocess has already exited non-zero and has to reverse-engineer a
stderr line; with it, the mistake is caught at the call site before any subprocess spawns.

**Platform:** gated capture depends on Belay's Seatbelt sandbox, which is **darwin-only**
(`CLAUDE.md`: "Belay's sandbox is macOS-only (Seatbelt + clonefile snapshot)"). The
minting driver's live path only runs on macOS.

## BYOK model clients

Two thin `Model` implementations (`eval/minting_driver/model.py`'s `Protocol`), neither
imported by the driver core (`loop.py`, `session.py`) and neither exercised in CI — both
lazy-import their SDK *inside* `__init__`, so importing the module never requires the SDK
to be installed (`tests/test_minting_driver_clients_import.py` asserts this by checking
`sys.modules`).

- **`AnthropicModel`** (`eval/minting_driver/clients/anthropic_client.py`) — wraps the
  Anthropic Messages API with tool-use. Reads `ANTHROPIC_API_KEY` from the environment
  (or takes `api_key=`/an injected `client=` directly).
- **`LocalOpenAICompatModel`** (`eval/minting_driver/clients/local_client.py`) — wraps any
  OpenAI-compatible `/chat/completions` endpoint (Ollama, llama.cpp's server, vLLM).
  Reads `OPENAI_BASE_URL` / `OPENAI_API_KEY` from the environment, falling back to a local
  sentinel key when unset (most local runtimes don't validate the key at all).

Both are installed via the **non-default** `eval` dependency group — never pulled in by a
plain `uv sync`:

```bash
uv sync --group eval
```

This matches the repo's BYOK guardrails (`CLAUDE.md`): never a vendor-default key, nothing
proxied through Belay's own infrastructure, and no raw agent state ever leaves the box —
the model client only ever sees the running conversation this driver builds locally.

## macOS gotchas

- **Node 20 or 22 LTS.** Older/newer Node versions are untested against these servers.
- **Always pin the exact version** in `npx -y pkg@version` (as shown above). An unpinned
  `npx -y pkg` can resolve to whatever is cached in `~/.npm/_npx`, which silently drifts
  from what you tested against and breaks reproducibility of the mint.
- **Point the filesystem server's allowed-dir at a neutral working directory** — a repo
  clone under `~/dev/...` or a scratch directory you create for the mint — **not**
  `~/Desktop`, `~/Documents`, or `~/Downloads`. macOS's TCC (Transparency, Consent, and
  Control) framework will pop a permission prompt for those three folders the first time
  a spawned process touches them, and a prompt mid-mint stalls (or silently blocks) a
  batch run with no clear error in the trace.
- **`run_process` (the shell server's tool) uses `/bin/sh`, not your interactive shell.**
  If you normally work in zsh with aliases/functions/rc-file customizations, none of that
  is present — commands run through `run_process` see a plain POSIX `/bin/sh` environment.

## How this maps to RUNBOOK Step 1 (Capture)

`docs/planning/phase0-corpus-run/RUNBOOK.md`'s Step 1 ("Capture — Run Instances Through
the Proxy") describes, in pseudocode, exactly what this driver automates: start the
filesystem/shell MCP servers, route the agent's actions through
`python -m belay.proxy`, and write per-instance traces to `BELAY_TRACE_DIR`. Concretely,
this driver's `run_session` (`eval/minting_driver/session.py`) is the piece that owns one
instance's transport lifecycle (spawn, run `run_task`, always close in a `finally`, even
if `run_task` raises or hits `max_steps`), and `capture.py`'s `gated_env`/`proxy_command`
are the pure helpers that build the RUNBOOK's env vars and the proxy-wrapped server argv.

The traces this driver writes under `BELAY_TRACE_DIR` are exactly what RUNBOOK Step 2
(`belay phase0 run`) consumes:

```bash
belay phase0 run ./traces \
  --ledger runs/phase0.json \
  --corpus-dir corpus/local \
  --server -- <mcp-server-command>
```

**Note the split of responsibility:** this driver produces traces for the real
`belay phase0 run` CLI path above (RUNBOOK Step 2 as written). The single-instance smoke
test (next section) is a *different*, narrower path — it calls
`belay.phase0.runner.run_batch` directly with an explicit `manifest_dir_for`, bypassing
the CLI, because the smoke's job is only to prove one instance produces ≥1 verifiable
turn before any batch run is attempted. That smoke test is Task 5's deliverable, not
this task's.

## Running the single-instance smoke

The smoke is a real, live, spending run: real model API calls, real `npx`-spawned MCP
servers, real Seatbelt sandboxing. It is **never part of CI** — guarded by both a
`sys.platform == "darwin"` skip and an explicit env flag, and excluded from the default
`pytest` collection via a registered `manual` marker (`-m "not manual"` in the default
run). See `docs/planning/phase0-minting-driver/plan_20260721.md` (Task 5) for the guard
mechanics; the test itself lives at `tests/test_minting_driver_smoke.py`.

Manual command (macOS, Darwin + Seatbelt, Node 20/22, a model key):

```bash
uv sync --group eval

export ANTHROPIC_API_KEY=sk-ant-...        # or OPENAI_BASE_URL/OPENAI_API_KEY for a local model
export BELAY_EVAL_LIVE=1

uv run pytest tests/test_minting_driver_smoke.py -m manual -v
```

`BELAY_EVAL_LIVE=1` is the flag that turns the skip off; the `manual` marker keeps this
test out of the default `uv run pytest` collection (confirm with
`uv run pytest --collect-only | grep smoke` showing nothing when the flag is unset).
The smoke asserts that `belay.phase0.runner.run_batch` resolves at least one turn to a
verifiable (non-`UNVERIFIED`) disposition — `verified-clean` or `verified-flagged` — for
the curated instance in `eval/instances.md`. It is a documented manual procedure run by a
human before scaling to the ≥50-instance mint, not a merge gate.

## Honest scope

This driver — like Belay itself — only sees what crosses the MCP boundary. Everything the
model does through `write_file` / `edit_file` / `run_process` is captured and later
verifiable; nothing outside that boundary (e.g. a model's own internal reasoning, or any
action it could take through a tool this driver doesn't wire up) is observed at all.
