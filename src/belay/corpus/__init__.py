"""C6: the failure corpus — moat #2, the regression suite that grows with every catch.

Every caught A1/A2 failure is stored here as a labeled, replayable CASE. `belay corpus run`
re-replays the whole corpus and asserts each case still reaches its recorded verdict, so the
corpus IS the regression suite: a catch that regresses breaks the build.

What lives here: the on-disk case FORMAT (`case.py`), composition (`add.py`), re-verification
and outcome classification (`run.py`), human labeling (`curate.py`), and precision/recall
scoring against those labels (`metrics.py`).

A case is not only a catch. A case may DECLARE that its stored verdict records a MISS — the
engine returned clean on a turn a human adjudicated a real violation, so the clean verdict IS
the defect. That declaration is a human act and there is no code path from a verdict, a status
or a label to setting it, exactly as the engine never labels its own cases. `run.py` therefore
reports `STILL_MISSED` rather than `MATCH` on a case the engine still misses, and `MISS_CLOSED`
rather than `REGRESSION` when a sharpened detector starts catching it. Read a green run as
"no case regressed" and nothing more.

Note the asymmetry that a reader keeps guessing wrong: `belay phase0 run` ingests FAIL turns
and nothing else, so a MISS never arrives by the bulk path — but composition here has never
enforced any precondition on the recomputed verdict, so pointing `belay corpus add` at a turn
the engine verified clean is how a miss gets in at all.

Zero runtime dependencies (stdlib only), matching the rest of `src/belay`.
"""

# S1 (Phase-0 seed): deferred until the Phase-0 audit exists — there is no audited seed
# data to import yet, so no seed adapter is built.

