"""A fake MCP server that answers the FIRST request, then exits mid-conversation.

For the replay client's "the server dies while we are still talking to it" case.
The client must return what it already read, plus a NAMED failure for the frame
that never got its reply — never hang, and never raise something that loses which
frame was in flight when the pipe closed.

So this replies once and leaves: the next frame the client sends finds the read
end gone. Stdlib only, deterministic, no network, no sleeps.
"""

import json
import sys


def main() -> None:
    stdout = sys.stdout.buffer
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        msg_id = message.get("id")
        if msg_id is not None:
            # A minimal, well-formed response so the first frame is genuinely
            # answered — the client must distinguish "died after answering one"
            # from "died before answering anything".
            stdout.write((json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {}}) + "\n").encode("utf-8"))
            stdout.flush()
        # Leave now, whatever it was: the conversation dies here on purpose.
        return


if __name__ == "__main__":
    main()
