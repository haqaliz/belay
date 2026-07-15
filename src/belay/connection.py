"""Connection context — which protocol, which client — resolved for every frame.

**Why "connection" and not "session", which a future reader will want to rename
it back to:** because a session is a thing the protocol says does not exist. The
2026-07-28 revision states it outright:

    "an open connection, such as a STDIO process, is not a conversation or
    session: clients may interleave unrelated requests on the same transport,
    and a server must not treat connection or process identity as a proxy for
    conversation or session continuity."

and makes MCP explicitly stateless: *"all the information needed to process a
request is contained in the request itself... no state should be inferred from
previous requests, even those on the same connection or stream."* Naming our
T0->T1 fact a "session" would encode a falsehood the spec forbids, in an
interchange format that cannot be quietly changed later. **The reason is the
point, not the label.**

Belay resolves this **per frame** rather than writing one header and pointing
every frame at it. That looks like redundancy. It is the only model that works:
the same revision removes the `initialize`/`initialized` handshake (SEP-2575) and
the protocol-level session, including `Mcp-Session-Id` (SEP-2567), moving
protocol version, client identity and capabilities into `_meta` on **every
request**. There is no session-start frame left to point at and no session id to
join on, so a trace whose context lived in a header would go blank the day a
client updates, and every replay built on that header would go with it. Per-frame
resolution costs almost nothing under raw forwarding, reads both the handshake
world and the `_meta` world, and keeps that migration off the critical path.

Resolution order, and it never leaves this order:

1. the `initialize` handshake, if one was captured
2. per-request `_meta`
3. **unknown, with a named cause**

Never a guess, and never the last value we happened to see smeared backwards over
frames that predate it — a negotiated version is not in force before it was
negotiated, and a trace that says otherwise cannot be asked when the contract
took effect.

An unrecognised `_meta` is reported unknown **with the keys it carried**, so a
key name Belay does not know surfaces as a named gap in the trace rather than as
a client that appears to have declared nothing.
"""

from __future__ import annotations

from typing import Any, Optional

from belay.frames import message_of
from belay.index import classify, derive_correlation

KINDS = ("connection_context", "trace_context")

# Reserved in `_meta` as an EXPLICIT exception to the reverse-DNS prefix rule,
# for W3C Trace Context / OpenTelemetry propagation. Belay records them and does
# nothing else with them: interpreting or stitching spans is the OTel bridge's
# job, and C1's only duty is to not lose what crossed the wire.
_TRACE_CONTEXT_KEYS = ("traceparent", "tracestate", "baggage")

# The normative 2026-07-28 keys, REQUIRED on every client request (a request
# missing them is malformed and the server must reject it -32602). Only these:
# recognising a spelling no revision defines would let Belay resolve context out
# of a key nobody promised, which is a fabrication with extra steps. The key that
# matched is recorded on the resolution, so a reader never has to infer the shape.
_META_VERSION_KEYS = ("io.modelcontextprotocol/protocolVersion",)
_META_CLIENT_KEYS = ("io.modelcontextprotocol/clientInfo",)

_NO_HANDSHAKE = (
    "no initialize handshake was captured and this frame carried no recognised "
    "connection context in params._meta"
)


def _message(record: dict) -> Optional[Any]:
    """The message alone, for the callers that have nowhere to put a cause.

    `_Handshake.observe` and `_trace_context` both read a frame only to see
    whether something is in it. Neither emits a record, so neither can name a
    gap — and an unreadable frame is already named twice over: by
    `derive_correlation`'s `index_gap`, and by `resolve` below, which turns the
    cause into the `unknown` on this very frame's `connection_context`. The
    discard is explicit here so it stays a decision rather than a habit.
    """
    message, _unreadable = message_of(record)
    return message


def _unknown(cause: str) -> dict:
    return {"status": "unknown", "cause": cause}


def _resolved(value: Any, source: str, source_key: Optional[str] = None) -> dict:
    resolution = {"status": "resolved", "value": value, "source": source}
    if source_key is not None:
        resolution["source_key"] = source_key
    return resolution


def _meta_of(message: Any) -> Optional[dict]:
    """`_meta`, from `params` or the top level.

    `params._meta` is where the SDK puts it. The top level is checked too, and
    only because being wrong about the *location* is cheap while being wrong
    about the *key names* is not: finding `_meta` is what lets an unrecognised
    key be reported loudly, with the keys it carried, instead of falling through
    to the silent "nothing was declared" branch.
    """
    if not isinstance(message, dict):
        return None
    params = message.get("params")
    for holder in (params, message):
        if isinstance(holder, dict) and isinstance(holder.get("_meta"), dict):
            return holder["_meta"]
    return None


def _from_meta(meta: dict, keys: tuple[str, ...]) -> Optional[dict]:
    for key in keys:
        if key in meta:
            return _resolved(meta[key], "request_meta", key)
    return None


def _meta_cause(meta: Optional[dict]) -> str:
    if meta is None:
        return _NO_HANDSHAKE
    # Name what was actually there. If Belay's idea of the key names is wrong,
    # this is the line that says so out loud instead of swallowing it.
    return (
        "no initialize handshake was captured; params._meta was present but carried "
        f"no recognised connection context (keys: {sorted(meta)})"
    )


class _Handshake:
    """What the `initialize` exchange declared, and from which frame onwards.

    Two different frames, deliberately. The client declares its identity in the
    request; the server chooses the version in the response. Neither fact exists
    before the frame that carried it.
    """

    def __init__(self) -> None:
        self.client: Optional[Any] = None
        self.client_seq: Optional[int] = None
        self.version: Optional[Any] = None
        self.version_seq: Optional[int] = None

    def observe(self, records: list[dict], index: list[dict]) -> None:
        frames = {r["seq"]: r for r in records if r.get("kind") == "frame"}
        for entry in index:
            if entry["kind"] != "correlation" or entry.get("method") != "initialize":
                continue
            if entry["request_seq"] is not None:
                request = _message(frames[entry["request_seq"]])
                params = request.get("params") if isinstance(request, dict) else None
                if isinstance(params, dict) and "clientInfo" in params:
                    self.client = params["clientInfo"]
                    self.client_seq = entry["request_seq"]
            if entry["response_seq"] is not None:
                response = _message(frames[entry["response_seq"]])
                result = response.get("result") if isinstance(response, dict) else None
                if isinstance(result, dict) and "protocolVersion" in result:
                    # The NEGOTIATED version: the server's choice, not the
                    # client's proposal. The proposal is what the client asked
                    # for and is not in force unless the server agreed.
                    self.version = result["protocolVersion"]
                    self.version_seq = entry["response_seq"]
            break  # the first handshake; a second would be a new connection

    def version_at(self, seq: int) -> Optional[dict]:
        if self.version_seq is None or seq < self.version_seq:
            return None
        return _resolved(self.version, "handshake")

    def client_at(self, seq: int) -> Optional[dict]:
        if self.client_seq is None or seq < self.client_seq:
            return None
        return _resolved(self.client, "handshake")

    def pending_cause(self, seq: int, declared_seq: Optional[int]) -> Optional[str]:
        """Why a frame that PRECEDES the declaration has no context.

        `declared_seq` differs per axis: the client declared its identity in the
        request, the server chose the version in the response. A frame before
        either has no context for that axis, and saying so is the whole point —
        smearing the eventual value backwards would hide when the contract
        actually took effect.
        """
        if declared_seq is None or seq >= declared_seq:
            return None
        return (
            "the initialize handshake had not completed at this point in capture "
            "order, so no connection context was in force yet"
        )


def _trace_context(record: dict) -> Optional[dict]:
    """W3C trace context from `_meta`, verbatim, or nothing.

    Emitted only when at least one key is present: a record per frame saying
    "no trace context" would be noise rather than a fact.
    """
    meta = _meta_of(_message(record))
    if meta is None:
        return None
    present = {key: meta[key] for key in _TRACE_CONTEXT_KEYS if key in meta}
    if not present:
        return None
    return {"kind": "trace_context", "seq": record["seq"], **present}


def derive_connection_context(records: list[dict]) -> list[dict]:
    """One `connection_context` record per frame, resolved or honestly unknown."""
    index = derive_correlation(records)
    frames = [r for r in records if r.get("kind") == "frame"]
    by_seq = {r["seq"]: r for r in frames}

    handshake = _Handshake()
    handshake.observe(records, index)

    # A response carries neither `_meta` nor a handshake of its own, so its
    # context is the context of the request it answered — which correlation, and
    # only correlation, can tell us.
    request_seq_of = {
        entry["response_seq"]: entry["request_seq"]
        for entry in index
        if entry["kind"] == "correlation" and entry["response_seq"] is not None
    }

    def resolve(record: dict, keys: tuple[str, ...], handshake_at, declared_seq) -> dict:
        seq = record["seq"]

        from_handshake = handshake_at(seq)
        if from_handshake is not None:
            return from_handshake

        message, unreadable = message_of(record)
        meta = _meta_of(message)
        if meta is not None:
            from_meta = _from_meta(meta, keys)
            if from_meta is not None:
                return from_meta

        if classify(message) == "response":
            origin = request_seq_of.get(seq)
            if origin is not None and origin in by_seq:
                inherited = _meta_of(_message(by_seq[origin]))
                if inherited is not None:
                    from_request = _from_meta(inherited, keys)
                    if from_request is not None:
                        return from_request

        pending = handshake.pending_cause(seq, declared_seq)
        if pending is not None:
            return _unknown(pending)
        if unreadable is not None:
            # The decoder's own cause, verbatim: truncated, or unparseable. Both
            # mean the same thing here — whatever context this frame carried, we
            # did not see it — and neither may be reported as "declared nothing".
            return _unknown(
                f"this frame could not be read ({unreadable}), so any connection "
                f"context it carried was not observed"
            )
        return _unknown(_meta_cause(meta))

    out: list[dict] = []
    for record in frames:
        out.append(
            {
                "kind": "connection_context",
                "seq": record["seq"],
                "protocol_version": resolve(
                    record, _META_VERSION_KEYS, handshake.version_at, handshake.version_seq
                ),
                "client": resolve(
                    record, _META_CLIENT_KEYS, handshake.client_at, handshake.client_seq
                ),
            }
        )
        trace = _trace_context(record)
        if trace is not None:
            out.append(trace)
    return out
