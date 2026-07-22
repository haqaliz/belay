"""The Phase-0 instance registry: the mint set as committed data, not prose.

`eval/instances.md` is hand-written prose with a single entry; a 50-instance mint cannot
be driven from prose. This package holds the machine-readable replacement: the record
type and its fail-closed I/O (`registry`), and — as later phases land — the deterministic
task-string derivation and the stratified draw that selects which instances get minted.

Eval-only, like everything under `eval/`: never imported from `src/belay`, never shipped
in the `belay-harness` wheel. It emits no verdicts and touches no verdict axis; it only
supplies inputs to a later capture.
"""
