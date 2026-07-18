"""Phase-0: run the failure corpus at scale and publish the violation-rate number.

This package builds the run ledger — the data model a later phase fills by verifying
traces and folding each instance's outcome into a `RunLedger`. No verify, no corpus
wiring, no CLI lives here yet; see `belay.phase0.ledger`.
"""
