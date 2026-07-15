"""Correlation: a derived index over the frames the trace already holds.

Nothing here captures anything. It reads records a `TraceWriter` wrote and emits
new records answering "which response answered which request" — a side table, so
that the frames stay exactly the bytes that crossed the wire. Writing correlation
back into a frame (into `_meta`, say) would break the byte-neutrality the
differential gate exists to protect, and would make the trace a thing Belay
edited rather than a thing Belay observed.

**This module does not judge.** It records what was observed and names what it
could not read. No verdict, no status beyond the structural facts, no opinion on
whether a call should have happened.

Two decisions carry the weight.

**The key is `(direction, id)`, never the bare id.** MCP is full-duplex: a server
originates requests of its own, and its ids live in its own namespace starting
wherever it likes — typically 1, exactly where the client's start. `id:1`
therefore routinely exists twice in one session meaning two different things, and
a bare-id table silently answers questions about one with the other.

**Classification is structural, never by method.** Responses carry no `method` at
all, so the method cannot be the discriminator; and a non-conforming server that
puts `method` on a response (one exists in this repo's own fixtures) would fool a
classifier that looked for it. `result`/`error` decides.

.. note::
   **There is a second correlation model, and it is deliberately not built here:
   Multi Round-Trip Requests (MRTR, SEP-2322), in the 2026-07-28 revision.**

   That revision removes server-originated requests entirely. A server needing
   input instead returns `resultType: "input_required"` with `inputRequests`, and
   **the client retries the original request under a NEW request id** carrying
   `inputResponses`. Correlating that is a *retry chain*, not a pairing — a
   different problem, not this one with a flag.

   `(direction, id)` is a strict superset that survives both worlds, so it stays.
   No RC servers exist yet, so the chain is not modelled: naming it costs a
   paragraph, guessing at it costs a format version. What this module does owe
   the future is to **not assume one-request-one-response-forever** — hence
   `duplicate-response` below, which appends rather than overwrites. Requests are
   never held waiting for a partner, so a retried request cannot leak an entry.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

# A gap is a fact, so it gets a record rather than an absence. "There is no entry
# for this frame" and "this frame could not be read" are different, and a reader
# that cannot tell them apart will eventually report the second as the first —
# which is the shape of every false PASS this project exists to prevent.
KINDS = ("correlation", "index_gap")


def classify(message: Any) -> str:
    """`request` | `response` | `notification` | `unknown`, from structure alone.

    Order matters: `result`/`error` is checked first, so a response is still a
    response when a non-conforming server also stamps `method` on it.
    """
    if not isinstance(message, dict):
        # A JSON-RPC batch (an array) lands here, as does any other top-level
        # shape. Unknown is the honest answer; a guess is not.
        return "unknown"
    if "result" in message or "error" in message:
        return "response"
    if "method" in message:
        return "request" if "id" in message else "notification"
    return "unknown"


def _id_key(direction: str, id_: Any) -> tuple:
    """The correlation key, with the id's type in it.

    Python would otherwise conflate ids JSON-RPC keeps apart: `1 == True` and
    `1 == 1.0` are both true, so `{"id": 1}` and `{"id": true}` would collide in
    one dict. `"1"` and `1` are likewise different ids on the wire.
    """
    return (direction, type(id_).__name__, id_)


def _opposite(direction: str) -> str:
    return "s2c" if direction == "c2s" else "c2s"


def _parse(record: dict) -> tuple[Optional[Any], Optional[str]]:
    """The frame's message, or None and a named cause."""
    if record.get("truncated"):
        # Forwarded whole, observed short. Whatever we parse from this is a
        # fragment, so we do not parse it: half a message indexed as if it were
        # the message is worse than an acknowledged gap.
        return None, "truncated: the observed copy exceeded MAX_FRAME and is incomplete"
    try:
        return json.loads(base64.b64decode(record["raw"])), None
    except ValueError as exc:  # invalid JSON, or bytes that are not UTF-8
        return None, f"unparseable: {type(exc).__name__}: {exc}"


def _gap(record: dict, cause: str) -> dict:
    return {
        "kind": "index_gap",
        "seq": record["seq"],
        "dir": record["dir"],
        "cause": cause,
    }


def derive_correlation(records: list[dict]) -> list[dict]:
    """Pair requests with their responses; return correlation and gap records.

    Single pass, and it never waits: an unanswered request is legal — MCP
    cancellation is racy by design — so it is recorded as unanswered rather than
    treated as an entry still owed a partner. Nothing is held back at the end,
    so nothing leaks.
    """
    entries: dict[tuple, dict] = {}
    out: list[dict] = []

    for record in records:
        if record.get("kind") != "frame":
            continue

        message, cause = _parse(record)
        if cause is not None:
            out.append(_gap(record, cause))
            continue
        if not isinstance(message, dict):
            # A JSON-RPC batch array, or any other top-level shape. Named, not
            # skipped: we read the bytes and could not place them, which is not
            # the same as there having been nothing here.
            out.append(_gap(record, "unknown message shape: not a JSON object"))
            continue

        kind = classify(message)
        direction = record["dir"]

        if kind == "request":
            entry: dict[str, Any] = {
                "kind": "correlation",
                # The direction the REQUEST travelled: the id space it belongs
                # to, and the whole reason two `id:1`s stay apart.
                "origin": direction,
                "id": message.get("id"),
                "method": message.get("method"),
                "request_seq": record["seq"],
                "response_seq": None,
                "status": "unanswered",
            }
            out.append(entry)
            entries[_id_key(direction, message.get("id"))] = entry
        elif kind == "response":
            # A response travels back the way its request came, so the request's
            # id space is the opposite direction's.
            origin = _opposite(direction)
            answered = entries.get(_id_key(origin, message.get("id")))
            if answered is None:
                # Legal: the proxy can attach mid-connection, and the request
                # that earned this reply predates capture.
                out.append(
                    {
                        "kind": "correlation",
                        "origin": origin,
                        "id": message.get("id"),
                        "method": None,  # responses carry no method to borrow
                        "request_seq": None,
                        "response_seq": record["seq"],
                        "status": "response-without-request",
                    }
                )
            elif answered["status"] == "answered":
                # A second reply to an id already answered. Non-conforming, and
                # both replies really did cross the wire — so this is appended as
                # its own fact rather than written over the first. Overwriting
                # would leave the trace asserting a reply that did not happen and
                # silently losing one that did.
                out.append(
                    {
                        "kind": "correlation",
                        "origin": origin,
                        "id": message.get("id"),
                        "method": answered["method"],
                        "request_seq": answered["request_seq"],
                        "response_seq": record["seq"],
                        "status": "duplicate-response",
                    }
                )
            else:
                answered["response_seq"] = record["seq"]
                answered["status"] = "answered"
        elif kind == "unknown":
            out.append(
                _gap(record, "unknown message shape: neither request, response nor notification")
            )
        # A notification has no id and no reply by definition. There is nothing
        # to correlate it to, and that is not a gap.

    return out


def tool_calls(index: list[dict]) -> list[dict]:
    """`tools/call` as a derived index: a filter, not a unit of capture.

    The proxy records frames. A tool call is a thing you notice about frames
    afterwards, which is why this is four lines and not a subsystem.
    """
    return [
        entry
        for entry in index
        if entry["kind"] == "correlation" and entry.get("method") == "tools/call"
    ]
