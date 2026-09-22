# HAND_REPLAY — run 2

> **This is not a gate run, it produces no Phase-0 number, and it is not a result
> about agents.**

## No FAIL exists, so no FAIL was hand-replayed

The pre-registered guard replays one FAIL end-to-end, so that a flag is known to be
a real state delta and not a wiring artifact. Run 2 produced **zero** FAILs: 0 per-turn,
0 trajectory, 0 A3 (`FLAGS.md`). There is nothing for the guard to check. This file
does not substitute an UNVERIFIED turn for a FAIL, because replaying an abstention would
not test what the guard tests.

## What was re-executed instead, and what it shows

`belay corpus run` re-executed the 7 **pre-existing** corpus cases under v0.37.0: 7/7
MATCH, 0 REGRESSION, 0 SKIP (`corpus-banking/acceptance-cm-run2-corpus-run-stage1.out`).
That shows the replay → verdict path still reproduces banked verdicts on this machine.
It does **not** show anything about the run-2 captures, which contributed no case.

## When this file gets its first real content

It gets real content from the first run whose stage produces a FAIL. Under the current
engine that needs the composite-transport correlation fix first (AUDIT.md, decision
line).
