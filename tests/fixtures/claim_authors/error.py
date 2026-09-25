"""A claim-author stub that reports its own error — `{"error": ...}` on stdout, exit 0.

Belay must record `AUTHOR_REPORTED_ERROR` with the error string as the detail.
"""

import json
import sys

sys.stdin.read()
print(json.dumps({"error": "model declined: no executable check for this claim"}))
