"""Failure, classified from the raw bytes — and the two failures kept apart.

MCP expresses failure two ways, and they are different events:

- **Protocol error** — a JSON-RPC `error` member and no `result`. The call did
  not happen. There is no tool output, because the tool was never reached.
- **Tool execution error** — a perfectly successful JSON-RPC envelope carrying a
  `result` whose payload declares `isError: true`. The call happened; the tool
  ran and reported failure from inside.

Collapsing those into "it errored" would be the single most tempting
simplification in this module and the most expensive: they replay differently,
they mean different things about what state was touched, and **the line between
them has already moved once**. The 2025-11-25 revision (SEP-1303) reclassified
input-validation failures from the first to the second, to let a model
self-correct. So the same underlying failure has different wire shapes depending
on the revision the server implements, and a trace that recorded a verdict
instead of the shape would be unreadable across that boundary.

Which is the rule this module follows: **record raw; derive the classification.**
The raw bytes are already in the trace, unmodified; everything here is a view
over them that can be recomputed, corrected, or extended later without the
original ever having been rewritten.

**This module does not judge.** An error is not a failure of the agent, a
violation, or a finding. It is a shape on the wire, recorded as such.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

from belay.declared import declared_state
from belay.index import classify, derive_correlation

KINDS = ("error_classification", "classification_gap")


def _message(record: dict) -> tuple[Optional[Any], Optional[str]]:
    if record.get("truncated"):
        return None, "truncated: the observed copy exceeded MAX_FRAME and is incomplete"
    try:
        return json.loads(base64.b64decode(record["raw"])), None
    except ValueError as exc:
        return None, f"unparseable: {type(exc).__name__}: {exc}"


def _protocol_error(message: dict) -> dict:
    """The `error` member, if there is one. Recorded, not interpreted."""
    error = message.get("error")
    if "error" not in message:
        return {"status": "absent"}
    if not isinstance(error, dict):
        return {"status": "present", "malformed": True, "value": error}
    return {
        "status": "present",
        "code": error.get("code"),
        "message": error.get("message"),
    }


def _result_type(result: Any) -> dict:
    """`resultType` as declared, or `not-declared`. Never the assumed default.

    The 2026-07-28 revision requires every result to carry `resultType`
    (`"complete"` | `"input_required"`), and requires clients to **treat an
    absent one from an earlier-protocol server as `"complete"`**. That is an
    assumption, and an assumption is not a declaration: every server shipping
    today omits this field, and materialising `"complete"` would record all of
    them as having declared something none of them said. Same discipline as the
    annotation defaults, same reason.

    `"input_required"` is the MRTR shape (SEP-2322). Recorded as a plain fact —
    see `belay.index` on why the retry chain itself is not modelled here.
    """
    if not isinstance(result, dict) or "resultType" not in result:
        return {"status": "not-declared"}
    return {"status": "declared", "value": result["resultType"]}


def _structured_content(result: Any) -> dict:
    """Whether `structuredContent` also went out serialised into a text block.

    Servers SHOULD do exactly that for backwards compatibility, so **the same
    data commonly crosses the wire twice**. Both copies are already recorded
    verbatim in the frame; this names the duplication so a reader does not count
    one payload as two independent facts.

    Duplication is decided by comparing parsed JSON, not text: the text block is
    the server's own serialisation and may differ in key order or whitespace
    while carrying identical data.
    """
    if not isinstance(result, dict) or "structuredContent" not in result:
        return {"status": "absent"}

    structured = result["structuredContent"]
    duplicates = []
    content = result.get("content")
    if isinstance(content, list):
        for position, block in enumerate(content):
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            try:
                parsed = json.loads(block.get("text", ""))
            except (ValueError, TypeError):
                continue  # prose, not a serialisation of the structured payload
            if parsed == structured:
                duplicates.append(position)

    return {"status": "present", "also_serialised_as_text": duplicates}


def derive_error_classification(records: list[dict]) -> list[dict]:
    """Classify every response frame; name every frame that could not be read."""
    index = derive_correlation(records)
    # A response carries no method, so what it was a reply TO is only knowable
    # through correlation. Carrying the method here costs nothing and spares
    # every reader the join.
    method_by_response = {
        entry["response_seq"]: entry.get("method")
        for entry in index
        if entry["kind"] == "correlation" and entry["response_seq"] is not None
    }

    out: list[dict] = []
    for record in records:
        if record.get("kind") != "frame":
            continue

        message, cause = _message(record)
        if cause is not None:
            out.append({"kind": "classification_gap", "seq": record["seq"], "cause": cause})
            continue
        if not isinstance(message, dict) or classify(message) != "response":
            continue

        result = message.get("result")
        out.append(
            {
                "kind": "error_classification",
                "seq": record["seq"],
                "id": message.get("id"),
                "method": method_by_response.get(record["seq"]),
                "protocol_error": _protocol_error(message),
                # Kept alongside the error member rather than derived from it: a
                # non-conforming server can send both, and "neither" is a shape
                # too. Recording the presence of each lets a reader see exactly
                # what arrived instead of trusting this module's arithmetic.
                "result": "present" if "result" in message else "absent",
                "is_error": declared_state(
                    result.get("isError") if isinstance(result, dict) else None,
                    isinstance(result, dict) and "isError" in result,
                ),
                "result_type": _result_type(result),
                "structured_content": _structured_content(result),
            }
        )
    return out
