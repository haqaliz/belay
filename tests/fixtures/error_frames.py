"""Canned response frames covering both ways MCP expresses a failure.

The two are not interchangeable, and the line between them MOVED: the 2025-11-25
revision (SEP-1303) reclassified input-validation failures from protocol errors
to tool execution errors, "to enable model self-correction". So the same
underlying failure has different wire shapes depending on which revision the
server implements — which is exactly why the classification must be derived from
the bytes rather than decided at capture time and baked in.

- `PROTOCOL_ERROR` — a JSON-RPC `error` member and no `result`. The method
  failed; there is no tool output at all.
- `EXECUTION_ERROR` — a perfectly successful JSON-RPC envelope carrying a
  `result`, whose payload says `isError: true`. The call succeeded; the tool
  reported failure inside it.
- `ISERROR_ABSENT` — a result with no `isError` at all. The spec *assumes* false;
  an assumption is not a declaration.
- `ISERROR_NULL` — `isError: null`. Declared, but not as a boolean.
- `STRUCTURED_DUPLICATED` — `structuredContent` plus a text block serialising the
  same data, which servers SHOULD do and which therefore puts the same facts on
  the wire twice.

Canned raw bytes only, for the same reason as `fake_server.py`.
"""

PROTOCOL_ERROR = (
    b'{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Invalid params"}}'
)

EXECUTION_ERROR = (
    b'{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"no such file"}],'
    b'"isError":true}}'
)

ISERROR_ABSENT = b'{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"ok"}]}}'

ISERROR_NULL = (
    b'{"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"ok"}],"isError":null}}'
)

# The same object twice: once structured, once serialised into a text block.
STRUCTURED_DUPLICATED = (
    b'{"jsonrpc":"2.0","id":5,"result":{"structuredContent":{"temp":22,"unit":"C"},'
    b'"content":[{"type":"text","text":"{\\"temp\\":22,\\"unit\\":\\"C\\"}"}]}}'
)

# Structured output whose text block is NOT the same data - a summary, not a
# duplicate. Counting this as duplication would lose a real second fact.
STRUCTURED_NOT_DUPLICATED = (
    b'{"jsonrpc":"2.0","id":6,"result":{"structuredContent":{"temp":22,"unit":"C"},'
    b'"content":[{"type":"text","text":"It is warm today."}]}}'
)

MALFORMED = b'{"jsonrpc":"2.0","id":7,"result":'

# The 2026-07-28 revision requires every result to carry `resultType`
# ("complete" | "input_required"). Clients MUST treat an ABSENT resultType from
# an earlier-protocol server as "complete" — which is an assumption, not a
# declaration, so it is never materialised into the trace. Every other response
# in this file predates the field and therefore declares nothing.
RESULT_TYPE_COMPLETE = (
    b'{"jsonrpc":"2.0","id":8,"result":{"resultType":"complete",'
    b'"content":[{"type":"text","text":"ok"}]}}'
)

# `input_required` is the MRTR shape (SEP-2322): the server is asking for input,
# and the client will RETRY the original request under a NEW id carrying
# `inputResponses`. Belay records the fact; it does not model the retry chain.
RESULT_TYPE_INPUT_REQUIRED = (
    b'{"jsonrpc":"2.0","id":9,"result":{"resultType":"input_required",'
    b'"inputRequests":[{"type":"text","prompt":"Which file?"}]}}'
)

REQUESTS = {
    1: b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"a"}}',
    2: b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"b"}}',
    3: b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"c"}}',
    4: b'{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"d"}}',
    5: b'{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"e"}}',
    6: b'{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"f"}}',
    7: b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"g"}}',
    8: b'{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"h"}}',
    9: b'{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"i"}}',
}
