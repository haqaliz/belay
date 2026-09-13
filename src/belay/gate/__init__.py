"""The ci-regression-gate: bank a run's expected verdicts, then gate re-verifies.

What lives here: the baseline STORE (`bank.py` — the on-disk baseline.json format,
the fail-closed loader, and the self-contained artifact copy) and the bank command
(`baseline.py` — verify a capture and compose its baseline). `check.py` (the gate
half: re-verify a run against its banked baseline) lands in aspect 3.

A baseline is the run's own expected verdict set, keyed by run id, bundled with the
trace, manifests and snapshot trees so it survives deletion of the original run —
the record the gate diffs a re-run against. Zero runtime dependencies (stdlib
only), matching the rest of `src/belay`.
"""