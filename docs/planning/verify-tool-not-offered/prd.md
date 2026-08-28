# PRD — `verify-tool-not-offered`

> **A2 result-equivalence must not FAIL a turn whose tool the replay boundary never
> offered.** Branch `feat/verify-multi-server-seam/aliz` (the branch name predates the
> scoping decision; the shipped scope is narrower than "multi-server" and this slug
> describes what ships).
>
> **Status:** PRD for review. Written 2026-08-28 from `docs/planning/_card/issue.md` and
> `docs/planning/_card/understanding.md`. Every factual claim is cited; the reproduction is
> verbatim, not paraphrased.

---

## Problem statement

`belay verify` emits a confident **FAIL** on turns it never actually verified.

When a replay server does not offer a recorded tool, it answers **readably** — the reply
parses, and it reproduces identically on every replay. So the turn takes the
`DIVERGED + DETERMINISTIC -> FAIL` branch (`src/belay/verify/result.py:18`) rather than
degrading to UNVERIFIED.

**Reproduced live**, from a clean checkout of this worktree, against the **committed demo
capture** (`demo/capture/trace-20260827T001428Z-e23f999d.jsonl` — a real `claude -p` run,
not a fixture), replayed against a filesystem-only variant of `demo/server.py`:

```
result-equivalence FAIL on deterministic tool 'run_process': the trace recorded
{... 'text': '... 4 passed, 2 failed'}], 'isError': False}} but replay
deterministically reproduced {... 'text': "no such tool: 'run_process'"}], 'isError': True}}
```

`"turns_verified": 1, "PASS": 0, "FAIL": 1, "UNVERIFIED": 0`, exit code **1**.

The recorded turn genuinely succeeded (`isError: false`, a real test-suite run). Belay
reports it as a deterministic failure of the agent's tool call. **That is a fabricated
verdict**, and it is the loudest kind: a FAIL is what a reader acts on.

### Why the existing machinery did not catch it

- The engine **names this exact mechanism** and asserts it is dormant
  (`src/belay/verify/turn.py:275-278`): *"a rooting/spawn failure is promoted into a
  confident FAIL (DIVERGED + DETERMINISTIC -> FAIL, `verify/result.py`) ... This is LATENT,
  not live."* For the tool-not-offered shape it is **live**.
- The prior dual-server aspect's honesty criterion
  (`docs/planning/phase0-gate-mint/verify-dual-server/spec.md`, AC-5) covered two shapes —
  a turn that *"replays with an unreadable outcome"* and one that *"cannot replay at all"*.
  A tool-not-offered reply is **neither**: it is readable **and** it replays. The hole sits
  precisely between AC-5's two clauses.

### Evidence it is real, and its measured scale

The 2026-08-12 gate mint recorded **171 per-turn FAILs, all of them this artifact**
(`docs/planning/mint-shell-toolset-run/audit-and-publish/AUDIT.md:10`, hand-verified on
`django-12125` turn 8). **Read that number with its caveat:** dual-server routing landed
two days later in `9138cea` (2026-08-14), so those 171 are historical and predate the
routing fix. They are evidence that the shape occurs at scale in real runs — **not** a
live count today.

## Goals & success metrics

| # | Goal | Measured by |
|---|---|---|
| G1 | A turn whose tool the replay boundary does not offer is **UNVERIFIED with a named cause**, never a result-equivalence FAIL | The reproduction above re-run: `FAIL: 1` becomes `UNVERIFIED: 1` with a named cause; exit code and coverage line correct on every surface |
| G2 | **A2 loses no detection power** — a genuine deterministic divergence still FAILs | A regression test per divergence shape: value mismatch, isError-vs-success where the tool IS offered |
| G3 | `belay verify` can route a shell turn, as `phase0 run` already can | `belay verify --shell-server` exists; the demo capture verifies its `run_process` turns to a real PASS/FAIL |
| G4 | The count "turns unverifiable because the boundary lacked the tool" becomes measurable | A distinct bucket in `phase0 report`'s UNVERIFIED-by-cause table |
| G5 | No published number moves, and no verdict axis other than A2 changes | Stated in the PR; trajectory verdicts pinned unchanged by test |

**Non-goal metric:** this unit does not aim to *increase* PASS counts. It converts false
FAILs into honest abstentions. **The UNVERIFIED rate rises by design** (risk **R7**).

## Users & scenarios

Belay's ICP — an engineer running an agent unattended who must answer *"did this run
actually do the right thing?"*

- **Today:** they run `belay verify` against a trace captured from an agent with more than
  one MCP server (the normal configuration). Every turn belonging to a server they did not
  pass to `--server` reports FAIL. They cannot distinguish that from a real failure without
  reading the sub-verdict text and knowing the engine's internals.
- **After:** those turns read UNVERIFIED with a cause that names the reason, and the
  operator can either add `--shell-server` and get a real verdict, or accept the documented
  coverage gap knowingly.

## Requirements

### Must-have

- **M1 · Positive evidence of absence.** The engine decides "this boundary does not offer
  this tool" by **asking the boundary** — a `tools/list` probe against the same resolved
  server command — never by matching error text and never by inferring from `isError`.
  - *Rationale, load-bearing:* `isError: True` is also what a tool that genuinely ran and
    failed returns (`_replayed_is_error`, `src/belay/verify/turn.py:131`). Error text is
    server-specific: the demo server says `no such tool: 'run_process'`; the node reference
    server says `MCP error -32602: Tool run_process not found`. Text matching would be
    exactly the heuristic this project refuses.
- **M2 · Lazy, gated on DIVERGED.** The probe runs **only** when the engine is about to
  emit a result-equivalence FAIL. A non-diverged turn costs nothing and its code path is
  untouched.
- **M3 · Fail-closed vocabulary.** Offered by exactly one configured server -> the FAIL
  stands (a real divergence). Offered by **none** -> UNVERIFIED with a named cause. Offered
  by **two or more** -> UNVERIFIED with a named cause. **Never a guess.**
- **M4 · Probe failure is not evidence.** If the probe itself cannot run (spawn failure,
  timeout, unparseable reply), the engine must **not** conclude "not offered". It reports
  UNVERIFIED with a distinct cause naming the probe failure. Absence of evidence is never
  evidence of absence.
- **M5 · A2 detection power preserved.** A genuine deterministic divergence on a tool the
  boundary **does** offer still FAILs, unchanged. Pinned by regression test.
- **M6 · `belay verify --shell-server`.** Parity with `belay phase0 run --shell-server`
  (`src/belay/cli.py:2561`), same single-quoted-string shape and same fail-closed
  `shlex.split` (`--server` is `nargs=REMAINDER` and cannot host a second remainder —
  `src/belay/cli.py:1770`).
- **M7 · Closed-set registration.** The new cause is a **module-level `REPLAYED_*` constant
  in `src/belay/replay/report.py`** and is added to `_REPLAYED_CAUSES`
  (`src/belay/interop/attach.py:81`).
  - *Trap the plan must state:* the guard test
    (`tests/test_interop_attach.py:475`) reflects over `REPLAYED_*` names in `report.py`. A
    cause hand-built inline elsewhere is **invisible to the guard** and would be silently
    misreported by C9 as `unrestorable-pre-state` — asserting a snapshot-restore failure
    that never happened. This is the `interop-merge-repair` bug class.
- **M8 · `_PREFIX_LABELS` ordering.** `canonical_cause` returns the **first** prefix match
  (`src/belay/replay/report.py:111-142`); the new label must be ordered so it cannot be
  shadowed by, or shadow, an existing prefix.
- **M9 · The cause renders on every surface** — `verify` text, `verify --json`,
  `corpus show`, `interop correlate` (text + `--json`), `phase0 report`, and the console —
  with its coverage line, mirroring `tests/test_coverage_rendering.py`'s per-surface
  structure.
- **M10 · README limits subsection.** *"Coverage & limits, stated exactly"* has 12
  subsections and **none** states the replay-boundary/server limit. Add one.

### Should-have

- **S1 · Finding fix: corpus recompute gap.** `corpus/run.py:run_case` (`:522`) and
  `_recompute_trajectory_case` (`:478`) pass only `case.server_command` and never thread
  `shell_server_command`, so a trajectory case whose original run routed `run_process`
  turns to a shell server silently recomputes them against the stored fs command. Latent
  today (the rule reads `records`, not per-turn replay outcomes) — a landmine.
- **S2 · Finding fix: broadcast-id collision.** `composite._broadcast` sends `initialize`
  and `tools/list` to every session with the **same JSON-RPC id**; after
  `merge_session_traces`, `derive_correlation` keys pending requests on
  `(direction, type(id), id)` with **no session component** (`src/belay/index.py:75`,
  `:140`), so the second session's request **evicts** the first and a reply can pair against
  the wrong request. **Untested** — `tests/test_minting_driver_trace_merge.py:215` covers
  only unique-id `tools/call` turns.
  - **Honest limit, stated up front:** this **cannot be validated against the real merged
    mint data** — the s6 captures no longer exist (see *Constraints*). It will be pinned by
    a **constructed two-trace fixture with colliding ids**, which is a legitimate test but
    is not a replay of history.

### Nice-to-have

- **N1** A `phase0 report` line surfacing the new bucket prominently, so a future mint sees
  instrument artifacts separated from violations without a hand audit.

## Technical considerations

- **Capability:** C4 (A2 replay verdict), with a CLI-parity slice touching C3's surface.
  Not a new capability — a correctness fix inside a built one.
- **Verdict axis: A2 only.** This changes when result-equivalence may emit FAIL vs
  UNVERIFIED. **A1 is untouched** (no invariant, scope, or weakening logic). **A3 is
  unbuilt.** No new status: `NOT_COVERED` is *not* involved — this is *"we tried to check
  and could not"* (UNVERIFIED), not *"we have no instrument"* (NOT_COVERED).
- **The trajectory axis must not move.** Confirmed decision: `replayed_is_error` stays
  exactly as today (`True` on such a turn), which the trajectory rule already treats as
  not-evidence. Because the turn still **replays** under the lazy design, nothing upstream
  of the scoring changes. **Pinned by test: no trajectory verdict may move.**
- **C9 impact is small by construction.** A lazily-rescored turn still replayed, so its
  bucket stays a `REPLAYED_*` cause — the existing dichotomy in `attach.py:172-177` holds
  and needs no third bucket. (An *eager* probe that skipped the re-invoke would have
  required one; that design was rejected.)
- **The probe must not enter the replayed conversation.** `replay_turn` sends only the
  recorded frames through `converse` (`src/belay/replay/client.py:341-400`); injecting a
  `tools/list` would change what the server is sent. The probe is a **separate contained
  spawn**, cached per resolved server command per run.
- **Cost.** Today a fresh server process is spawned **per turn**, plus `--replays` more on
  a DIVERGED reply (`client.py:36-38`). One cached probe on would-be-FAIL turns is small
  against that baseline.

### Explicitly NOT built on trace-derived routing

The trace **cannot** attribute a turn to a server. `src/belay/proxy.py` is a byte pump for
one client↔server pipe; `TRACE_FORMAT.md:191` states it: *"one open pipe to one server
process — nothing more."* The eval-only composite runs N separate proxies and
`merge_session_traces` **renumbers `seq`, adds no origin tag, and deletes the originals** —
provenance is destroyed by the merge because none was ever recorded. Probing the live
boundary sidesteps this entirely, and asks the more honest question.

## Risks & open questions

| Risk | Reading |
|---|---|
| **Over-broad discriminator guts A2** | The single most dangerous outcome, and the one a reviewer should attack first. Mitigated by M1 (positive evidence only), M4 (probe failure ≠ absence) and M5 (regression tests per divergence shape). |
| **R7 — UNVERIFIED dominance** | The UNVERIFIED rate rises by design. Honesty, not regression — but it must be said wherever reported, never presented as an improvement. |
| **R5 — over-claiming what A2 proves** | This unit *retires* a concrete instance of R5: a FAIL that claimed more than replay checked. |
| Probe adds a spawn on would-be-FAIL turns | Accepted; small against a per-turn spawn baseline. Measure and report, do not assume. |
| S2 cannot be validated on real data | Stated, not hidden. Fixture-pinned only. |

**Open questions for review:**

1. Cause naming. Proposed: `REPLAYED_TOOL_NOT_OFFERED` (boundary lacks the tool) and a
   distinct one for M4's probe failure. Names are load-bearing — they appear in the
   `phase0 report` table and in C9 output.
2. Should M4's probe-failure cause be a **separate** bucket from M3's ambiguity cause, or
   is one "could not decide the boundary" bucket enough? (Separate is proposed; it costs
   little and the two mean different things.)
3. Does `belay replay` / `corpus add` / `interop correlate` need `--shell-server` too, or
   is `verify` parity sufficient for this unit? (Proposed: `verify` only; the rest is
   deliberate scope.)

## Constraints on what may be claimed

- **The s6 mint captures NO LONGER EXIST.** They lived under
  `.claude/worktrees/feat-mint-shell-toolset-run/eval/mint/s6{a,b,c}/batch/`, a worktree
  since removed; the holder backup has `s1, s1b, s1p, s2, s3, live-smoke-claude-cli` and
  **no `s6`**. `trace-django__django-12125.jsonl` is unreachable. **No acceptance criterion
  may promise re-verifying the mint**, and the 171 FAILs cannot be recomputed.
- **Reclassification discipline** (precedent: `trajectory-toolset-rescope`,
  `CHANGELOG.md:339`): this is *a reclassification, never improved detection*.
  **`11/60 = 18.3%`, the 11 hand-audited TPs, `precision 0.00`, `1/15`, `4/16` stand
  UNEDITED.**
- A newly-verifiable turn is **evidence for the owner to re-adjudicate**, never a verdict
  this unit re-decides.

## Out of scope

- **N-server routing / a general tool→server routing table.** Deferred once already, on
  purpose (`verify-dual-server/spec.md`: *"the map shape must not over-abstract"*).
  Replacing the two hardcoded `tool_name == "run_process"` branches
  (`src/belay/verify/turn.py:239`, `src/belay/phase0/runner.py:107`) is a separate unit.
- **Any trace-format change**, including a server-provenance field.
- **Capture-side multiplexing** — `src/belay/proxy.py` is single-server by construction.
- **A new CLI flag shape for repeatable servers** (`--server` is `REMAINDER`).
- **Console multi-server support** and its separate `EngineErrorCause` union
  (`console/src/server/types.ts:103-110`) — not to be conflated with engine causes.
- **Corpus case-format change.** Schema v4 stores one resolved command and stays that way.
- Any change to A1, the trajectory rule, the claim classifier, or the verdict vocabulary
  beyond adding one UNVERIFIED cause (plus M4's).
- Re-deriving, re-editing or re-adjudicating any published Phase-0 number.
