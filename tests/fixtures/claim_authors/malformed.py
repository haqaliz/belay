"""A claim-author stub whose stdout is not JSON — Belay must record `AUTHOR_OUTPUT_MALFORMED`."""

import sys

sys.stdin.read()
print("this is not json")
