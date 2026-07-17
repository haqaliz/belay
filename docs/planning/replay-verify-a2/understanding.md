# C4 — Replay-verify (axis A2): Understanding note (Phase 2)

**Status:** pre-PRD. Every API claim below was **read in source** by the mapping agent and cross-checked
by me. **Base:** master @ 48dcf6e — C1+C2+C3 merged, 290 tests green.
**Source:** `docs/planning/_card/issue.md` (quotes `CAPABILITY_ROADMAP.md` §C4 verbatim).

---

## 1. What the work is really asking

**The first grounded verdict — and the whole moat.** *"Langfuse/Phoenix/LangSmith/Braintrust record
and (optionally) LLM-judge score; none re-execute a tool call in a sandbox to check real state. There
is no LLM anywhere in this capability — that is the point."*

C4 turns C3's replay **observations** into a **Verdict** (PASS/WARN/FAIL/UNVERIFIED). Two
deterministic checks per turn: **result equivalence** and **effect conformance**. Zero model calls.

## 2. 🔴 The load-bearing warning C4 must not violate

From `CLAUDE.md`, and it is the single most important sentence for this capability:

> **A2 catches trace infidelity — fabricated/tampered/nondeterministic results. A2 CANNOT catch a
> cheating agent, because a cheater's trace is faithful.** Replay restores the recorded pre-state
> (already containing the weakened test), re-invokes, observes the same result, returns **PASS —
> correctly**. Only a declared invariant (A1/C5) catches corrupt success. **Building A2 and expecting
> it to catch cheating is the single most likely way this project fails quietly.**

**C4's PASS means "the trace reproduces." It NEVER means "the agent did the right thing."** Every
verdict message, docstring, and the README must say exactly that and no more. This is the demo's whole
point (`ROADMAP.md`): A2 returns PASS on the cheat, A1 returns FAIL on the same turn — proving the axes
are non-redundant.

## 3. result-equivalence — the rule, with the MANDATORY determinism gate

C3's `engine.replay_turn` (`engine.py:97-121`, frozen `TurnReplay`) already gives C4:
`status` (REPLAYED/UNVERIFIED/NOT_VERIFIABLE), `cause`, `result_equivalence` (EQUAL/DIVERGED/None),
`recorded_reply` + `replayed_reply` (**both raw bytes, present on REPLAYED** — so a concrete
recorded-vs-observed diff is buildable without recompute), `delta`, version fields.

**But single-turn replay has ZERO determinism knowledge.** Nondeterminism is a **separate N-replay
call**: `determinism.classify_determinism(records, n, replays=3)` → `DeterminismResult`
(DETERMINISTIC / NONDETERMINISTIC / NOT_REPLAYABLE + optional axis).

🔴 **C4 MUST run `classify_determinism` BEFORE promoting a divergence to FAIL.** The rule:

| result_equivalence | determinism | → Verdict |
|---|---|---|
| EQUAL | DETERMINISTIC | **PASS** |
| DIVERGED | DETERMINISTIC | **FAIL** (trace infidelity, `kind="replay"`, concrete diff) |
| DIVERGED | NONDETERMINISTIC | **UNVERIFIED** (carry the axis) — *never FAIL* |
| None (no reply to compare) | — | **UNVERIFIED** |

> *"Never let a timestamp diff render as FAIL — that's how you train users to ignore the verifier."*
> A divergence on a clock/random tool is **legitimate nondeterminism, not infidelity.** Getting this
> ordering wrong is the most likely way C4 produces false FAILs.

## 4. effect-conformance — one strong signal, one real gap (the gate decision)

The roadmap says effect-conformance checks *"files touched, network egress, exit codes"* against the
tool's declared annotations + sandbox policy. Reality, from source:

**✅ Files touched — fully observable.** `delta = diff_records(scan_tree(pre), scan_tree(post))`
(`engine.py:300-310`) → `list[FieldDiff(path, field, left, right)]` covering content, perm (incl.
setuid), uid/gid, mtime_ns, symlink target, xattrs, hardlink group. This is a **strong, grounded
signal**, and it delivers the roadmap's headline acceptance test in full:
**`readOnlyHint: true` + a non-empty filesystem delta → FAIL, naming the annotation and the write.**

**✅ Tool errors ("exit codes") — observable via the reply.** For an MCP tool, the "exit code" is the
`CallToolResult.isError` / JSON-RPC `error` — part of the reply, so already covered by
result-equivalence. The OS *server* process exit is handled by C3's `UNANSWERED_TARGET`. **Not a
separate gap.**

**🔴 Network egress — a REAL GAP, and the honest scoping decision for the gate.**
- The delta is **filesystem-only**. There is **no positive egress observation** (bytes/hosts) anywhere.
- C2 records the **applied policy** (`network_policy` record: `{policy: mode, ports: [...]}`) and
  *inferred* `denial`s from child stderr — but **`client.replay_turn` sends the replay server's stderr
  to `DEVNULL`** (`client.py:328`) and the replay path writes **no `network_policy` record**. So in the
  replay path as built, **denials are not captured.**
- **What this means for `openWorldHint`:** C4 cannot diff observed-egress-vs-policy today. Under the
  deny-all replay default, a tool that *attempts* egress would be *denied* — a real conformance
  signal — **but only if C4 un-DEVNULLs the replay stderr and runs `DenialCapture`.** That is a modest
  build (SHOULD), not a large one, and it catches **denied** egress only (deny-all), never **successful**
  egress (allow-all).

→ **Proposed scope (for the gate):** effect-conformance v0 = **filesystem delta vs the tri-state
`readOnlyHint`/`destructiveHint`** (the MUST, which is the whole roadmap acceptance list).
**`openWorldHint` network conformance is either a SHOULD (denials-during-deny-all-replay) or an honest
UNVERIFIED-for-that-dimension** — stated plainly, never implied as covered. *"Never claim coverage we
don't have."*

**The annotations, from source:** the tri-state is `declared-true` / `declared-false` / `not-declared`
(+ a 4th `declared-non-boolean` for `readOnlyHint: "yes"`). Spec defaults appear **nowhere** — absent
stays `not-declared`. **No per-turn lookup helper exists** — `derive_annotations(records)` returns a
flat list of `annotation_snapshot` / `annotation_gap` / `annotation_staleness`. **C4 correlates
itself**, mirroring `_uncovered_calls` (`annotations.py:232`): tool name from the turn's request-frame
`params.name`; the most-recent snapshot with `source_seq < request_seq`; look up the tool by name.

Effect-conformance rule per hint:
- `readOnlyHint` **declared-true** + non-empty delta → **FAIL** (contract non-conformance)
- **not-declared** / `annotation_gap` / **declared-non-boolean** → **UNVERIFIED** (*absent ≠ permissive*)
- `readOnlyHint` **declared-false** + mutation → **PASS**

## 5. The Verdict model + the reduction

**Nothing emits a Verdict today** — confirmed: every `PASS`/`FAIL`/`UNVERIFIED` in `src/` is a comment
deferring to C4/C5. **C4 owns the model from scratch:** `Verdict(axis, kind, status, observed,
expected, message)` and the PASS/WARN/FAIL/UNVERIFIED status type.

**Reduction: worst-status-wins**, ordering **FAIL > UNVERIFIED > WARN > PASS**.
🔴 **UNVERIFIED must rank ABOVE PASS/WARN** so worst-wins can *never* turn UNVERIFIED into a clean
verdict — *"UNVERIFIED is never rendered as PASS"* becomes the reduction's structural property, not a
hope. Today C4 reduces across A2's **two sub-checks only** (A1/C5 doesn't exist yet); **shape the model
so A1 slots into the same worst-wins later, and A3 as downgrade-only.**

## 6. Mapping EVERY C3 status → a Verdict (the one hole to avoid)

| C3 replay_turn status | → C4 |
|---|---|
| REPLAYED | PASS / FAIL / UNVERIFIED per §3 (determinism-gated) |
| UNVERIFIED (no request / unrestorable / unrecognised handle / unreadable frame / manifest missing / **UNANSWERED_TARGET**) | **UNVERIFIED**, carry the cause verbatim (incl. the gate's `UNRESTORABLE_SNAPSHOT_FAILED` string — **never `UnrestorableCause(it)`, it throws**) |
| NOT_VERIFIABLE (absent handle — no snapshot attempted) | **UNVERIFIED** with a **distinct** cause |
| determinism NOT_REPLAYABLE | **UNVERIFIED** |

🔴 **The one hole to avoid:** `NOT_VERIFIABLE` (an un-snapshotted turn) must **not** fall through as
PASS. A2 has no PASS/FAIL for a turn it never snapshotted — it is UNVERIFIED, kept out of the "passed"
count. **Reuse `report.canonical_cause`** (`report.py:101-117`, total/never-empty) for UNVERIFIED
causes so the failure-corpus buckets stay consistent.

## 7. What C4 must build

1. **The Verdict model** + PASS/WARN/FAIL/UNVERIFIED type (nothing in `src/`).
2. **The reduction** with the UNVERIFIED-never-PASS guarantee; A1-ready.
3. **result-equiv → verdict** with the **mandatory determinism gate** (call `classify_determinism`
   before FAIL on a divergence).
4. **effect-conformance**: the per-turn annotation correlation (C4 writes it) + tri-state
   `readOnlyHint` vs the BTH-1 delta.
5. **network-egress observation** — SHOULD (un-DEVNULL replay stderr + `DenialCapture` for
   `openWorldHint` under deny-all), or an honest UNVERIFIED for that dimension.
6. **The CLI** — `belay replay` (`cli.py:318-396`) reports coverage only and says so
   (*"emits no PASS/FAIL... That is C4."*). C4 adds `belay verify` (or a `--verify` mode); plumbing
   (`read_trace`, `replay_trace`, `--manifest-dir`/`--server`/`--replays`/`--turn`) is reusable.
   `--no-claim-axis` is A3's refutation and **not wired yet** (lands with C8) — shape verdict
   aggregation as a clean toggle so it slots in.

## 8. Guardrail check

| Guardrail | C4 |
|---|---|
| No agent framework | ✅ C4 verifies a recorded call; never authors/drives an agent |
| No LLM judge | ✅ **Zero model calls — re-execution and diffing decide. This is the point.** |
| UNVERIFIED never PASS | ✅ **The reduction's structural property** (UNVERIFIED > PASS) + the NOT_VERIFIABLE hole |
| Never claim coverage we don't have | ⚠️ **The network-egress gap.** effect-conformance must not imply it verifies `openWorldHint`/egress unless it actually observes it |
| The engine gets better as models improve | ✅ Deterministic re-execution; a better model writes better *tools*, C4's diff is unchanged |
| Test-first | ✅ The 6 acceptance bullets become failing tests first |

## 9. Open questions for the PRD

1. **Network egress: SHOULD (denials via un-DEVNULL'd replay stderr) or scoped-out UNVERIFIED?**
   The gate decision. Recommend: **build the denial capture (it's modest and gives a real
   `openWorldHint` signal under deny-all), but state plainly that successful egress under allow-all is
   NOT verified.** If it proves fiddly, fall back to honest UNVERIFIED — never fake it.
2. **CLI surface: `belay verify <trace>` vs `belay replay --verify`?** Recommend a distinct
   `belay verify` — the verb *is* the capability, and it keeps `belay replay` (coverage-only) honest.
3. **`WARN` — does A2 ever emit it?** The roadmap's A2 examples are only PASS/FAIL/UNVERIFIED. The
   `bth1` sparse-file case is a documented WARN candidate. Recommend: **model WARN in the status type
   (A1/A3 will use it) but A2 v0 emits only PASS/FAIL/UNVERIFIED** unless a concrete WARN case appears.
4. **`kind` on the Verdict** — the roadmap names `kind="replay"` for result-equivalence divergence.
   effect-conformance needs its own kind (`kind="effect"`?). Confirm the two check kinds.
