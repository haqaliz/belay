# Belay

Belay is an **agent harness**: it sits between an AI agent and the tools it calls, records
exactly what crossed, and is built so that a run can later be **replayed against real state**
and checked by re-execution rather than by asking a model whether it thinks it did well.

**What exists today is capture (C1) and the containment machinery (C2), and only those.**
Belay is a transparent stdio proxy in front of your MCP servers: it forwards bytes verbatim,
writes an append-only trace of every frame, and snapshots each turn's pre-state before the
call reaches the server. **It records. It does not judge.** There is no verdict, no
PASS/FAIL and no scoring in this codebase yet — that is C4/C5.

> ### The proxy does not sandbox your server yet
>
> Read this before assuming otherwise. The Seatbelt sandbox is **built, tested and real** —
> five escape vectors contained, network policy enforced — and it is reachable today
> through `belay sandbox check` and as a library. **It is not yet wired into the proxy's
> spawn path.** `python -m belay.proxy <server>` starts your server with a plain
> `subprocess.Popen`, unsandboxed, exactly as C1 did.
>
> `BELAY_SANDBOX_SCOPE` is, despite its name, the scope of the **snapshot** — it tells the
> turn gate which tree to capture. It does not contain the server. Wiring containment into
> the proxy is the next step, and until it lands, **nothing you run through the proxy is
> contained.**

Zero runtime dependencies. Stdlib only. It runs on your machine and sends nothing anywhere.
**macOS only** — see [below](#the-sandbox-is-macos-only-and-linux-is-unverified).

## Use it

Put `belay.proxy` in front of the server command you already run:

```bash
BELAY_TRACE_DIR=./traces python -m belay.proxy <server-command> [args...]
```

For an MCP client that launches servers for you (Claude Code, Cursor, …), wrap the command
in its config:

```jsonc
{
  "mcpServers": {
    "files": {
      "command": "python",
      "args": ["-m", "belay.proxy", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"],
      "env": { "BELAY_TRACE_DIR": "/path/to/traces" }
    }
  }
}
```

With `BELAY_TRACE_DIR` unset the proxy still forwards; it attaches no observer and writes no
file. The format is documented in [`docs/technical/TRACE_FORMAT.md`](docs/technical/TRACE_FORMAT.md).

### Snapshot each turn's pre-state

Set a scope and somewhere to put the snapshots:

```bash
BELAY_TRACE_DIR=./traces \
BELAY_SANDBOX_SCOPE=/path/to/workspace \
BELAY_SNAPSHOT_DIR=/path/to/snapshots \
python -m belay.proxy <server-command> [args...]
```

Each `tools/call` is held while the workspace is snapshotted, and the turn's frames carry a
handle naming that pre-state. `BELAY_SNAPSHOT_DIR` must be **outside** the scope, or every
turn would snapshot the previous turns' snapshots; the proxy refuses at startup rather than
recording a pre-state the agent never had. Setting a scope without a snapshot dir is
likewise refused.

This snapshots. **It does not sandbox** — see the note at the top.

### Check the sandbox before you trust it

```bash
belay sandbox check --scope /path/to/workspace -- <server-command> [args...]
# or, without installing the console script:
python -m belay.cli sandbox check --scope /path/to/workspace -- <server-command> [args...]
```

It answers two questions, and they are **not** equally answerable. *Does the substrate work
on this machine?* — it probes by using it: it **attempts a real escape under the profile and
confirms the kernel refuses it**, then takes a real snapshot and restores it. (Building a
profile proves nothing — that is string formatting. The failure worth catching is a
deprecated Seatbelt that runs your command and enforces nothing, and only an attempted
escape can see it.) *Is the scope too tight for this server?* — it runs the server briefly
and reports any denial with its exact path.

**The second answer is refutable only, never confirmable.** A server that ran cleanly for a
few seconds has proven that it started, not that its scope is sufficient. The command says
so in its own output, and it never widens a scope for you: it prints the path and the
decision stays yours.

## What the capture proves, and what it does not

**The neutrality claim is narrow, and it is the only one supported.**

> Against a deterministic fixture, the proxy is byte-transparent — proven by a differential
> test (`tests/test_differential.py`) that is itself proven to fail on a re-serialising proxy
> (`tests/test_teeth.py`).

That is the whole claim. It is **not** the claim that no real server is ever perturbed. A
byte-level differential is **unrunnable** against a real, nondeterministic server: two runs
of one differ for reasons that have nothing to do with the proxy — varying ids, timestamps,
progress tokens. Real-world runs are **corroborating evidence, not proof**, and this
distinction is not going to be quietly upgraded later.

Separately, a real `mcp` SDK client completes `initialize` → `tools/list` → `tools/call`
through the proxy (`tests/test_real_client.py`). That proves compatibility. It proves nothing
about byte-transparency: the fixture it drives is conforming, and a re-serialising proxy would
pass it unnoticed. The two tests answer different questions and neither substitutes for the
other.

## The sandbox is macOS only, and Linux is unverified

The sandbox is macOS **Seatbelt** (`sandbox-exec`), and the snapshot is APFS
**`clonefile`**. Everything Belay claims about containment was measured on macOS 26.5.2 /
arm64.

**Linux is entirely unverified — nothing has ever been run there.** Not "partially
supported", not "should work". Off macOS the sandbox **raises** rather than returning a
cheerful no-op, because a no-op that reported success would be Belay claiming a boundary
that does not exist on that platform. `ext4` has no reflink and GitHub's Linux runners are
ext4, so the `clonefile` approach has **no CI equivalent** there either. Linux/Docker is
C2's second slice.

What the sandbox does and does not enforce — reads are not scoped, per-host network rules
are inexpressible, denial records are *inferred* — is in
[`docs/technical/THREAT_MODEL.md`](docs/technical/THREAT_MODEL.md). Read it before trusting
the word "sandbox".

## Belay is content-neutral, not latency-neutral

The turn gate holds each `tools/call` while it snapshots the pre-state. **Measured: ~5ms
per turn** (4.9 / 5.0 / 5.1 / 5.5 / 4.9 ms) — **on a 400-file tree**, which is the size the
suite measures. The gate walks and clones the scope, so the cost scales with the tree: that
number is a measurement, not a constant, and a large workspace will pay more.

C1's neutrality claim was written to assert **bytes, never timing**, and this is what that
narrowness was for. The bytes the client sent are the bytes the server receives, gate or no
gate — but the turn waits. A snapshot must complete *before* the call reaches the server,
or it is not a pre-state; it is a race against whatever the server has already done.

## What a restore does and does not bring back

**Preserved, and measured** — content · mode including **setuid** · nanosecond mtime ·
symlink targets · **xattrs** (the mechanism a macOS resource fork is stored in) ·
`st_flags` · **hardlink structure** · empty directories.

Each of those is in the tree hash because a real copy mechanism was measured losing it:
`clonefile` silently drops hardlink identity, setuid (`0o4711` → `0o0711`) and directory
mtimes; `shutil.copytree` drops xattrs. A content-only hash calls every one of those copies
"byte-identical".

**Not restored, each for a stated reason:**

- **birthtime** — unsettable by anyone, including `tar`.
- **ctime** — unsettable.
- **atime** — self-invalidating: hashing reads every file, which changes it.
- **ownership**, when not running as root.
- **sockets, devices, FIFOs** — **detected and refused, never silently skipped.**

That last one is the contract, not an apology. Copy a FIFO and you restore an empty pipe,
losing the queued bytes with no record that anything was lost. Skip it and the restored
tree is missing an entry, and every verdict grounded on that pre-state is grounded on a
tree that never existed. Both report success. **Refusal is the only option that leaves a
reader able to tell what happened** — so the snapshot is refused, by name, with the cause
in the trace.

A `present` handle therefore declares its own gaps rather than implying a fidelity no
snapshot has.

## Coverage: Belay sees what crosses the MCP boundary, and nothing else

**An agent's built-in tools do not traverse MCP and are invisible to Belay.** Claude Code's
`Bash` and `Edit` are in-process; they never reach a stdio transport, so no proxy on that
transport can see them. An agent can read a file, run a command, or rewrite your working tree
without a single byte crossing Belay.

This is a real limit, not a temporary gap in the docs. Read a trace as *"here is what went
over MCP"*, never as *"here is what the agent did"*. The `connection_window` records bound
the period Belay was listening at all, which is the honest denominator for that question.

**The sandbox's limit and the MCP boundary's limit are the same limit.** Belay contains the
processes it spawns — the MCP servers it proxies. `Bash` and `Edit` are never spawned by
our proxy and are therefore **never in our sandbox**. Adding the sandbox did not widen what
Belay can see by one byte; it changed what happens to what Belay could already see.

## A trace is as sensitive as the agent's most sensitive tool argument

Capture is lossless by design, so everything crossing the boundary is recorded verbatim:
**API keys, tokens, file contents, customer data**. It lands in the trace in fully
recoverable form.

Trace files are created owner-only (`0600`). Beyond that there is deliberately **no redaction
and no secret scanning**. Both are opinions, capture is opinion-free, and a redacted trace
cannot be replayed — which would defeat the only reason the trace exists. **Treat a trace
file as the credential it may contain.**

## The protocol is moving

Belay is developed against MCP revision **`2025-11-25`**.

The **`2026-07-28`** revision removes the `initialize`/`initialized` handshake, protocol-level
sessions and `Mcp-Session-Id`, and server-initiated requests. Belay forwards bytes and does
not model the conversation, so the proxy is not expected to be affected — **but Belay has not
been tested against that revision and does not claim support for it.** No such server exists
to test against yet. When one does, the claim can be made on evidence.

The trace format records what the wire carried rather than what a revision assumes it meant;
where that mattered, the reasoning is in [`docs/technical/TRACE_FORMAT.md`](docs/technical/TRACE_FORMAT.md).

## Develop

```bash
uv run pytest            # full suite
uv run pytest -m sdk     # the tests driving a real MCP SDK client
```

`mcp` is a **dev-only, test-only** dependency and must never appear in `src/belay/`.
`tests/test_import_guard.py` enforces that statically, along with the zero-runtime-dependency
rule and the rule that the forwarding path cannot import `json`.
