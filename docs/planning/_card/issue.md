# Card: C1 — MCP proxy trace capture

## Source

**No GitHub issue.** `gh` is authenticated and reachable; `gh issue list` and `gh pr list`
both return empty (the tracker has never been used). The `id` for this unit of work is the
slug `mcp-proxy-capture`, not an issue number.

**Provenance of the brief below:** it was authored by Claude during a `belay-next` session
as the recommended handoff, and invoked verbatim by the user as `bbf feat mcp-proxy-capture`.
It is therefore a *derived* brief grounded in the repo's own roadmap files — not a
user-authored issue and not an independent requirement source. Every claim in it traces to
`docs/technical/CAPABILITY_ROADMAP.md` (C1) or `docs/ROADMAP.md`. Where the brief and those
files disagree, **the files win.**

- Branch: `feat/mcp-proxy-capture/aliz`
- Worktree: `.claude/worktrees/feat-mcp-proxy-capture`
- Base: `origin/master` @ 25f31f9

## Brief

Build C1 — MCP proxy trace capture, the first commit of the Belay engine (see
`docs/technical/CAPABILITY_ROADMAP.md`, C1). A transparent JSON-RPC proxy: the agent
points at Belay, Belay points at the real MCP servers, and it is behavior-neutral.
Capture per `tools/call`: server identity, tool name, args, result, `isError`, timing,
ordering, and the tool's declared annotations (`readOnlyHint`, `destructiveHint`,
`idempotentHint`, `openWorldHint`) snapshotted from `tools/list` at session start.
Content-address args, result, and state handles so traces are tamper-evident and
comparable across runs. Append-only, self-describing trace format with a versioned
schema on day 1 — it is the interchange format for the whole engine, and C2's
snapshot/restore needs will shape it, so design the pre/post state handle slot now
even though C2 fills it. Capture is lossless and opinion-free; C1 makes no judgements.

Repo is test-first: write these as failing tests before any code. (1) A fake MCP
server plus a scripted client round-trips through the proxy and observes
byte-identical responses versus a direct connection. (2) Every `tools/call` appears in
the trace with args, result, and annotations, and hashes are stable across two
identical runs. (3) A malformed / non-conforming server yields a recorded, honest
error, never a dropped turn. (4) A trace written by version N is readable by version
N (schema round-trip). All tests deterministic, no network, runs in CI.

Caveat to design around, not discover later: risk R6 (`docs/ROADMAP.md`) — an agent's
built-in Bash/Edit do not traverse MCP, so fixtures and the eventual corpus must use
off-the-shelf MCP filesystem + shell servers. C1 cannot retire R6, only make it
measurable. Branch off `master`.

## Authoritative source files (the brief is subordinate to these)

- `docs/technical/CAPABILITY_ROADMAP.md` — C1 (lines ~62–96): what we build, acceptance, deps
- `docs/ROADMAP.md` — Phase 0 milestones, the locked MCP wedge, risk register (R2, R6)
- `CLAUDE.md` — the wedge, the four primitives, the three verdict axes, the guardrails
- `VISION.md` — narrative thesis, moat, non-goals

## Related issues / PRs

None. Tracker is empty.
