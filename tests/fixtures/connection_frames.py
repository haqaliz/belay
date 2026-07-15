"""Frames in the 2026-07-28 shape: connection context on every request, no handshake.

The 2026-07-28 revision removes the `initialize`/`initialized` handshake
(SEP-2575) and the protocol-level session (SEP-2567). Protocol version, client
identity and capabilities move into `_meta` on **every request** — all three
REQUIRED, a request missing any being malformed and rejected `-32602`. So there
is no "session start" frame to point at and no session id to join on: a trace
that resolved context by finding the handshake would stop resolving anything the
day a client updates.

The keys below are the normative ones (`io.modelcontextprotocol/protocolVersion`,
`io.modelcontextprotocol/clientInfo`). `UNRECOGNISED_META` is the one that
matters if Belay's idea of those names is ever wrong: it pins the behaviour that
an unrecognised `_meta` is reported unknown **with the keys it did carry**,
rather than resolving to nothing and looking like a client that declared
nothing.

Canned raw bytes only, for the same reason as `fake_server.py`.
"""

META_REQUEST = (
    b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo",'
    b'"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",'
    b'"io.modelcontextprotocol/clientInfo":{"name":"future-client","version":"9"}}}}'
)

RESPONSE_TO_META_CALL = (
    b'{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}'
)

# `_meta` is there and carries nothing Belay knows how to read. The point is that
# this is reported unknown WITH the keys it carried, so a wrong idea about the
# key names shows up as a named gap rather than as silence.
UNRECOGNISED_META = (
    b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo",'
    b'"_meta":{"com.example/some-other-key":"whatever"}}}'
)

NO_META_AT_ALL = b'{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"echo"}}'

# W3C Trace Context in `_meta`. These three keys are reserved as an EXPLICIT
# exception to the reverse-DNS prefix rule, for OpenTelemetry propagation: trace
# context is becoming protocol-native rather than a bolt-on. Belay records them
# and does nothing else with them - they matter to a later capability (the OTel
# bridge), and interpreting them is that capability's job, not C1's.
TRACE_CONTEXT_META = (
    b'{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"echo",'
    b'"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",'
    b'"traceparent":"00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01",'
    b'"tracestate":"vendor=opaque","baggage":"key=value"}}}'
)
