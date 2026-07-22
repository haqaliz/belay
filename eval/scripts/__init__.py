"""Eval-only maintenance scripts that produce the committed Phase-0 mint data.

Two kinds of thing live here and the difference is the whole point:

* the **fetch** (`fetch_swebench_pool`) touches the network exactly once, in `main()`,
  and is run **by a human**; its output (`eval/instances/pool.json`) is committed, so
  nothing downstream — and no test — ever reaches the dataset server;
* everything else is pure and offline, so it can run in CI.

Like the rest of `eval/`, this package is never imported from `src/belay` and is not
shipped in the `belay-harness` wheel. It emits no verdicts and touches no verdict axis;
it only supplies inputs to a later capture.
"""
