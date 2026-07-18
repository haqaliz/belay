"""C6: the failure corpus — moat #2, the regression suite that grows with every catch.

Every caught A1/A2 failure is stored here as a labeled, replayable CASE. A later
`belay corpus run` re-replays the whole corpus and asserts each case still reaches its
recorded verdict, so the corpus IS the regression suite: a catch that regresses breaks
the build. This package currently owns only the on-disk case FORMAT (`case.py`); the
`corpus add`/`run`/metrics commands land in later C6 phases.

Zero runtime dependencies (stdlib only), matching the rest of `src/belay`.
"""

# S1 (Phase-0 seed): deferred until the Phase-0 audit exists — there is no audited seed
# data to import yet, so no seed adapter is built.

