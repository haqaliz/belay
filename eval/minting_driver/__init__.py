"""The Phase-0 minting driver: a minimal sequential MCP agent loop, eval-only.

Drives ≥50 SWE-bench-lite instances through Belay's MCP proxy to produce the corpus data
`belay phase0 run/report` measures. Pure orchestration outside the product boundary — it
is a *client* of the proxy, never a modification to `src/belay`. Zero third-party
dependencies (stdlib only), matching the rest of this repo's dependency discipline.
"""
