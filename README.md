# Belay

Belay is an **agent harness**: it sits between an AI agent and the tools it calls, records
exactly what crossed, and is built so that a run can later be **replayed against real state**
and checked by re-execution rather than by asking a model whether it thinks it did well.

**What exists today is the capture layer (C1), and only that.** Belay is a transparent stdio
proxy in front of your MCP servers. It forwards bytes verbatim and writes an append-only
trace of every frame. **It records. It does not judge.** There is no verdict, no PASS/FAIL,
no scoring, and no policy enforcement in this codebase yet.

Zero runtime dependencies. Stdlib only. It runs on your machine and sends nothing anywhere.

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

## Coverage: Belay sees what crosses the MCP boundary, and nothing else

**An agent's built-in tools do not traverse MCP and are invisible to Belay.** Claude Code's
`Bash` and `Edit` are in-process; they never reach a stdio transport, so no proxy on that
transport can see them. An agent can read a file, run a command, or rewrite your working tree
without a single byte crossing Belay.

This is a real limit, not a temporary gap in the docs. Read a trace as *"here is what went
over MCP"*, never as *"here is what the agent did"*. The `connection_window` records bound
the period Belay was listening at all, which is the honest denominator for that question.

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
uv run pytest -m sdk     # the real-SDK client test
```

`mcp` is a **dev-only, test-only** dependency and must never appear in `src/belay/`.
`tests/test_import_guard.py` enforces that statically, along with the zero-runtime-dependency
rule and the rule that the forwarding path cannot import `json`.
