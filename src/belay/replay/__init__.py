"""C3: deterministic replay — restore a recorded turn's pre-state and re-execute it.

The first thing replay needs is a snapshot that outlives the process that took it.
`persist` is that: a manifest on disk that joins a trace's `state_handle` to a
restorable `clone.Snapshot`, sidecar and all.
"""
