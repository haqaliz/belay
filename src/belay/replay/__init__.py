"""C3: deterministic replay — restore a recorded turn's pre-state and re-execute it.

The first thing replay needs is a snapshot that outlives the process that took it.
`persist` is that: a manifest on disk that joins a trace's `state_handle` to a
restorable `clone.Snapshot`, sidecar and all.

The second is a way to read the trace back. `reader` is that: it turns a trace file
into the records C3 replays, honouring the format's unknown-kind rule — an unknown
`kind` or a newer `v` is skipped and the skip recorded, never dropped and never
fatal, so an old reader survives a new writer without hiding what it could not read.
"""
