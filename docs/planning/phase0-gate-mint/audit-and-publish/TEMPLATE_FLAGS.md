# TEMPLATE_FLAGS.md — Evidence inventory (Phase 1)

> **DRAFT TEMPLATE** for unit `feat/phase0-gate-mint` (2026-08-14). Fill during the run;
> no outcome cells are pre-filled. Do not commit as results. When filled, every row below
> is transcribed from the ledgers and the traces — nothing inferred, no labels, no TP/FP
> judgments (those belong to `TEMPLATE_AUDIT.md`).

**Stage(s):** `<s6a|s6b|s6c>` · **Ledger(s):**
`docs/planning/phase0-gate-mint/mint-run/ledgers/<s6a.json|s6b.json|s6c.json>`
**Traces:** `eval/mint/s6<stage>/batch/trace-*.jsonl` (+ `.manifests/` siblings)
**Engine:** belay <version> — A1 `no-assertion-weakening` (`tests` + `testing`) + instance-level
`suite-before-success-claim` (scope `""`) · **Model:** `claude-opus-5` (claude-cli, subscription)
**Toolset:** `filesystem+shell` (dual server — filesystem + `mcp-server-commands`)

---

## 1. Trajectory table (all instances)

Columns read from the ledger's per-instance `trajectory` object; the aggregate line matches
`belay phase0 report`'s trajectory section verbatim.

| Instance (`trace_id`) | Verdict (ledger `trajectory.status`) | Cause (`trajectory.cause`) | evidence_count (`trajectory.evidence_count`) | Claim classification (`<VERIFICATION|completion-only|ambiguous|NO_TEXT>` — from trace claim record) |
|---|---|---|---|---|
| <trace_id> | <FAIL\|PASS\|UNVERIFIED> | <cause\|null> | <n> | <value> |

Aggregate (from `STAGE<stage>_FINDINGS.md` report block, verbatim):
`<n> FAIL / <n> PASS / <n> UNVERIFIED (by cause: <cause>: <n>, ...)`.

## 2. Per-instance facts

Workspace root in every trace path below:
`<worktree>/eval/mint/s6<stage>/<instance>/workspace/`. Turn indices are 0-based positions of
`tools/call` frames in the trace. Turn count per instance = `sum(turn_status_counts.values())`.

### <trace_id> — <turn_count> turn(s) · disposition <VERIFIED_CLEAN|VERIFIED_FLAGGED|ERRORED>

| Turn | Tool | Args (summary) |
|---|---|---|
| <idx> | <tool_name> | <args summary> |

- Per-turn statuses (ledger `turn_status_counts`): <PASS: n, UNVERIFIED: n, ...>
- Flagged turns (ledger `flagged_turns`): <[] | [idx, ...]> — addable (`flagged_addable`) /
  unaddable (`flagged_unaddable`): <...>
- edit_file writes: <n> (turns <idx...>) · run_process calls: <n> (turns <idx...>)
- Exposure (ledger `exposure`): `files_compared <n>, turns_judging <n>, turns_recorded <n>`
  (or `unrecorded` — `exposure` key absent; never rendered as a zero)
- Trajectory (ledger): status <...> · cause <...> · evidence_count <n> ·
  `trajectory_addable` <true|false|absent>
- Claim (verbatim, `claim` record in trace): *"<claim text>"*
- `error`: <null | message>

## 3. Flag inventory

### 3a. Turn-level flags (ledger `flagged_turns`, non-empty per instance)

| Instance | Turn index | Rule (scope) | Message (verbatim, from verdict/case) | Corpus case id (once ingested) |
|---|---|---|---|---|
| <trace_id> | <idx> | <no-assertion-weakening, scope `<tests|testing>`> | "<message>" | <case_id\|—> |

### 3b. Trajectory FAILs (ledger `trajectory.status == FAIL`)

| Instance | evidence_count | Case id | Kind | Rule (case `invariants` / sub-verdict expected) | Target turn | Target tool |
|---|---|---|---|---|---|---|
| <trace_id> | <n> | <trace-<trace_id>-turn<idx>> | <corrupt-success (instance-level trajectory case, schema v<X> `trajectory` declaration)> | `suite-before-success-claim`, scope `""` | <final/claim turn idx> | <tool of that turn> |

**Trajectory FAILs with no case id: <none|list>.** `belay corpus list` output (verbatim) and
`belay corpus score` (verbatim, pre-label state) are appended here at transcription date.

## 4. Per-flag adjudication block (Phase 2 — fill during adjudication)

One block per flag from §3a/§3b. Filled by the operator from `TEMPLATE_AUDIT.md`'s rules.

```
Flag: <trace_id> turn <idx> (rule <rule>, scope <scope>) | trajectory FAIL on <trace_id>
  verdict:            <TP | FP | abstain-reclassified | unverifiable>
  evidence:           <the facts that decided it — claim text, evidence_count, tools/list facts>
  root-cause key:     <kebab-case, case.py-valid>
  human label:        <true-positive | false-positive>  (via `belay corpus label`)
  independence note:  <distinct root-cause key? distinct instance AND tool? — see AUDIT §3>
```

## 5. Tools availability per trace (the offered-toolset fact)

Decode from the trace's `tools/list` request/response frames **before the claim** (the
derived reading the engine itself uses; per-instance, never assumed shared):

| Instance | Connection(s) | Server(s) | Tools listed before claim | `run_process` offered? | Reading |
|---|---|---|---|---|---|
| <trace_id> | <n> | <server name + version> | <n tools, names> | <yes|no|unknown> | <offered | NO_COMMAND_TOOL_OFFERED | TOOLSET_UNKNOWN> |

- `run_process` offered = listed in a pre-claim `tools/list` snapshot and the snapshot is
  not stale (no un-re-snapshotted `list_changed` between snapshot and claim).
- `unknown` = no pre-claim snapshot exists, or a `list_changed` was never re-snapshotted
  (⇒ `TOOLSET_UNKNOWN`, never a guess).
- Network policy recorded in every trace: <deny-all|...>.

Fact for adjudication, stated without judgment: <one sentence — was the suite-run ability
(any command/shell tool such as `run_process`) offered on the MCP boundary in this stage?>

## 6. Validation (Phase 1 requirements)

- Case ids in §3 match `uv run belay corpus list` output byte for byte (<n>/<n>).
- Ledger cross-checks: `flagged_turns` / `trajectory` fields transcribed exactly
  (<n>/<n> instances); `turn_status_counts` sums match the report's total turns (<n>).
- Trajectory table (§1) matches the ledger's `trajectory` fields instance for instance.
- Exposure lines transcribed from `exposure` (`files_compared` counts JUDGMENTS, a sum over
  turns — not distinct files); `exposure` absent ⇒ `unrecorded`, never a zero.
- Per-turn statuses aggregate (ledger `turn_status_counts` across instances) matches the
  report's `per-turn FAIL rate` numerator/denominator.
