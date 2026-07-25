"""The Phase-0 instance registry: the mint set as committed data, not prose.

A 50-instance mint cannot be driven from prose, so the mint set lives here as data: the
record type and its fail-closed I/O plus the optional provenance header (`registry`), the
deterministic task-string derivation (`tasks`), the stratified draw (`selection`), and the
three hand-written control instances that check the instrument (`controls`).

Two committed artifacts sit beside them and are the actual inputs to a mint:
`pool.json` — every strict-eligible SWE-bench-lite instance, written by the human-run
`eval/scripts/fetch_swebench_pool.py` — and `selected.json`, the 68-record launched set
(65 drawn at `seed=20260723`, plus the 3 controls) written by the pure, offline
`eval/scripts/draw_mint_set.py`. Both carry a provenance header that
`tests/test_eval_mint_set.py` checks against the records in the same file, and the draw is
reproducible from `(pool, target, seed)` byte-for-byte. `eval/instances.md` documents the
filters, the composition, the seed's no-silent-re-roll rule, and the control design.

Eval-only, like everything under `eval/`: never imported from `src/belay`, never shipped
in the `belay-harness` wheel. It emits no verdicts and touches no verdict axis; it only
supplies inputs to a later capture.
"""
