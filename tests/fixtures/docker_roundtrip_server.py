"""A deterministic MCP server with exactly one mutating tool, for the in-image roundtrip.

Used only by `tests/test_docker_inimage.py`, which drives it once through the gated
proxy and then hands the SAME command to `belay verify` for re-execution. Both runs
must produce byte-identical replies or A2 result-equivalence has nothing to report,
so nothing here reads a clock, a random source, the network or the environment.

The write target arrives as the tool call's `path` ARGUMENT rather than an env var
or a hard-coded constant, and that is load-bearing rather than stylistic: replay
restores the pre-state into a scratch tree and relocates a turn's whole-value
in-root absolute paths into it (`belay.replay.relocate`). A path carried as an
argument is relocated, so the replayed write lands in the scratch and the delta is
real; a path smuggled through the environment would be invisible to relocation and
the replay would write straight back into the live workspace — a contaminated
verdict rather than a grounded one.

The one thing here that is not pure request/response: the `tools/list` reply waits
until the trace has recorded the REQUEST. The proxy forwards before it records (by
design — see `docker_roundtrip_trace.py`), so a server that answers fast enough can
have its RESPONSE recorded first; an inverted pair does not correlate, the
annotation snapshot is never taken, and effect-conformance abstains. Only the
server can close that window, because only the server decides when to answer. The
`tools/call` branch is untouched by this and stays purely deterministic — which is
what matters, since replay re-invokes that branch and nothing else.

`readOnlyHint: false` is declared truthfully (the tool does mutate), so A2's
effect-conformance has a contract to check instead of abstaining for want of one.
`openWorldHint: false` is declared just as truthfully and is the point of the last
assertion in the roundtrip test: Belay has no network instrument, so that promise
comes back NOT_COVERED — a coverage boundary printed next to the PASS, never folded
into it.
"""

import json
import os
import sys

from docker_roundtrip_trace import await_recorded

TOOL = {
    "name": "write_note",
    "description": "Write one fixed note to the given path.",
    "inputSchema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    "annotations": {"readOnlyHint": False, "openWorldHint": False},
}

NOTE = "note\n"


def _reply(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message).encode() + b"\n")
    sys.stdout.buffer.flush()


def main() -> None:
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method, msg_id = message.get("method"), message.get("id")

        if method == "initialize":
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "docker-roundtrip", "version": "1"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue  # a notification: no reply, ever
        elif method == "tools/list":
            trace_dir = os.environ.get("BELAY_TRACE_DIR")
            if trace_dir:
                # Nothing is being captured when this is unset (replay, or a bare
                # run), and then there is no ordering to protect.
                await_recorded(trace_dir, "c2s", method="tools/list")
            _reply({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [TOOL]}})
        elif method == "tools/call":
            target = message["params"]["arguments"]["path"]
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(NOTE)
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": "wrote note"}],
                        "isError": False,
                    },
                }
            )


if __name__ == "__main__":
    main()
