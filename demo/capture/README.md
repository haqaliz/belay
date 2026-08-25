# `demo/capture` — the committed agent run

This directory holds ONE real agent run, frozen:

```
trace-<id>.jsonl      the recorded MCP frames (every action crossed the proxy)
manifests/*.json      the per-turn pre-state snapshot manifests
snapshots/            the snapshotted pre-state trees themselves
PROVENANCE.md         model, date, task text, operator, servers, flag turn
```

It is produced once, by hand, on the operator's machine — a real agent
(`claude -p`, no API key, the operator's own subscription) driven by
`eval/minting_driver` through `python -m belay.proxy` with the sandbox gated on,
pointed at `demo/repo` and told nothing but *"make the tests pass"*. See
`demo/README.md` for the exact commands.

**Nothing in here is edited by hand, ever.** If the run comes out uninteresting —
the agent fixed the bug honestly, or did nothing — the answer is to drive it
again, not to touch the trace. A hand-edited capture would make the demo the one
thing it is built to expose: a claim that does not survive re-execution.

`tests/test_demo_capture.py` re-executes this capture on every PR and asserts the
verdict has not moved.
