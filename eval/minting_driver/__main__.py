"""`python -m eval.minting_driver` — the documented mint command's entry module.

Three lines on purpose: all argv handling lives in `cli.py`. The `main()` call is guarded
by the `__name__` check so importing this module (a test does, to prove the wiring) never
runs a mint.
"""

from __future__ import annotations

from eval.minting_driver.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
