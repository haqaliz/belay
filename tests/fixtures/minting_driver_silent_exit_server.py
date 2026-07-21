"""A fake MCP server that reads one request and exits without ever replying.

For `StdioMcp.request`'s "the process is gone before an awaited reply arrives"
case: stdout hits EOF, and the transport must surface that as an explicit,
named error — never a silent hang and never a mistaken match against garbage.
Stdlib only, deterministic, no network, no sleeps.
"""

import sys


def main() -> None:
    for raw_line in sys.stdin.buffer:
        if raw_line.strip():
            return  # read exactly one request, then leave without replying


if __name__ == "__main__":
    main()
