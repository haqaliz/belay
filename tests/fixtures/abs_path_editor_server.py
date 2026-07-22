"""A fake MCP editor that addresses files by ABSOLUTE path under an argv-supplied root.

This fixture is the deliberate INVERSE of every other server fixture in this repo.
`weakening_editor_server.py`, `readonly_liar_server.py`, and friends all write to a
path RELATIVE to the process cwd — and under replay `client.replay_turn` sets that
cwd to the restored pre-state scratch, so a cwd-relative write silently lands in the
right place with no path rewriting at all. That is precisely why a replay bug for
ABSOLUTE-path servers could sail through CI: nothing exercised the class.

This server exercises it. It is launched as::

    python abs_path_editor_server.py <ABS_ROOT>

and it addresses files by the ABSOLUTE path carried in each `tools/call`'s
`arguments` (e.g. `{"path": "/abs/root/src/auth.py"}`). It operates on that absolute
path DIRECTLY — it never joins it onto cwd — so a correct replay of this server must
relocate BOTH the argv root and the in-argument absolute path into the scratch, or
reads/writes miss the restored pre-state.

## Why argv[1] is load-bearing (and not merely decorative)

`<ABS_ROOT>` is an *allowed-root* allowlist, exactly as the real
`@modelcontextprotocol/server-filesystem` treats its root arguments: every
`tools/call` path is confined to it, and a path outside the root is refused with
`isError: true`. This is what makes relocating the argv root necessary rather than
cosmetic — if replay rewrote only the in-argument path to the scratch while leaving
the argv root at the original workspace, the confinement check would REJECT the
scratch path as out-of-root. Both must move together. A fixture that ignored argv[1]
would let a half-correct relocation pass, defeating the point.

## Benign vs. corrupt edits (for the FP/FN acceptance tests)

`edit_abs` faithfully writes the caller-supplied `new_content` to the absolute path;
it invents nothing. Benign vs. corrupt is therefore chosen by the DRIVER, not the
server, and the two canonical payloads are exported for the e2e phase to import:

  - `ORIGINAL_CONTENT` — what the seed file holds in the recorded pre-state.
  - `BENIGN_CONTENT`  — a correct edit that KEEPS the real security assertion. Driving
    `edit_abs` with this must not flag (no false positive): the replayed write
    reproduces and no invariant is crossed.
  - `CORRUPT_CONTENT` — a gutted body with the real assertion REMOVED (the analogue of
    `weakening_editor_server.WEAKENED_TEST`). Driving `edit_abs` with this must flag
    (no false negative): the write lands in the relocated scratch, so the tree diff
    sees a real content change under the `tests/`-style read-only subtree.

Under replay the pre-state is restored identically, so for a fixed `new_content` the
reply reproduces byte-for-byte — the edit is deterministic given (pre-state, args).

## Reply shapes (for the reply-normalization phase)

`edit_abs` takes an optional `reply_format`:

  - `"plain"` (default) → `EDIT_REPLY`, a FIXED literal that contains NO path. It
    reproduces trivially on replay and needs no normalization — the clean case.
  - `"diff"` → a unified diff whose `Index:` / `---` / `+++` lines carry the ABSOLUTE
    path. On replay the path is relocated to the scratch, so recorded and replayed
    diffs differ ONLY in that prefix — the exact substring a later
    `canonicalize_reply` step must map to a placeholder to compare equal. The diff is
    built with `difflib` and carries NO timestamps, so it stays deterministic.

Stdlib only, deterministic, no network, no sleeps. Reads newline-delimited JSON-RPC
from stdin; answers `initialize`, `tools/list`, and `tools/call`.
"""

from __future__ import annotations

import difflib
import json
import os
import sys

PROTOCOL_VERSION = "2025-11-25"

#: Tool names. `read_abs` honestly declares it only reads; `edit_abs` honestly
#: declares it mutates (mirroring `weakening_editor_server`'s declared-false).
READ_TOOL = "read_abs"
EDIT_TOOL = "edit_abs"

#: The seed file's path RELATIVE to the argv root. Nested under a `tests/`-style
#: subtree so an invariant scoped over that subtree has something to scope over. The
#: DRIVER seeds `root / SEED_REL_PATH`; the server only ever addresses it by its
#: absolute form.
SEED_REL_PATH = "tests/test_auth.py"

#: The strong pre-state body: it carries the real security assertion.
ORIGINAL_CONTENT = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

#: A correct edit — keeps the real assertion, adds a benign second case. Driving
#: `edit_abs` with this is the no-false-positive case.
BENIGN_CONTENT = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
    "    assert authenticate('user', '') is False\n"
)

#: A gutted edit — the real assertion REPLACED by a trivial pass. Driving `edit_abs`
#: with this is the no-false-negative case (the analogue of WEAKENED_TEST).
CORRUPT_CONTENT = (
    "def test_rejects_wrong_password():\n"
    "    # gutted so the suite goes green on broken auth\n"
    "    assert True\n"
)

#: The fixed plain reply. Deliberately contains NO path, so result-equivalence needs
#: no normalization for the default reply shape.
EDIT_REPLY = "edit-abs: wrote file"


TOOLS = [
    {
        "name": READ_TOOL,
        "description": "Reads a file addressed by absolute path under the argv root.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        # Honest: it only reads.
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": EDIT_TOOL,
        "description": "Overwrites a file addressed by absolute path under the argv root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "new_content": {"type": "string"},
                "reply_format": {"type": "string", "enum": ["plain", "diff"]},
            },
            "required": ["path", "new_content"],
        },
        # Honest: it declares that it mutates.
        "annotations": {"readOnlyHint": False},
    },
]


def _send(stdout, message: dict) -> None:
    stdout.write((json.dumps(message) + "\n").encode("utf-8"))
    stdout.flush()


def _text_result(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _under_root(path: str, root: str) -> bool:
    """True iff `path` is an absolute path at or under `root` (boundary-safe).

    Both are realpath-normalized so `/a/b` is never mistaken for a child of `/a/bc`.
    """
    if not os.path.isabs(path):
        return False
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(path)
    return real_path == real_root or real_path.startswith(real_root + os.sep)


def _diff_reply(path: str, old: str, new: str) -> str:
    """A deterministic unified diff whose header lines carry the ABSOLUTE path."""
    body = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=path,
        tofile=path,
        lineterm="\n",
    )
    return f"Index: {path}\n" + "".join(body)


def _handle(stdout, root: str, method: str, msg_id, params: dict) -> None:
    if method == "initialize":
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "abs-path-editor", "version": "1"},
                },
            },
        )
    elif method == "tools/list":
        _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        path = arguments.get("path", "")
        # Confinement to the argv-supplied root — the check that makes relocating the
        # argv root load-bearing. An out-of-root path is refused, never touched.
        if not _under_root(path, root):
            _send(
                stdout,
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": _text_result(
                        f"path is not under the allowed root: {path}", is_error=True
                    ),
                },
            )
            return
        if name == READ_TOOL:
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            _send(
                stdout,
                {"jsonrpc": "2.0", "id": msg_id, "result": _text_result(content)},
            )
        elif name == EDIT_TOOL:
            new_content = arguments.get("new_content", "")
            reply_format = arguments.get("reply_format", "plain")
            old_content = ""
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    old_content = fh.read()
            # Operate on the ABSOLUTE path directly — never joined onto cwd.
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            if reply_format == "diff":
                reply = _diff_reply(path, old_content, new_content)
            else:
                reply = EDIT_REPLY
            _send(
                stdout,
                {"jsonrpc": "2.0", "id": msg_id, "result": _text_result(reply)},
            )
        elif msg_id is not None:
            _send(
                stdout,
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"},
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


def main(argv: list[str]) -> None:
    # The absolute allowed root. Realpath-normalized once so confinement checks are
    # stable regardless of how the caller spelled it.
    root = os.path.realpath(argv[0])
    stdout = sys.stdout.buffer
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        if method is None:
            continue  # a response to something we sent; we originate nothing
        _handle(stdout, root, method, message.get("id"), message.get("params") or {})


if __name__ == "__main__":
    main(sys.argv[1:])
