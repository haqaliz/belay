"""Eval-only tools for Belay: NOT part of the shipped `belay` package.

Everything under `eval/` drives the product from the outside (through the MCP proxy) to
produce measurement data — it never ships in the `belay-harness` wheel and is never
imported from `src/belay`. See `eval/minting_driver/` for the Phase-0 minting driver.
"""
