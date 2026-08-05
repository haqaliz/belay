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

## Where the banked eval data lives

**All captures, corpus cases, ledgers and the pinned MCP servers live OUTSIDE this repo**, at
`~/dev/at/holder/belay/`. They are gitignored by nature — raw agent run-state is never committed —
and they used to sit inside git worktrees, where `git worktree remove` would have destroyed them.
Moved out on 2026-08-06.

| Path | What |
|---|---|
| `~/dev/at/holder/belay/corpus-local/` | the 7 hand-labeled cases behind `precision 0.00` |
| `~/dev/at/holder/belay/mint/` | `s1`, `s1b`, `s1p`, `s2`, `s3`, plus `live-smoke-claude-cli` (the v0.13.0 `pytest-7432` smoke) |
| `~/dev/at/holder/belay/runs/` | the published ledgers |
| `~/dev/at/holder/belay/servers/` | the pinned MCP servers every trace names by absolute path |

**Why outside the repo and not just gitignored inside it.** `git clean -xfd` deletes gitignored
files. Inside the repo, one routine `git clean` would destroy 4.8 GB of unregenerable evidence.
Outside, the blast radius is three symlinks.

### ⚠️ The symlinks are load-bearing — replay does not work without them

The traces record the **original worktree absolute paths**, and those bytes are the primary record.
Three symlinks make those paths resolve to the new home:

```sh
for w in feat-verdict-coverage-status feat-phase0-mint-execution feat-subscription-model-client; do
  mkdir -p ".claude/worktrees/$w"
  ln -sfn ~/dev/at/holder/belay ".claude/worktrees/$w/eval"
done
```

**DO NOT "fix" the recorded paths by rewriting the manifests.** This was tried on 2026-08-06 and
**measurably breaks replay**: rewriting `s1p`'s manifests to point at the new location took it from
**0/11 UNVERIFIED to 7/11**, because the manifest's `source_root` must agree with what the trace
recorded for relocation to match. An over-broad revert then broke the smoke capture the same way
(5/5 UNVERIFIED) until its manifests were restored to their true original prefix. The symlink is
the correct mechanism precisely because it changes no recorded byte.

### Verified working, after the source worktrees were deleted

```
belay corpus run ~/dev/at/holder/belay/corpus-local          -> 7/7 MATCH, 0 REGRESSION, 0 SKIP
belay phase0 run  .../mint/s1p/batch                         -> VERIFIED_CLEAN, 0/11 UNVERIFIED
belay phase0 run  .../mint/live-smoke-claude-cli/batch       -> VERIFIED_CLEAN, 0/5 UNVERIFIED,
                                                                exposure 0 file-comparison(s)
```

Usage:

```sh
belay corpus run ~/dev/at/holder/belay/corpus-local

belay phase0 run ~/dev/at/holder/belay/mint/<stage>/batch --ledger out.json --no-ingest \
  --server node ~/dev/at/holder/belay/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js '{workspace}'

export BELAY_EVAL_SERVER_ROOT=~/dev/at/holder/belay/servers   # driver + live smokes
```

One deliberate exception: the **corpus cases' `server_command`** was re-pointed to
`~/dev/at/holder/belay/servers`, so the corpus needs no symlink at all. That is safe because
`server_command` is machine-binding metadata rather than recorded behaviour, and it retires the
standing caveat that *"the corpus is machine-bound through the SERVER"*. `expected`, `human_label`
and `root_cause` were untouched.

### Off-machine backup

A compressed archive is attached to the **`v0.13.0` GitHub Release** as
`belay-eval-data-v0.13.0.tar.zst` — **226 MB**, down from 4.8 GB (**21.7x**; the snapshots are
near-identical copies of the same source tree per turn, which `zstd --long=27` collapses).

```sh
gh release download v0.13.0 -p 'belay-eval-data-*.tar.zst'
mkdir -p ~/dev/at/holder && tar -I 'zstd -d --long=27' -xf belay-eval-data-v0.13.0.tar.zst -C ~/dev/at/holder
# then recreate the three symlinks above, or nothing will replay
```

**This is durability, not portability.** The archive restores *your* evidence after disk loss. It
does **not** let anyone else verify these claims: the paths are absolute and user-specific, and the
substrate is macOS/Seatbelt-only, so `belay corpus run` on another box reports `SKIP`. Making the
evidence portable is real, separate work — the machine-binding through absolute paths would have to
go first, and as recorded above, naively rewriting those paths is exactly what breaks replay.

## The MCP servers (pinned, pre-installed)

Two servers, each pinned to an exact version and **pre-installed** into a gitignored
`eval/servers/`, then launched by **absolute *entrypoint* path**: the argv is
`["node", "<abs .../dist/index.js>", ...]` (`eval/minting_driver/servers.py`) — the
entrypoint is absolute, `node` itself is still a plain `$PATH` lookup. That is enough for
the finding below (a resolved entrypoint needs no registry and no cache write), but it is
worth stating precisely, because this same argv is also the replay `--server` command:
resolving `node` absolutely would change replay inputs and is deliberately a separate
question, not something to "fix" in passing.

> ### ⚠️ `npx -y` does NOT work behind the gated proxy — measured, not theorised
>
> This was the documented launch method until 2026-07-21, when the first live smoke run
> proved it cannot work. Recording the finding here so nobody re-derives it:
>
> A gated run (`BELAY_SANDBOX_SCOPE` + `BELAY_SNAPSHOT_DIR` set) spawns the server inside
> Seatbelt, which **denies all network by default** (`src/belay/sandbox/launch.py:73-98` —
> a deliberate, argued default, not an oversight) and confines writes to the workspace
> scope. `npx` needs both: it contacts the registry and writes `~/.npm/_npx` and
> `~/.npm/_logs`. Denied both, it **hangs** rather than failing loudly — the proxy emits
> nothing and the client times out on `initialize`.
>
> Worse, npm misattributes the write denial to an unrelated known bug and prints
> *"Your cache folder contains root-owned files"*. **That message is a red herring** —
> `find ~/.npm -user root` returns nothing. Do not chase it.
>
> The trace-only path (`BELAY_TRACE_DIR` alone, no sandbox) works fine with `npx`, which is
> why this went unnoticed: it is only the *contained* run that breaks, and the contained
> run is the only one that produces verifiable turns.
>
> **The sandbox is not the bug.** Deny-all network is exactly what makes a minted turn
> worth verifying. The eval harness was wrong to depend on a package manager at spawn time.
> Pre-installing also makes the mint fully offline, which strengthens what the published
> number can claim.

Versions resolved by `npm view <pkg> version` on 2026-07-21 (re-run before minting in case
newer versions have shipped since):

```bash
npm view @modelcontextprotocol/server-filesystem version   # 2026.7.10
npm view mcp-server-commands version                       # 0.8.2
```

### Install once, before any mint

Run **outside** the sandbox, from the repo root:

```bash
npm install --prefix eval/servers \
  @modelcontextprotocol/server-filesystem@2026.7.10 mcp-server-commands@0.8.2
```

(The `--prefix` form is the one `eval/minting_driver/servers.py` generates in its
`MissingServerError`, so this is byte-for-byte the command the error you would actually
see tells you to run. Its earlier `cd eval/servers && npm install` form was equivalent in
effect but not in text, which is worse than useless in an error-recovery path.)

`eval/servers/` is gitignored — third-party JS, pinned but never vendored into a repo whose
Python core has zero runtime dependencies. `eval/minting_driver/servers.py` resolves the
entrypoints and raises a named error naming this exact command if they are absent, so a
missing install fails loudly at startup rather than as a mysterious timeout.

Override the install root with `BELAY_EVAL_SERVER_ROOT` if you keep servers elsewhere.

### filesystem — `@modelcontextprotocol/server-filesystem@2026.7.10`

```bash
node eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js <abs-allowed-dir>
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
node eval/servers/node_modules/mcp-server-commands/build/index.js
```

(Entrypoint is `build/index.js`, **not** `dist/` — read from the package's own
`bin` field at install time, not guessed.)

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

Three thin `Model` implementations (`eval/minting_driver/model.py`'s `Protocol`), none
imported by the driver core (`loop.py`, `session.py`) and none exercised in CI — the two
SDK-backed ones lazy-import their SDK *inside* `__init__`, so importing the module never
requires the SDK to be installed (`tests/test_minting_driver_clients_import.py` asserts
this by checking `sys.modules`).

- **`AnthropicModel`** (`eval/minting_driver/clients/anthropic_client.py`) — wraps the
  Anthropic Messages API with tool-use. Reads `ANTHROPIC_API_KEY` from the environment
  (or takes `api_key=`/an injected `client=` directly).
- **`LocalOpenAICompatModel`** (`eval/minting_driver/clients/local_client.py`) — wraps any
  OpenAI-compatible `/chat/completions` endpoint (Ollama, llama.cpp's server, vLLM).
  Reads `OPENAI_BASE_URL` / `OPENAI_API_KEY` from the environment, falling back to a local
  sentinel key when unset (most local runtimes don't validate the key at all).
- **`ClaudeCliModel`** (`eval/minting_driver/clients/claude_cli_client.py`) — runs the
  `claude` CLI as a subprocess on the operator's **own subscription**, so a mint needs no
  metered key at all. Imports **no SDK whatsoever** (its boundary is a process, not a
  client object) and reads **no credential**: see "The subscription path" under "Running a
  mint" for the setup and, more importantly, for its stated limits.

The first two are installed via the **non-default** `eval` dependency group — never pulled
in by a plain `uv sync`:

```bash
uv sync --group eval
```

`--provider claude-cli` needs neither group: it depends on the `claude` CLI being on
`PATH`, not on any Python package.

This matches the repo's BYOK guardrails (`CLAUDE.md`): never a vendor-default key, nothing
proxied through Belay's own infrastructure, and no raw agent state ever leaves the box —
the model client only ever sees the running conversation this driver builds locally.

## macOS gotchas

- **Node 20 or 22 LTS.** Older/newer Node versions are untested against these servers.
- **Always pin the exact version** in the `npm install` above. An unpinned install resolves
  to whatever is newest at install time, which silently drifts from what you tested against
  and breaks reproducibility of the mint. Pinning is why the version appears in the install
  command and in `eval/minting_driver/servers.py`.
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
belay phase0 run <root>/batch \
  --ledger runs/phase0.json \
  --corpus-dir corpus/local \
  --server node <abs-entrypoint> '{workspace}'
```

**No `--` separator after `--server`** — it is `nargs=REMAINDER`, so everything after it
*is* the server command and a separator would be handed to `node` as an argument. And
`'{workspace}'` (quoted, as one whole argument) is what makes ONE static command correct
for a batch captured from many workspaces: replay substitutes each trace's own recorded
`source_root`. The mint prints this exact line when it finishes — see "Running a mint".

**Note the split of responsibility:** this driver produces traces for the real
`belay phase0 run` CLI path above (RUNBOOK Step 2 as written). The single-instance smoke
test (next section) is a *different*, narrower path — it calls
`belay.phase0.runner.run_batch` directly with an explicit `manifest_dir_for`, bypassing
the CLI, because the smoke's job is only to prove one instance produces ≥1 verifiable
turn before any batch run is attempted. That smoke test is Task 5's deliverable, not
this task's.

## Running a mint

The committed mint commands. **Never `belay mint ...`** — `eval/` is not a product
surface, so the entry point is a plain module invocation:

```bash
# one instance by id (the Stage-1 tool)
uv run python -m eval.minting_driver one pallets__flask-4045 \
  --root eval/mint/stage1 --registry eval/instances/stage1.json \
  --model gemini-3.1-pro-preview

# the whole selection (Stage 2 / Stage 3)
uv run python -m eval.minting_driver batch \
  --root eval/mint/stage3 --registry eval/instances/selected.json \
  --model gemini-3.1-pro-preview
```

Both take the same flags: `--root` (**required, no default**), `--model` (**required, no
default**), `--registry`, `--clones-dir`, `--checkpoint` (default
`<root>/checkpoint.json`), `--provider` (`openai-compat` | `anthropic` | `claude-cli`,
default `openai-compat` — see "The subscription path" for the third), `--request-timeout`
(default `120.0`), `--max-steps`, `--max-attempts` (default `3`), `--retry-base-delay`
(default `1.0`), `--server-root`, and `--verify`.
`python -m eval.minting_driver one --help` is authoritative.

**`--model` is required and has no default, for the same reason `--root` has none.** The
default used to be `gemini-flash-latest`, and Stage 2 measured what that buys
(`docs/planning/phase0-mint-execution/mint-execution/STAGE2_FINDINGS.md:25-39`): two
flash-class models hit the step cap on `pallets__flask-4045` doing **only reads and
searches**, editing nothing — and an agent that never mutates produces turns that all
verify clean, so the mint publishes a **0% violation rate that means "the agent did
nothing"**. That is worse than `INSTRUMENT SUSPECT`, because it *looks like a result* and
the pre-registered gate would read it as a PIVOT on a premise that was never tested.
`gemini-3.1-pro-preview` edited on the first try in 11 turns: **pro-class is required, and
the published number must name the model.** Forgetting the flag is argparse's own exit 2,
before a workspace is prepped or a token is spent.

`--max-attempts` counts attempts per model call **including the first**, so `1` means
"no retries"; `--retry-base-delay` is the first backoff, doubling each time (`0` retries
immediately). Both tune the **transient** ladder only — a provider quota cap is never
retried at any setting. See the next section for why.

### Required environment

```bash
uv sync --group eval                      # anthropic + openai (non-default group)
export OPENAI_BASE_URL=...                # the OpenAI-compatible endpoint
export OPENAI_API_KEY=...                 # required and never substituted (see below)
unset ANTHROPIC_API_KEY                   # unless you pass --provider anthropic
```

Three deliberate properties, each of which exists because its absence produces an **empty
mint** — which `belay phase0 run` reports as `INSTRUMENT SUSPECT`, i.e. a *fake* PIVOT
caused by operator setup rather than by the agents being measured:

- **The provider is an argument, never an environment sniff.** A stray `ANTHROPIC_API_KEY`
  cannot change which model mints; if it could, the published number would name the wrong
  model. Environment variables supply credentials only.
- **`OPENAI_API_KEY` is required, not defaulted.** `LocalOpenAICompatModel` substitutes a
  local sentinel key when it is unset — right for Ollama, and a 401 on the first call of
  *every* instance against a hosted endpoint. The entry point refuses to start instead.
- **The server install is preflighted once, before anything is prepped or spent.** A
  missing `eval/servers/` exits 2 with the `npm install --prefix ...` command on stderr,
  rather than recording ~65 identical contained failures an hour after you walked away.

`BELAY_EVAL_MODEL` is **not** an entry-point knob — it is read only by
`tests/test_minting_driver_smoke.py`. Use `--model`.

### The subscription path (`--provider claude-cli`)

A third provider that mints on the operator's **own Claude subscription** instead of a
metered API key. Everything the other two paths guarantee still holds — the traces, the
gated proxy, the bridge, the verdicts are all unchanged — because this is a `Model`
implementation behind the same seam and **nothing in `loop.py` or `batch.py` was touched to
add it** (asserted by a pinned-hash test in `tests/test_minting_driver_claude_cli.py`).

```bash
# setup: the CLI on PATH, logged in ONCE, interactively, as yourself
claude --version                      # must resolve; the client spawns `claude`
claude                                # log in if you have not: OAuth / keychain

# then mint, with no key exported and none needed
uv run python -m eval.minting_driver batch \
  --root eval/mint/stage4 --registry eval/instances/selected.json \
  --provider claude-cli --model claude-opus-5
```

`--model` is required here exactly as elsewhere, and it must be a **full id**
(`claude-opus-5`), never an alias (`opus`): an alias resolves to whatever is newest at call
time, so two mints reporting the same string would not have run the same model. The
client's default constant is a full id for the same reason.

**No API key is read or passed.** `resolve_credentials("claude-cli")` returns an empty
mapping and touches no environment variable at all (a test substitutes a recording mapping
for `os.environ` to prove it), and the client goes further: it **removes**
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` from the child's
environment, by *absence* rather than by setting them empty — an empty string still occupies
its precedence slot. This matters because a leaked key produces a run that **succeeds and
looks identical** while silently billing per token; there is no output you could inspect
afterwards to tell the two apart. You do **not** need to `unset` anything by hand.

**`--tools ""` and `--strict-mcp-config` are what keep the capture complete.** The oracle is
granted no built-in tool and inherits none of *your* MCP servers; the MCP tool schemas
travel as **data inside the prompt**, so the model can propose a call it cannot make, and
every edit is executed by the driver through the recorded proxy (R6). Either flag missing is
a path around the boundary — an inherited filesystem server would let the oracle edit files
without the trace ever seeing them, and the mint would be missing exactly the turns that
matter. Both are asserted on the constructed argv. R7 ("never more than one `tools/call` in
flight") stays `loop.py`'s control flow; the client's part is that it returns **at most one**
decision per call, and warns-and-drops rather than queueing if a reply states more.

**`--bare` must never be added.** Its own help says *"OAuth and keychain are never read"*:
it reads like the isolation flag and would break authentication outright. Asserted absent,
deliberately — the failure it prevents is a plausible future "improvement".

**`--max-turns` is a no-op, so the bound is elsewhere.** Probed 2026-08-05: absent from
`--help`, accepted silently, and `--max-turns 1` still produced `num_turns: 2`. The mint's
actual bounds are the harness's `--max-steps` (default `12`) **plus** the client-owned
subprocess timeout (`DEFAULT_TIMEOUT_SECONDS = 600.0` per invocation). A wedged call raises
a `TimeoutError` subclass, which the shared classifier calls `transient` and the retry
breaker retries; a missing `claude` binary classifies `terminal` and costs one instance, not
the queue.

Other stated limits, so nothing here is discovered the hard way:

- **`--max-tokens` is refused, not ignored.** The CLI has no reply-length flag, so
  `make_model_factory(..., provider="claude-cli", max_tokens=...)` is a named
  `MintConfigError` rather than a cap that was silently never applied.
- **`total_cost_usd` is never read.** The envelope carries it; nothing stores or reports it.
  Under a subscription there is no per-token price, and a currency figure would be
  fabricated precision presented as a measurement (`prd.md` D-1).
- **The undocumented CLI surface can change under us** (`prd.md` R-7). Every flag the client
  depends on is asserted on the constructed argv, so a *removed* flag surfaces as a failing
  test — but a flag that is still accepted while **meaning something new** would not. That
  residual is named, not fixed.
- **What a subscription usage limit looks like is still unknown.** Nothing pattern-matches
  one, so such a failure reads `terminal` (safe: one instance, queue intact) unless the CLI's
  text happens to carry a recognisable rate-limit shape. The first real limit encountered is
  a finding to write down.

> ⚠️ **The Terms-of-Service position is a stated assumption, not a settled fact**
> (`docs/planning/subscription-model-client/prd.md` R-5). Anthropic's docs bar third-party
> developers from *offering* claude.ai login for their products, and are **silent** on
> running one's own eval on one's own subscription and on unattended batch automation. The
> owner re-affirmed the assumption on 2026-08-05 with the live smoke explicitly in view;
> **the re-affirmation does not convert it into a settled fact**, and it belongs in the
> limitations section of any published write-up that uses a number minted this way.

### `eval/.mint_key` and `eval/resume_mint.sh` — an operator convention, not a feature

Both names appear in `.gitignore` (commit `3c01984`) and **nothing in this repository
reads either one**. They are a local operator convention, written down here so the next
person does not have to reverse-engineer two ignore lines:

- **`eval/.mint_key`** — a gitignored local file holding a BYOK API key. No code opens it.
  The entry point reads `OPENAI_API_KEY` / `OPENAI_BASE_URL` (and the Anthropic SDK reads
  `ANTHROPIC_API_KEY`) from the **environment**, so the usual pattern is to export from
  the file rather than to point anything at it:

  ```bash
  export OPENAI_API_KEY="$(cat eval/.mint_key)"
  ```

  It is a live credential: **never commit it**, never paste it into a findings document,
  and keep the `.gitignore` entry. Deleting the file costs nothing — re-create it, or just
  export the key directly.

- **`eval/resume_mint.sh`** — a per-run script an operator generates to re-invoke a batch
  after a stop. It is gitignored and the copy that existed lived in another worktree, so
  this is documentation, **not** a code fix: there is nothing here to change.

  > ⚠️ **If you regenerate it, do not have it `rm -rf` anything.** The version used on
  > 2026-07-24 deleted every non-`captured` instance directory before each attempt, which
  > **destroyed that run's failure diagnostics** — we still cannot say why it stopped.
  > It is also unnecessary now: the quota circuit breaker records `no_observation`, which
  > `Checkpoint.is_done` treats as *not* done, so re-running the same `--root` re-drives
  > exactly those instances and skips every `captured` one (see "`no_observation`, and how
  > a resume re-arms it" below). A resume is `--root` plus patience, not a delete pass.

### Re-minting an instance

Use a **fresh `--root`**. An instance already recorded `captured` or `failed` in
`<root>/checkpoint.json` is skipped (that is the resume, and it is what stops a crash at
#37 from re-spending on 1..36), and its bridge destination in `<root>/batch` already
exists. An instance recorded `no_observation` is *not* skipped — see "`no_observation`,
and how a resume re-arms it" below; it never produced an observation, so re-driving it is
not a re-roll of anything. There is deliberately
no `--force` and no way to forget a recorded disposition: both are ways to double-spend by
accident and to lose the record of what already ran. A directory you name is a better unit
of "this is a new attempt".

### The quota circuit breaker

> #### ⚠️ A daily cap destroyed 56 instances of denominator in 3m48s — measured, not theorised
>
> On 2026-07-24 a Stage-3 mint hit Google's 250-requests-per-day cap on instance 3 of 68.
> **Nothing crashed** — that is the whole point. `run_mint`'s single bare
> `except Exception` recorded the 429 as `failed` and moved on to the next instance, which
> hit the same wall, and so on down the queue. Because `checkpoint.is_done` counts
> `failed` as *done*, a resume would have skipped all 56 forever. The provider's own
> `retryDelay` was **39043s (≈10h50m)**: no bounded backoff could ever have reached it.
> What was lost was not a retry, it was the **queue** — and a shrunken denominator is the
> R6 false-zero failure mode, one layer up.

`eval/minting_driver/resilience.py` answers one question about a provider exception —
*"is waiting going to help, and for how long?"* — and the mint acts on the answer:

| kind | what it looks like | what the mint does |
|---|---|---|
| `quota` | a daily/period cap (429 + `RESOURCE_EXHAUSTED`, or a retry hint > 600s) | records `no_observation` and **stops the batch** |
| `transient` | a rate-limit or transport blip (other 429s, 408/409/425/5xx, timeouts) | bounded retry with exponential backoff, then `no_observation` |
| `terminal` | everything else | records `failed` and continues — today's behavior, unchanged |

**An unrecognised error classifies `terminal`, never `transient`.** Retrying an error we
do not understand is how the queue got burned; the next unknown shape will be a
subscription-plan cap nobody has seen yet. A `terminal` verdict costs one instance and
keeps the batch alive.

The retry wraps `Model.propose_next` and **nothing else** — it is installed at the
`ModelFactory` boundary (`entrypoint.make_model_factory`), so it is structurally incapable
of re-sending a `tools/call`. Re-sending one would duplicate a real side effect against
the workspace and corrupt the very capture the mint exists to produce; `loop.py`'s "no
retries" claim stays literally true. The wrapper is built **inside** the factory, one per
instance, for the same reason the model client is: a hoisted one would leak conversation
state *and* accumulate the retry count across instances.

### `no_observation`, and how a resume re-arms it

The checkpoint has a third status: **`no_observation`** — the instance was never actually
driven. A quota cap rejected the request outright, or a transient blip outlived its
retries: no session ran, no trace exists, nothing was observed. `Checkpoint.is_done` is
`True` for `captured` and `failed` and **`False` for `no_observation`**, so re-running the
same `--root` re-drives exactly those instances and nothing else.

That asymmetry **is** the re-arm mechanism. There is deliberately no flag and no
`--force`, because the honest rule and the re-arm rule are the same rule: an instance that
produced an observation is never re-rolled, and an instance that produced none was never
measured in the first place. Each entry also carries an append-only `history`, so a
superseded disposition is recorded rather than erased.

When a quota stop happens, the instances *after* the stopping one stay **absent** from the
checkpoint entirely — not recorded as anything. Absent is honest: they are visibly
missing, and still eligible. Re-run the same `--root` once the cap resets.

### What a mint cost: per-instance accounting

Nothing recorded what a mint cost — anywhere. The clients read the response's `.choices` /
`.content` and let `.usage` fall out of scope with the response object; `batch.py` built
the model **inline at the `run_session` call and never bound it**, so the object that knew
what an instance had spent was unreachable the moment the call returned. Stage 2 therefore
produced one wall-clock anecdote (~15 min for one sympy instance) and **no spend figure at
all**, so no stop-loss could be set and the write-up could not state what the number cost
to produce.

Every recorded disposition now carries an `accounting` record:

| field | meaning |
|---|---|
| `wall_clock_seconds` | **prep through bridge** — the instance's whole cost, not the model's |
| `model_requests` | attempts that reached the provider, **retries included** |
| `retry_count` | the transient ladder's own count (`RetryingModel`) |
| `input_tokens` / `output_tokens` | where the provider reports usage — **omitted where it does not** |
| `model` / `provider` | per-instance provenance: a mint may span two models |

Three rules, and each exists because its absence would put a fabricated number in the
write-up:

- **Absent is not zero.** A provider that reports no token usage leaves the key OUT; it is
  never written as `0`. An unmeasured quantity rendered as a measured one is the same
  dishonesty as rendering `UNVERIFIED` as `PASS`, and any later total would silently
  absorb the fake zero. The summary states how many instances reported usage and how many
  were `ABSENT`.
- **Accounting is recorded on `captured`, `failed` *and* `no_observation`.** A
  quota-stopped instance still spent a request — the 2026-07-24 run spent one on each of
  56 instances and observed nothing — so a stop-loss blind to failed attempts under-counts
  by exactly the failures it exists to notice. On a re-arm the superseded attempt's
  accounting moves into `history` rather than being erased.
- **No dollar figure is computed or stored, anywhere, at any flag.** Under a subscription
  there is no per-token price, so a currency amount would be invented precision presented
  as a measurement. Requests + tokens + wall-clock only; if a metered key is ever used,
  price is applied at *report* time from a stated rate and never baked into the ledger.
  There are tests asserting no currency symbol or money-shaped field reaches the ledger or
  the summary.

The clock is **injected and lives in `batch.py`** (`run_mint(..., clock=time.monotonic)`),
never in `entrypoint.py`, whose design rule is "no clock, no randomness" — asserted
structurally. It is `time.monotonic` rather than `time.time` so an NTP step during a
15-minute instance cannot produce a negative duration.

### Re-arming a ledger written before the breaker

`eval/scripts/rearm_checkpoint.py` is the one-off migration for a checkpoint written
*before* `no_observation` existed — concretely, the 56 stranded entries of the 2026-07-24
Stage-3 run. It rewrites a `failed` entry to `no_observation` **if and only if** its
recorded `reason` classifies `quota` under the same `classify_error` the live breaker uses
(which is why that classifier is duck-typed: here there is no exception object, only the
text `str(exc)` left in the ledger).

```bash
# always look first — this rewrites the only record of a live, unrepeatable mint
uv run python -m eval.scripts.rearm_checkpoint \
  --checkpoint eval/mint/s3/checkpoint.json --dry-run

# then, without --dry-run, to write it
uv run python -m eval.scripts.rearm_checkpoint --checkpoint eval/mint/s3/checkpoint.json
```

```
rearm: DRY RUN — nothing will be written to eval/mint/s3/checkpoint.json
  68 entr(ies) recorded
  56 to re-arm (failed -> no_observation, quota-classified)
  12 untouched
  re-arm control__flask-read-only: Error code: 429 - [{'error': {'code': 429, ...
```

- **`--checkpoint` is required, with no default.** A default is how this gets pointed at
  the wrong ledger.
- **`captured` is never touched, whatever its reason says.** The guard is the *status*,
  never the classifier. Re-arming a captured instance would double-spend and replace a
  recorded result with a second roll of the same dice — the re-roll `eval/README.md` bans
  `--force` for and `mint-execution/spec.md` calls "precisely the dishonesty this project
  exists to prevent".
- **A genuine failure stays `failed`.** It ran, it errored, an observation exists.
- **The original reason moves to `history`**, so the evidence for why each instance became
  eligible again survives in the file.
- **Fail-closed and idempotent:** a corrupt or absent ledger exits 2 with one line, and a
  second run rewrites nothing.

### Scoring the mint

Every completed mint prints where its artifacts landed, what it cost, and the exact
`belay phase0 run` command that turns the captures into the number:

```
minted 1 captured, 0 failed, 0 no_observation, 0 never-driven of 1 instance(s)
  batch dir:  eval/mint/stage1/batch
  checkpoint: eval/mint/stage1/checkpoint.json
  accounting: 1 of 1 instance(s) recorded
    wall-clock:     182.5s
    model requests: 7 (1 retry)
    tokens:         41200 in / 3100 out, over 1 of 1 recorded instance(s)
    models:         gemini-3.1-pro-preview (1)

verify with:
  belay phase0 run eval/mint/stage1/batch --ledger runs/phase0.json \
    --corpus-dir corpus/local --server node <abs-entrypoint> '{workspace}'
```

**All four buckets are always on the summary line**, and a batch that stopped early says
so. Summarising only `captured`/`failed` was complete before the quota circuit breaker and
is not now: a mint that stopped at instance 3 of 68 read as "2 captured, 0 failed of 68",
with the `no_observation` instance and the 65 never-driven ones present in the counts and
absent from the summary. A stopped batch prints, above the accounting:

```
  STOPPED EARLY: 65 of 68 instance(s) were never driven — absent from the checkpoint, and
  therefore still eligible; re-run the same --root
```

`--verify` runs that same command in process immediately after minting. **The mint itself
is a live observation and is not reproducible**; the ledger → report path is, and this
printed line is what makes that second half true.

## Running the single-instance smoke

The smoke is a real, live, spending run: real model API calls, real pre-installed MCP
servers spawned by `node`, real Seatbelt sandboxing. It **skips** with an actionable message
if `eval/servers/` has not been installed (see "Install once" above). It is **never part of CI** — guarded by both a
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
