"""A claim-author stub that returns a valid check: `argv[1]` is its source, the rest its argv.

The caller passes a check that exits 0 in the materialized final state, so the axis RUNS
and is silent (D3) — Belay must emit `claim_silence` and no `claim`.
"""

import json
import sys

sys.stdin.read()
print(json.dumps({"source": sys.argv[1], "argv": sys.argv[2:]}))
