"""A fake MCP editor that writes OUTSIDE the default A1 content-rule scope.

Same shape as `weakening_editor_server.py` — honestly declares `readOnlyHint: false` and
overwrites a file — but the target is `src/app.py`, not anything under `tests/` or
`testing/`. `default_invariants()` scopes the `no-assertion-weakening` content rule over
exactly those two path segments, so `_evaluate_content_rule` finds ZERO in-scope files for
this write under either default invariant: `in_scope` is empty, `compared` never leaves 0.

This is the exposure aspect's "no opportunity" fixture: the rule RAN (it is declared, it
evaluated the delta) and found nothing it was scoped to judge. A PASS produced from it says
nothing about whether the rule would have caught a real weakening — which is the exact
distinction `belay verify`'s exposure line exists to make visible.

Stdlib only, deterministic, no network, no sleeps. Reads newline-delimited JSON-RPC from
stdin; answers `initialize`, `tools/list`, and `tools/call`.
"""

import json
import sys
from pathlib import Path

PROTOCOL_VERSION = "2025-11-25"

#: The file this editor overwrites, relative to its cwd (the restored pre-state scratch
#: under replay). Deliberately outside `tests/` and `testing/` — see the module docstring.
TARGET_PATH = "src/app.py"

#: The content written. Its exact text doesn't matter for the invariant (it is never
#: in-scope); it only needs to differ from the pre-state so the tree diff records a real
#: mutated path, exercising the same delta machinery `weakening_editor_server.py` does.
NEW_CONTENT = "def handler():\n    return 42\n"

#: The fixed reply text, matching the recorded reply byte-for-byte so result-equivalence
#: PASSes and any divergence in the turn's reduced status can only come from A1.
REPLY_TEXT = f"edited {TARGET_PATH}"

TOOLS = [
    {
        "name": "edit_file",
        "description": "Edits a file. Honestly declares it mutates the workspace.",
        "inputSchema": {"type": "object", "properties": {}},
        # Truthful declaration, exactly like `weakening_editor_server.py`'s: A2 effect
        # conformance PASSes a write this tool announced up front.
        "annotations": {"readOnlyHint": False},
    }
]


def _send(stdout, message: dict) -> None:
    stdout.write((json.dumps(message) + "\n").encode("utf-8"))
    stdout.flush()


def _handle(stdout, method: str, msg_id, params: dict) -> None:
    if method == "initialize":
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "scope-free-editor", "version": "1"},
                },
            },
        )
    elif method == "tools/list":
        _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        target = Path(TARGET_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(NEW_CONTENT, encoding="utf-8")
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": REPLY_TEXT}],
                    "isError": False,
                },
            },
        )
    elif msg_id is not None:
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            },
        )


def main() -> None:
    stdout = sys.stdout.buffer
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        if method is None:
            continue  # a response to something we sent; we originate nothing
        _handle(stdout, method, message.get("id"), message.get("params") or {})


if __name__ == "__main__":
    main()
