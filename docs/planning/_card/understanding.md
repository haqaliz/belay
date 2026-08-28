# Phase 2 — Understanding note

**Unit:** `verify-multi-server-seam` · branch `feat/verify-multi-server-seam/aliz`
**Written:** 2026-08-28. Every claim below is cited; anything not cited is marked as an
open question, not asserted.

---

## 1 · The pick's premise was partly WRONG, and the correction narrows the unit

The `belay-next` brief said *"`belay verify --server` takes ONE server command."* At the
**replay** layer that is true (`src/belay/replay/client.py:341`,
`src/belay/replay/engine.py:412` — one `server_command` per call). At the **verify** layer
it is false: **dual-server routing already shipped.**

- `verify_turn(shell_server_command=...)` with an explicit "Server routing rule"
  (`src/belay/verify/turn.py:210`, `:225-231`): a turn whose tool name is exactly
  `_EVIDENCE_TOOL` (`run_process`) replays against the shell command; everything else
  against `--server`.
- `belay phase0 run --shell-server CMD` (`src/belay/cli.py:2561`).
- Landed in `9138cea` (2026-08-14) — **two days AFTER** the 2026-08-12 gate mint.
- Designed in `docs/planning/phase0-gate-mint/verify-dual-server/spec.md`.

**Consequence for the record:** the mint's **171 per-turn FAILs** are an artifact of a run
that predates this routing. They are historical. This unit does **not** re-derive them, and
**cannot** — see §5.

## 2 · What is ACTUALLY still broken (both reproduced/verified in-tree)

### Gap A — the honesty hole (load-bearing)

A replay whose server does not offer the recorded tool answers **readably**: the reply
parses, and it reproduces deterministically. So it takes the
`DIVERGED + DETERMINISTIC -> FAIL` branch (`src/belay/verify/result.py:18`) instead of
degrading to UNVERIFIED.

**Reproduced live on the committed demo capture** (not the mint's, not synthetic —
`demo/capture/trace-20260827T001428Z-e23f999d.jsonl`, a real `claude -p` run), verified
against a filesystem-only variant of `demo/server.py`:

```
result-equivalence FAIL on deterministic tool 'run_process': the trace recorded
{... 'text': '... 4 passed, 2 failed'}], 'isError': False}} but replay
deterministically reproduced {... 'text': "no such tool: 'run_process'"}], 'isError': True}}
```
`"FAIL": 1, "UNVERIFIED": 0`, exit code 1.

This is a **false FAIL on the user-facing path, reproducible today from a clean checkout.**

The engine already NAMES this mechanism as a known sharp edge and asserts it is dormant —
`src/belay/verify/turn.py:275-278`: *"a rooting/spawn failure is promoted into a confident
FAIL (DIVERGED + DETERMINISTIC -> FAIL, `verify/result.py`) ... This is LATENT, not live."*
It is live for the tool-not-offered shape.

**Why the prior aspect missed it.** `verify-dual-server/spec.md` AC-5 covered exactly two
shapes — a shell turn that *"replays with an unreadable outcome"* and one that *"cannot
replay at all"*. The tool-not-offered reply is neither: it is **readable and it replays**.
The hole sits precisely in the gap between AC-5's two clauses.

### Gap B — `belay verify` never got the routing

`belay verify --help` (verbatim, current): `[--server ...]` and no `--shell-server`. The
engine supports routing; the documented user-facing command cannot reach it. Only
`phase0 run` (the batch/eval surface) has the flag.

`tests/test_phase0_dual_server.py:14` records why: *"The CLI `--shell-server` flag is Phase
3 of the aspect"* — the parity work was planned for the batch runner and never extended.

**Precedent, same defect class:** the L7 work found `belay verify` lacked the `--timeout`
that `corpus add` / `phase0 run` / `interop correlate` already had (CLAUDE.md, L7 block).
`verify` lagging the other surfaces' flags has now happened twice.

### Gap C — routing is hardcoded and non-general

Routing keys on the exact literal tool name `run_process` and admits exactly two servers
(`src/belay/verify/turn.py:239-241`). A third server, or a shell server exposing a
different tool name, still produces the Gap-A false FAIL. The prior spec declared this out
of scope deliberately and correctly for the mint boundary:

> *"Per-tool routing for any tool other than `run_process` (the mint boundary has exactly
> two servers; the map shape must not over-abstract)."*

Whether to generalize now is a **scope question for the PRD**, not a settled defect.

## 3 · The discriminator — the one genuinely hard design decision

"The replay server does not offer this tool" must be decided by **evidence**, not a guess.

- **`isError: True` is NOT the discriminator.** A tool that genuinely ran and failed also
  returns `isError: True` (`_replayed_is_error`, `src/belay/verify/turn.py:131`). Using it
  would convert real FAILs into abstentions — destroying A2's detection power, the opposite
  of the goal.
- **Error-text matching is NOT acceptable.** The demo server says `no such tool:
  'run_process'`; the node reference server says `MCP error -32602: Tool run_process not
  found`. A text/regex match is a server-specific heuristic of exactly the kind this
  project refuses.
- **Proposed: ask the boundary what it offers.** Probe each configured replay server's live
  `tools/list` and build a routing table `tool_name -> [servers]`. Deterministic,
  server-agnostic, no text matching, and it mirrors the idiom `belay sandbox check` already
  uses ("decides the boundary by USING it").

**Constraint on the probe.** `replay_turn` sends only the recorded frames through
`converse` (`src/belay/replay/client.py:341-400`); injecting a `tools/list` into that
conversation would change what the server is sent and break the byte-identical regression
requirement. So the probe must run **once per server per verify run, cached, in its own
contained spawn** — never inside a turn's replay.

**Fail-closed vocabulary this implies:** offered by exactly one server -> route there;
offered by **none** -> UNVERIFIED with a named cause; offered by **two or more** ->
ambiguous -> UNVERIFIED with a named cause, never a guess.

**Anti-overreach invariant (mirrors `trajectory-toolset-rescope`'s "usage is proof of
offering"):** a turn whose tool the replay server *did* answer must never be
UNVERIFIED-by-tool-not-offered. The new cause requires positive evidence of absence.

## 4 · Verdict-axis placement

**A2 only.** This changes when result-equivalence may emit FAIL versus UNVERIFIED. It does
**not** touch A1 (no invariant, scope or weakening logic), does not touch A3 (unbuilt), and
adds no new status — `NOT_COVERED` is not involved, because this is *"we tried to check and
could not"* (UNVERIFIED), not *"we have no instrument"* (NOT_COVERED).

Guardrail check (CLAUDE.md): no agent framework, no LLM judge, no raw-data egress, no
UNVERIFIED-rendered-as-PASS. The change moves verdicts *toward* honesty (FAIL -> UNVERIFIED),
never away.

## 5 · Hard constraints on what may be claimed

- **The s6 mint captures NO LONGER EXIST.** They lived under
  `.claude/worktrees/feat-mint-shell-toolset-run/eval/mint/s6{a,b,c}/batch/`, a worktree
  since removed; the holder backup (`~/dev/at/holder/belay/mint/`) has `s1, s1b, s1p, s2,
  s3, live-smoke-claude-cli` and **no `s6`**. `trace-django__django-12125.jsonl` is not
  reachable anywhere. **No acceptance criterion may promise re-verifying the mint**, and the
  171 FAILs cannot be recomputed.
- **Reclassification discipline** (the precedent `trajectory-toolset-rescope` set,
  CHANGELOG.md:339): this is *a reclassification, never improved detection*. **`11/60 =
  18.3%`, the 11 hand-audited TPs, `precision 0.00`, `1/15`, `4/16` stand UNEDITED.**
- The UNVERIFIED rate **rises** by design (risk **R7**). That is honesty, not regression,
  and must be stated wherever it is reported.
- Any newly-replayable turn is **evidence for the owner to re-adjudicate**, never a verdict
  this unit re-decides.

## 6 · Known hazards

- **`_REPLAYED_CAUSES` is a CLOSED vocabulary** (`src/belay/interop/attach.py:81`) with a
  guard test. A tool-not-offered turn **did** get re-invoked, so its cause belongs IN that
  set — omit it and C9 reports the turn as `unrestorable-pre-state`, asserting a
  snapshot-restore failure that never happened. `interop-merge-repair` fixed exactly this
  class once already.
- `belay verify --json` has a **pinned machine-contract fixture**; a new cause and any
  routing surface must land there deliberately.
- README's *"Coverage & limits, stated exactly"* has **12 subsections and none states the
  replay-boundary/server limit.** Closing that is part of this unit's deliverable.

## 7 · Open questions for the PRD

1. **Scope of generality:** ship the honesty half + `verify --shell-server` parity only, or
   generalize to N servers routed by a probed `tools/list`? (Gap C was deliberately deferred
   once.)
2. Should the `tools/list` probe run always, or only when >1 server is configured? Always
   costs one extra spawn per run but makes the honesty check work in the single-server case
   — which is where the defect was just reproduced.
3. Does `corpus add` need the routing too (a stored case is single-command by prior
   decision), and does the case format change? Prior spec said cases stay single-command.
4. What exactly does `phase0 report`'s UNVERIFIED-by-cause table do with a new cause string?

---

# Phase 2 — Addendum: agent findings (2026-08-28)

## 8 · The trace CANNOT attribute a turn to a server. This is settled.

**No frame carries any server marker** — not a field, not a session id, not a connection id.

- `src/belay/proxy.py` is a byte pump for **exactly one** client↔server pipe;
  `TRACE_FORMAT.md:191` states the invariant: *"the two records bracket is one open pipe to
  one server process — nothing more."* Capture-side multiplexing **does not exist in the
  product.**
- The only multi-server capture ever built is eval-only
  (`eval/minting_driver/composite.py`): it runs **N separate proxies**, each writing its own
  trace, then `eval/minting_driver/trace_merge.py:merge_session_traces` interleaves them by
  `t_in`, **renumbers `seq`, adds no origin tag, and deletes the originals.** Provenance is
  destroyed by the merge — there was none to preserve.
- Therefore trace-derived routing could only reconstruct `name -> server` from
  `annotation_snapshot`s (first-declaration-wins, mirroring `composite.merge_tool_lists`).

**Two hazards make that reconstruction unsafe today:**

1. **Broadcast-id collision (latent, untested).** `composite._broadcast` sends `initialize`
   and `tools/list` to every session with the **same JSON-RPC id**. After merge,
   `derive_correlation` keys pending requests on `(direction, type(id), id)` with **no
   session component** (`src/belay/index.py:75`, `:140`), so the second session's request
   **evicts** the first and a reply can pair against the wrong request. The merge test
   (`tests/test_minting_driver_trace_merge.py:215`) covers only unique-id `tools/call`
   turns; the broadcast case is untested. `offered_toolset` survives only *by accident*
   (it does not filter on `status`).
2. **Tool-name collisions are invisible.** `merge_tool_lists` is first-session-wins
   (`composite.py:171-179`); the loser's tool never appears in the trace at all. A reader
   cannot tell a collision occurred.

**Design consequence — and it simplifies the unit.** The replay-time question is *"does
THIS boundary offer this tool?"*, **not** *"which server answered at capture?"* So probing
each configured replay server's live `tools/list` (§3) **sidesteps the provenance problem
entirely** and needs no trace facts, no format change, and no dependence on the two hazards
above. It is also the more honest question.

## 9 · C9's cause dichotomy has NO room for this verdict — a real design consequence

`attach.py:172-177` is binary: a `TurnVerdict.cause` **in** `_REPLAYED_CAUSES` reports
`cause=None`; **anything else** reports `UNRESTORABLE_PRE_STATE`.

If the design **probes first and therefore skips a pointless re-invoke**, the turn did not
replay — but **not because of its pre-state**, which restored perfectly. C9 would then
assert a snapshot-restore failure that never happened: exactly the `interop-merge-repair`
bug class, in a new dress.

Two options, and the PRD must choose:
- **(a)** re-invoke anyway so the cause stays "replayed" — wasteful, but no C9 change.
- **(b)** give `attach.py` a **third** bucket ("did not replay, pre-state was fine") —
  correct, honest, and a small closed-vocabulary extension.
**(b) is recommended**; (a) buys a spawn per turn to preserve a dichotomy that is simply
wrong.

## 10 · Cause-vocabulary mechanics (confirmed)

- There is **no enum**. Causes are free strings funnelled through `canonical_cause`
  (`src/belay/replay/report.py:126-142`), which is **total** — so `phase0 report`, interop,
  console and `--json` need **no registration** for a new cause.
- The **only** load-bearing closed set is `_REPLAYED_CAUSES`
  (`src/belay/interop/attach.py:80-87`), guarded by
  `tests/test_interop_attach.py:475` `test_replayed_cause_vocabulary_is_closed`, which
  **reflects over `REPLAYED_*` module-level names in `report.py`.**
  **Trap:** a cause hand-built inline (not a module-level `REPLAYED_*` constant in
  `report.py`) is **invisible to the guard** and silently misreported. The plan must state
  this explicitly — the guard cannot catch it.
- `_PREFIX_LABELS` (`report.py:111-123`) is **order-sensitive** ("returns the FIRST match").
- `tests/fixtures/verify_json_snapshot.json` pins only a PASS turn, so a new cause does not
  disturb it.
- The console has a **separate, unrelated** closed union `EngineErrorCause`
  (`console/src/server/types.ts:103-110`) for subprocess-level failures — must not be
  conflated with engine causes.

## 11 · Latent corpus gap found in passing (report, do not necessarily fix)

`corpus/run.py:run_case` (`:522`) and `_recompute_trajectory_case` (`:478`) call
`verify_turn` / `_verify_one_trace` with **only** `case.server_command` — they never thread
`shell_server_command`, even though `_verify_one_trace` supports it. A trajectory case whose
original run routed `run_process` turns to a shell server would silently recompute those
turns against the stored fs command. It does not bite today (the rule reads `records`, not
per-turn replay outcomes) but it is a landmine. **Record as a finding.**

## 12 · Full `--server` inventory (all `nargs=REMAINDER`, none repeatable)

| Surface | line | second-server flag |
|---|---|---|
| `belay replay` | `cli.py:2153` | none |
| `belay verify` | `cli.py:2220` | **none — Gap B** |
| `belay corpus add` | `cli.py:2314` | none |
| `belay phase0 run` | `cli.py:2549` | `--shell-server` `cli.py:2561` |
| `belay interop correlate` | `cli.py:2666` | none |

`REMAINDER` means `--server` **swallows everything after it** and **cannot be repeated** —
so an N-server CLI cannot be spelled as repeated `--server`. Any widening needs a different
flag shape (the `--shell-server` single-quoted-string precedent, or grouped aliases).

Spawn cost today: `client.py:36-38` — **a fresh server process per turn**, plus `--replays`
more on a DIVERGED reply. A once-per-run cached probe is cheap by comparison.
