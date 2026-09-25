"""A claim-author stub that never answers in time: it sleeps past Belay's author timeout.

`argv[1]` is the sleep in seconds (default 90, past `AUTHOR_TIMEOUT` = 60 s) — Belay must
kill it and record `AUTHOR_TIMED_OUT`.
"""

import sys
import time

sys.stdin.read()
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 90.0)
