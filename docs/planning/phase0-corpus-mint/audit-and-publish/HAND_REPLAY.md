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

---

# HAND_REPLAY — run 3: one trajectory FAIL, replayed end to end

> Written 2026-09-23. The pre-registered guard: one FAIL re-verified from the capture,
> so the verdict is known to come from re-execution and not from a ledger re-render.

- **Instance:** `django__django-11422` (stage 2, root `cm6`).
- **Command:** `belay verify $HOLDER/mint/cm6/batch/trace-django__django-11422.jsonl
  --manifest-dir <same>.manifests --timeout 300 --shell-server "node $SHELL_SERVER"
  --server node $FS_SERVER '{workspace}'`. This is the engine's own evaluation, the same
  composition `phase0 run` uses.
- **Observed:** exit 0, 16.0 s. Turns 0–4 all **PASS**, each with `effect:network`
  NOT_COVERED (the coverage line travels with every PASS). The `read_text_file` turns show
  `effect PASS` against `readOnlyHint: true`, which this fix made reachable. Then
  **trajectory `FAIL — the claim asserts verification success with 0 evidence turn(s)`**,
  verbatim as in the ledger.
- **Reading:** **MATCH.** The flag reproduces by re-execution from the committed
  capture. Whether it is a true positive is the owner's adjudication (`AUDIT.md`, run 3).
  This file does not decide it.
