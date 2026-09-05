# Invite — send this (edit the bracketed bits)

**Subject: Can I borrow an hour of your time to break my agent tool?**

Hi [name],

I'm about to publish a tool I've been building — **Belay**, a harness that
sits between an AI agent and the tools it calls, and **verifies each step by
re-running it**: it records what the agent did, restores the real pre-state of
each tool call, re-executes it, and diffs the result. Verdicts are grounded in
re-execution, not in a model judging itself.

The measurement behind it: in a 60-run study, **11 of 60 agent runs claimed the
work was verified without ever running anything — 18.3%, hand-audited**. That's
the failure mode Belay exists to catch, and the honest version of the pitch is
that it's measurable.

Before I publish, I need one thing I can't do myself: **someone who is not me
installing it and using it against their own agent.** Not a demo — your real
agent, your real task, your real tools. The mission is to try to catch it
**crying wolf** as much as to catch a real failure: either result is useful, and
both get reported honestly.

What it takes:

- **~1 hour**, macOS or Linux, Python 3.10+. One install command —
  `uv tool install belay-harness`, or `docker pull ghcr.io/haqaliz/belay` if you
  would rather not install anything.
- You run your agent against an MCP server as usual, with Belay's proxy in
  front — one line changed in how you launch the server.
- You run `belay verify` on the recorded trace. If a turn comes back FAIL, we
  look at whether it's a real failure or an instrument artifact — **you
  adjudicate, not the tool**.
- You tell me what happened. There's a short report form.

Honest limits, up front, because the tool's whole point is not over-claiming:

- It's **alpha**. macOS + Linux sandbox; it sees **what crosses the MCP
  boundary** — an agent's built-in tools (Claude Code's `Bash`/`Edit`, for
  example) are invisible to it.
- A `PASS` covers the dimensions it checks and **excludes the network
  dimension entirely** — there's no network instrument.
- `UNVERIFIED` means "we tried and couldn't check" — never rendered as PASS.

If you're game, the step-by-step is in the runbook I'll send (or:
`docs/planning/launch-readiness/external-self-hoster/runbook.md` in the repo).
If anything breaks, that's a finding too — report it the same way.

Thanks for the hour,

[you]