"""Canned `tools/list` payloads covering every annotation shape a server can emit.

Not a server — a byte bank. The annotation derivation reads trace records, so
these are fed through the real `TraceWriter` by the tests rather than spoken over
a pipe. They are canned raw bytes for the same reason `fake_server.py`'s are: a
fixture that serialised at runtime would re-normalise through the same code path
as the code under test.

The tools below are chosen so that every distinction the tri-state exists to
preserve is reachable:

- `read_file` declares `readOnlyHint: true` and declares nothing else
- `write_file` declares `readOnlyHint: **false**` explicitly
- `mystery` has **no `annotations` object at all**
- `contradictory` declares `readOnlyHint: true` **and** `destructiveHint: true`,
  which the spec makes incoherent: destructive/idempotent are "meaningful only
  when readOnlyHint == false"
- `sloppy` declares `readOnlyHint: "yes"` — present, but not a boolean

`write_file` and `mystery` are the pair the whole capability turns on. Both will
"mutate without having claimed read-only". Only one of them ever *said* so, and a
trace that cannot tell them apart lets a downstream check reason "it mutated, it
never claimed read-only, therefore fine -> PASS" about a tool that declared
nothing — a false PASS manufactured by a spec default.
"""

TOOLS_LIST_RESPONSE = (
    b'{"jsonrpc":"2.0","id":2,"result":{"tools":['
    b'{"name":"read_file","annotations":{"readOnlyHint":true}},'
    b'{"name":"write_file","annotations":{"readOnlyHint":false}},'
    b'{"name":"mystery"},'
    b'{"name":"contradictory","annotations":{"readOnlyHint":true,"destructiveHint":true}},'
    b'{"name":"sloppy","annotations":{"readOnlyHint":"yes"}}'
    b"]}}"
)

# The re-snapshot: same server, later, and `read_file` is no longer read-only.
# A single snapshot would verify every later call against this stale contract.
TOOLS_LIST_RESPONSE_CHANGED = (
    b'{"jsonrpc":"2.0","id":4,"result":{"tools":['
    b'{"name":"read_file","annotations":{"readOnlyHint":false,"destructiveHint":true}}'
    b"]}}"
)

TOOLS_LIST_REQUEST = b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
TOOLS_LIST_REQUEST_AGAIN = b'{"jsonrpc":"2.0","id":4,"method":"tools/list"}'

NOTIFICATION_LIST_CHANGED = b'{"jsonrpc":"2.0","method":"notifications/tools/list_changed"}'
