"""The approval gate's pure decision core: parse a frame, decide, hold.

Aspect `approval-gate/decision-model`: given a c2s frame and the live
annotation facts for the tool it names, decide hold / no-hold, and model a
hold's life (pending -> approved / denied / timed out) with a closed cause
vocabulary. No I/O, no proxy coupling, no trace writes — everything here is
testable with plain bytes and dicts, and the channel aspect (the proxy hook)
composes these pieces.

Two honesty rules shape this module:

- **Never hold on doubt.** A frame that is not a single `tools/call` REQUEST
  (notification, response, batch, garbage) is forwarded untouched, and a
  `params.name` that is not a string yields no tool name. A hold is a state
  change the proxy makes; doubt must never manufacture one. Every parse here
  is structural and never raises.
- **A default is not a declaration.** `triggers_for` reads the tri-state
  vocabulary from `belay.declared` — only `declared-true` on `destructiveHint`
  or `openWorldHint` triggers a hold. The MCP spec's fail-safe defaults
  (`destructiveHint: true`, `openWorldHint: true` when omitted) are exactly the
  declarations that must NOT trigger one.

Batch JSON-RPC frames (arrays) are **never held**: holding one would require
rewriting the frame to split it, which the proxy cannot do — they are
forwarded untouched.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def _load(frame: bytes) -> Any:
    """Parse a frame copy, or None on any unreadable input — never raise."""
    try:
        return json.loads(frame)
    except ValueError:
        return None


def is_tools_call(frame: bytes) -> bool:
    """True exactly for a single JSON-RPC `tools/call` REQUEST.

    Structural only: a dict with `method == "tools/call"` and an `id` key
    (string, int, or null — JSON-RPC 2.0 permits null). Notifications (no
    `id`), responses (no `method`), batches (arrays), other methods, and
    unparseable bytes are all False, never raising: the hook runs on every c2s
    frame, so a raise would kill the direction it is guarding.
    """
    if not isinstance(frame, bytes):
        return False
    message = _load(frame)
    if not isinstance(message, dict):
        return False
    return message.get("method") == "tools/call" and "id" in message


def tool_name(frame: bytes) -> Optional[str]:
    """The `params.name` of a `tools/call` request, or None on any doubt.

    A non-string or absent `params.name` yields None, never a hold on doubt.
    `params` that is not an object (JSON-RPC 2.0 permits positional params)
    likewise yields None.
    """
    if not isinstance(frame, bytes):
        return None
    message = _load(frame)
    if not isinstance(message, dict):
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    name = params.get("name")
    return name if isinstance(name, str) else None


def request_id(frame: bytes) -> Any:
    """The JSON-RPC `id` of a `tools/call` request (string, int, null, or None).

    Absent and `null` both read as None; callers pair this with `is_tools_call`,
    which guarantees the key was present, so the two are never conflated.
    """
    if not isinstance(frame, bytes):
        return None
    message = _load(frame)
    if not isinstance(message, dict):
        return None
    return message.get("id")