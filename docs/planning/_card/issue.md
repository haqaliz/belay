# Card: feat/verdict-coverage-status

**Type:** feat · **Slug:** verdict-coverage-status · **Owner:** aliz
**Branch:** feat/verdict-coverage-status/aliz (off `master`)

No GitHub issue (`gh` tracker empty). Task source: the inline brief below, produced by the
**Stage-1 re-mint of `phase0-mint-execution`** (2026-07-23). The finding is documented at
`docs/planning/phase0-mint-execution/mint-execution/STAGE1_REMINT_FINDINGS.md` §2.

## Brief

**`UNVERIFIED` is carrying two different meanings, and the second is silently consuming the
first — with the result that the Phase-0 denominator is structurally zero.**

Found by running the Stage-1 re-mint. A representative turn:

```
turn 2  read_text_file                                    UNVERIFIED
   A2 replay          PASS         replayed reply reproduced the recorded reply
   A2 effect          PASS         readOnlyHint: true honored, no filesystem mutation
   A2 effect:network  UNVERIFIED   openWorldHint: false cannot be verified
   A1 invariant       PASS         tests/ read-only respected
```

Three of four sub-verdicts PASS. The one dimension Belay **explicitly does not cover** —
network egress — drags the turn to UNVERIFIED by worst-status-wins
(`src/belay/verify/effect.py:309-325`, `src/belay/verify/turn.py:206-214`).

The reference `@modelcontextprotocol/server-filesystem` declares `openWorldHint: false` on
its tools. Therefore **every turn of every instance is permanently UNVERIFIED** — for any
user of the reference server, not merely for this mint. Every instance is
`NO_VERIFIABLE_TURNS`; the run is `INSTRUMENT SUSPECT` with denominator **0**, regardless of
what the agent does or how many instances are run.

### The two meanings

- *"We tried to verify this and could not"* — an honest abstention. (Unrestorable pre-state,
  nondeterministic tool, un-annotated contract.)
- *"This was never inside what Belay claims to check"* — a **coverage boundary**, documented
  in `README.md`'s honest-coverage limits and in the `belay verify` help text itself.

Today both are `UNVERIFIED`, and the second dominates the reduction.

### The perverse incentive (the sharpest symptom)

A server that **honestly declares** a closed network posture (`openWorldHint: false`) gets a
strictly **worse** verdict than one that stays silent — because un-annotated and
`openWorldHint: true` both return `None` and are not folded in. The more truthful the
annotation, the less Belay can verify. That is backwards, and it is a product-level argument,
not only an engineering one.

### Decided at interview (2026-07-23)

**A distinct `NOT_COVERED` status**, excluded from the worst-status-wins reduction and
surfaced prominently per-turn and in the coverage statement, so a turn reports PASS *on what
Belay actually verifies* and `UNVERIFIED` regains its honest meaning:

```
turn 2  read_text_file                                    PASS
   A2 replay          PASS
   A2 effect          PASS
   A2 network         NOT_COVERED   (never verified by Belay)
   A1 invariant       PASS

coverage: network egress NOT observed for 12/12 turns
```

**Built as its own unit, before the mint resumes** — because it touches the honesty contract
at its most load-bearing point, and `phase0-mint-execution` has already absorbed one
core-engine scope change.

### The risk to manage, stated up front

**A PASS must never read as "network verified."** This change trades a conservative,
over-broad abstention for a precise claim plus a visible coverage statement. If the coverage
statement is easy to miss, this change makes Belay *less* honest, not more. The discipline
this needs is the one the A3 `--no-claim-axis` guarantee gets:

- a test asserting `NOT_COVERED` can **never** be rendered, reduced, or summarized as PASS;
- a test asserting **every existing PASS / FAIL verdict survives unchanged**;
- the coverage statement is **not suppressible** and travels with the verdict wherever it is
  rendered (CLI, ledger, corpus case, phase0 report).

### Also in scope (found by the same run, both small)

1. **Named causes are bucketed as `unknown`.** Each UNVERIFIED turn carries a long, precisely
   named cause, yet `belay phase0 report` prints `unknown: 12`. The Phase-0 gate requires
   every UNVERIFIED to trace to a **named cause**, so this is a gate blocker independent of
   the `NOT_COVERED` work.
2. **`belay phase0 run --ledger runs/x.json` crashes with `FileNotFoundError`** when the
   parent directory does not exist (`src/belay/cli.py:1067`) — *after* completing the entire
   verification run, discarding all of it.

## Why this blocks the mint

`phase0-mint-execution` is paused at Stage 1. Its aspects 1-3 are merged; aspects 4
(`mint-execution`) and 5 (`audit-and-publish`) cannot produce a number until a turn against
the reference server can be verified at all.
