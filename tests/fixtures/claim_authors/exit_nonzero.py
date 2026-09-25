"""A claim-author stub that fails the way a crashing author does: exit 1, a named stderr line.

Reads the prompt (so the pipe never breaks), writes a traceback-shaped tail to stderr, and
exits 1 — Belay must record `AUTHOR_EXITED_NONZERO` with the LAST non-empty stderr line.
"""

import sys

sys.stdin.read()
sys.stderr.write("working on the claim...\nAuthorTimeoutError: the model did not answer\n")
sys.exit(1)
