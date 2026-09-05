# Brief: the trace-ordering race (proxy recording)

Source: `CLAUDE.md` L3 block (docker-selfhost findings) and
`docs/planning/docker-selfhost/` — a documented engine follow-up, not a GitHub issue.

## The defect

`_pump` (the proxy's forwarder) forwards each chunk and observes it afterwards —
"forwarding must never wait on the recorder" is the transparency contract. A fast
server can therefore have its `tools/list` RESPONSE recorded before its own REQUEST.
An inverted pair does not correlate, `derive_annotations` takes no snapshot, and
effect-conformance abstains.

## The current mitigation (not a fix)

The fixtures close the window by waiting on the trace itself, no sleep (40/40 stress,
from 18/20). The degradation is honest — UNVERIFIED, never a false PASS — and the
engine was left UNCHANGED at L3 time.

## What this unit must deliver

A fix in the engine so a REQUEST frame is always recorded before the RESPONSE that
follows it, WITHOUT violating the transparency contract (forwarding must never wait on
the recorder) — i.e. the fix must not serialize the data plane behind the recorder.

Acceptance: the inverted-pair defect shape is closed by a test that reproduces the race
(no sleep-based waiting), all existing suite stays green, and the honest-degradation
contract (UNVERIFIED never PASS) is unchanged.