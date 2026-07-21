"""A fake MCP server that reads requests and never replies, but stays alive.

For `StdioMcp.request`'s TIMED_OUT path specifically: the process does NOT
exit (no EOF on its stdout), so a bounded wait must return via the deadline
alone, distinctly from the EOF-triggered error `minting_driver_silent_exit_
server.py` exercises. Stdlib only, deterministic, no network, no sleeps.
"""

import sys


def main() -> None:
    for _ in sys.stdin.buffer:
        pass  # read and discard forever; never write a reply


if __name__ == "__main__":
    main()
