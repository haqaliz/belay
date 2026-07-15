"""A non-conforming MCP server that emits a frame which is not valid UTF-8.

MCP says stdio messages are UTF-8. Servers are written by third parties and a
non-conforming one exists the moment someone writes a buggy one. Belay's job is
to record what actually crossed the wire, so bytes that cannot be decoded — and
therefore cannot be a JSON string at all — must round-trip through the trace
rather than crash the writer or get lossily coerced.

Kept separate from `fake_server.py` on purpose: that fixture is the differential
gate's control and must not acquire new behaviour.

Replies from CANNED RAW BYTES ONLY, for the same reason as `fake_server.py`.
"""

import sys

# 0xff can never appear in valid UTF-8. Structurally this looks like JSON, so a
# writer that assumes "parse failure means malformed JSON" and not "these bytes
# are undecodable" will still trip over it.
REPLY_INVALID_UTF8 = b'{"jsonrpc":"2.0","id":1,"result":{"text":"\xff\xfe"}}\n'

REPLY_VALID = b'{"jsonrpc":"2.0","id":2,"result":{"text":"ok"}}\n'


def main() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    for index, raw_line in enumerate(stdin):
        if not raw_line.strip():
            continue
        # Byte-for-byte canned replies keyed off arrival order, so this fixture
        # never needs to parse (and therefore never needs to decode) its input.
        if index == 0:
            stdout.write(REPLY_INVALID_UTF8)
            stdout.flush()
        elif index == 1:
            stdout.write(REPLY_VALID)
            stdout.flush()


if __name__ == "__main__":
    main()
