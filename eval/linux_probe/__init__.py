"""The Linux containment spike probe: measurement-only, eval-only.

Runs on the `spike-linux` CI job (pinned `ubuntu-24.04`) and writes
`probe_result.json` — the machine-readable evidence the containment-spike
decision (`docs/planning/linux-sandbox/containment-spike/`) cites. This tree
is NOT part of the `belay-harness` wheel and never touches `src/belay`.
"""
