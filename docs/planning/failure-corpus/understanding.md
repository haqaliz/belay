# C6 — Failure corpus: Phase-2 deep-dig understanding note

Read-only dig. No production code, no tests. Every claim below is grounded in a file I read;
where I infer, I say so. Citations are `path:line`.

---

## 1. What the work is really asking (grounded in the roadmap)

C6 is **moat #2, made durable**: every failure the engine already catches becomes a
**stored, labeled, replayable case**, and `belay corpus run` **re-replays the whole corpus and
asserts each case still reaches its expected verdict** — i.e. the corpus *is* the regression
suite (`docs/technical/CAPABILITY_ROADMAP.md:317-347`, `docs/ROADMAP.md:143`).

Concretely C6 must deliver four things (roadmap §C6, `CAPABILITY_ROADMAP.md:324-335`):

1. **A corpus format.** Each case = *trace slice + pre-state handle + expected verdict +
   human-audited label* (true-positive / false-positive / unverifiable).
2. **`belay corpus add`** (ingest a flagged run into a case) and **`belay corpus run`**
   (re-replay every case, assert the expected verdict; a detection change that breaks a past
   case fails CI).
3. **Precision/recall** against the audited labels, so "detection improved" is measured, not a
   vibe.
4. **Privacy by construction** — cases store what the user's infra already holds; nothing
   uploads. (`/corpus/local/` is already gitignored — `.gitignore:19`.)

Crucially, C6 **adds no new verdict axis**. It *stores and regresses* the A1/A2 verdicts the
engine already emits. It seeds on day one from Phase 0's audited corpus rather than starting
empty (`CAPABILITY_ROADMAP.md:344-345`); the Phase-0 gate is the run that mints that seed
(`ROADMAP.md:105-119`).

What "the audited corpus" / "the violation-rate number" mean (Phase 0, `ROADMAP.md:84-119`):
mint ≥50 SWE-bench-lite runs through the proxy, emit A1/A2 verdicts per turn, **hand-audit
every flag**, and publish a violation rate *with its denominator* and a *stated false-positive
rate*. Those hand-audited flags — verdict + human adjudication — are exactly the rows C6
stores. C6 is the persistence/replay layer that turns that one-off audit into a compounding,
re-runnable asset.

---

## 2. The real code C6 builds on

Each building block, with what it provides and what it lacks for C6.

### 2a. `corrupt_success_case(verdict)` — the C5 seam (`src/belay/verify/invariants.py:253-290`)
A **pure shaper**, explicitly documented "no persistence — C6 owns storage"
(`invariants.py:254-266`). Given a `TurnVerdict` whose A1 invariant sub-verdict is `FAIL`, it
returns a dict:
```
{kind:"corrupt-success", axis:"A1", rule, scope, turn_index, tool_name,
 violating_paths, message}
```
(`invariants.py:281-290`). Returns `None` when no A1 sub-verdict is FAIL.

**What it is:** the "flagged finding" summary — the human-readable *what was caught*. It is
enough to file and display a case, and is the natural seed of the case's metadata.
**What it is NOT:** anywhere near a *replayable* case. It carries no trace, no pre-state, no
server, and no expected verdict beyond the A1 FAIL fact. Everything needed to *re-derive* the
verdict is missing (see §3). Tests pin its exact shape (`tests/test_corrupt_success_case.py`).
It also only covers **A1-FAIL corrupt success** — the highest-value class, but C6's format must
also hold A2 FAILs (fabricated/tampered results), UNVERIFIED cases, and human-labeled
false-positives (cases where the engine FAILed but a human ruled it GOOD). So `corrupt_success_case`
seeds *one kind* of case; the corpus format is a superset.

### 2b. Trace format + reader — what a "trace slice" concretely is
- Format: JSONL, append-only, one record per line, versioned `v` from line one
  (`docs/technical/TRACE_FORMAT.md:19-49`). A `frame` record carries `seq` (one monotonic order
  across both directions), `dir` (`c2s`/`s2c`), `raw` (base64 of exact bytes), hashes, and
  `state_handle` (`TRACE_FORMAT.md:39-116`).
- The **pre-state handle is stamped on the `tools/call` frame** by the gate via
  `TraceWriter.set_state_handle(handle, frame=raw)` (seen in use at
  `tests/test_launch_demo.py:150-151`). The three-state handle — `absent` / `present` /
  `unrestorable` — lives in the frame's `state_handle` slot (`TRACE_FORMAT.md:100-116`,
  `substrate.py:407-436`).
- Reader: `read_trace(path) -> ReadResult(records, skips)` (`src/belay/replay/reader.py:83-145`).
  It returns raw record dicts ready to hand straight to `derive_correlation`; unknown kinds /
  newer versions are *skipped and recorded*, a broken line raises `TraceCorrupt`.

**A "trace slice" for one turn** is, concretely, the set of records that make
`verify_turn(records, n)` work for that turn: the handshake frames (if any), the `tools/list`
response (so C4 can read the tool's annotations and C4-network can see `openWorldHint`), and
the target `tools/call` request + its response — with the pre-state handle on the call frame.
`test_launch_demo._demo_records` (`test_launch_demo.py:159-172`) is the minimal shape:
`tools/list` req+resp, then the `tools/call` (carrying the `present` handle) + its reply. Note
`verify_turn` selects the turn by correlation index over the **whole** records list
(`turn.py:100`, `_tool_name`), so the slice must be a self-consistent mini-trace where index
`n` picks the target. Simplest correct choice: store enough contiguous records that
`tool_calls(derive_correlation(records))[n]` is the target.

### 2c. Replay + snapshot — what a deterministic re-verify actually needs
`verify_turn(records, n, *, server_command, manifest_dir, network, timeout, replays,
invariants) -> TurnVerdict(status, sub_verdicts, cause)` (`src/belay/verify/turn.py:140-218`).
It replays **once** via `replay_turn` and composes A2 (result + effect [+ network]) and A1
sub-verdicts, reducing worst-status-wins.

`replay_turn(records, n, *, server_command, manifest_dir, network, timeout)`
(`src/belay/replay/engine.py:202-383`) does the real re-execution:
- reads the handle off the target `tools/call` frame (`engine.py:244-268`);
- resolves the persisted **manifest** by globbing `manifest_dir/*.json` for one whose `handle`
  matches (`_manifest_for`, `engine.py:133-147`);
- `load_snapshot(manifest_path)` reconstructs a `GuardedSnapshot` (`engine.py:297`);
- `guarded_restore` restores the pre-state into a scratch dir, `scan_tree` captures `before`
  (`engine.py:298-301`);
- spawns the server (`_client_replay_turn`, `engine.py:302-308`) — **the live MCP server** —
  and diffs `before` vs the post-state workspace to get `delta` (`engine.py:321-322`).

`persist_snapshot(snap, manifest_path)` / `load_snapshot(manifest_path)`
(`src/belay/replay/persist.py:98-138`) join a recorded handle to a restorable snapshot on disk.
**The load-bearing portability fact:** the manifest stores `tree_path = str(snap.snapshot.path)`
— an **absolute path to the cloned pre-state tree** (`persist.py:111`), and `load_snapshot`
reconstructs `Snapshot(path=Path(payload["tree_path"]), ...)` verbatim (`persist.py:129-132`).
`restore`/`guarded_restore` then clone *from that tree* (`clone.py:133-138`,
`substrate.py:386-404`). So **the manifest is not self-contained** — it references an external
tree by absolute path, and that tree's bytes must exist on disk for a restore to happen.

Snapshot substrate: `take_snapshot`/`guarded_restore`/`present_handle`
(`src/belay/snapshot/substrate.py:368-436`). Two hard constraints C6 must respect:
- **darwin/APFS only.** `clonefile` requires Darwin (`clone.py:141-149`), which is why every
  real-replay test carries `pytest.mark.skipif(sys.platform != "darwin", ...)`
  (`test_launch_demo.py:59-62`).
- **Capability match.** `guarded_restore` **refuses** with `UNRESTORABLE_CAPABILITY_MISMATCH`
  if the restoring machine's backend capabilities differ from the capturing machine's
  (`substrate.py:386-403`) — e.g. `xattrs-os-native` is present on Linux but not macOS
  (`substrate.py:341-343`). So a case captured on one substrate legitimately restores to
  UNVERIFIED on another.

### 2d. CLI subcommand pattern — the template for `belay corpus`
`_parser()` (`src/belay/cli.py:653-773`) registers `sandbox check`, `replay`, `verify` as
argparse subparsers, each with `set_defaults(func=...)`. `_cmd_verify`
(`cli.py:460-543`) is the closest template for `corpus run`: read the trace, build the A1
policy (defaults + `--invariants`, fail-closed on a bad file, `cli.py:491-497`), loop
`verify_turn` per turn, aggregate PASS/WARN/FAIL/UNVERIFIED, and return a **non-zero exit if any
turn is FAIL or UNVERIFIED** (`cli.py:542-543`). `--server` after a `nargs=REMAINDER` sentinel
supplies the server command (`cli.py:765-771`, `main` at `cli.py:776-785`). The
darwin-Seatbelt gate is *not* in the CLI — it surfaces as UNVERIFIED at replay time and via
the test skipif.

### 2e. Phase-0 audited-corpus artifacts already present
**None exist yet.** `rg -i corpus` finds only planning/docs prose and the gitignore entry;
there is no `corpus/` tree, no seeded cases, no labels file in the repo. The Phase-0 run that
mints the seed has **not been executed/committed** here. So C6 must *define* the seed format
and the `add` path that produces it; it cannot assume seed rows on disk. (This matches the
status note: "Next: run the Phase-0 corpus … then C6" — CLAUDE.md status block.)

---

## 3. The crux (Question A): what a case must carry to replay deterministically

To re-derive a verdict, `verify_turn` needs **four inputs** (`turn.py:140-150`), and tracing
each back through `replay_turn`:

| Input | Source today | Can it be *stored in the case*? |
|-------|--------------|-------------------------------|
| **(a) trace slice** `records` | the recorded JSONL (`reader.read_trace`) | **Yes** — copy the records into the case as `trace.jsonl`. Fully self-contained. |
| **(b) pre-state** = manifest + cloned tree | `manifest_dir/*.json` (by handle) **+** the tree at the manifest's absolute `tree_path` | **Manifest yes; tree needs work.** The manifest is a small JSON, but it points at an *absolute external tree* (`persist.py:111`). To be self-contained the case must **copy the cloned tree in and rewrite `tree_path`** (or `load_snapshot` must learn to resolve a manifest-relative tree). This is the single biggest format decision. |
| **(c) server** `server_command` | supplied at run time (a live MCP server binary/script) | **Command string: yes. The binary: generally no.** The server must actually *run and write to its scratch workspace* — that filesystem write is the `delta` A1/A2 ground on (`engine.py:321-322`). A "just replay the recorded reply" stub would make result-equivalence trivially PASS and produce **no delta**, so A1/A2 could never re-fire. The real server is load-bearing and cannot be portably bundled. |
| **(d) A1 policy** `invariants` | passed by the caller (`--invariants` + defaults) | **Yes, and it MUST be stored.** The expected A1 verdict depends entirely on which invariants were enforced (`turn.py:209-210`); a case that omits them cannot reproduce its own FAIL. Store the scope/rule set with the case. |
| plus `expected verdict` and `human label` | — | **Yes** — the two fields that make it a corpus case (see §4). |

**The honest constraint.** A case is **not** a hermetic, run-anywhere artifact. Even with the
trace, the tree, and the policy fully bundled, deterministic re-replay requires:
1. **darwin/APFS** (the clonefile substrate — `clone.py:141-149`), and
2. **a matching capability set** (else `guarded_restore` refuses — `substrate.py:386-403`), and
3. **the server command runnable on the box** (the binary is external).

Where any of those is unmet, re-replay legitimately yields **UNVERIFIED** (capability mismatch,
missing manifest, unanswered server), never a fabricated verdict — the engine already does the
honest thing here (`engine.py:248-290`, `substrate.py:396-403`). C6's job is to *not paper over
this*: `corpus run` on the wrong substrate must **skip / report UNVERIFIED-by-substrate as
distinct from a regression**, not count it as a broken case.

**Recommended case shape** (a directory per case under `corpus/local/<case-id>/`):
```
corpus/local/<case-id>/
  case.json        # metadata: id, target_turn_index, expected_verdict (+ per-sub-verdict
                   #   statuses/axes for a richer assertion), human_label, invariants
                   #   (scope/rule list), server_command, replays, timeout, provenance
                   #   (source trace id, capture timestamp), capture platform + capability set
  trace.jsonl      # the trace slice (self-contained; index target_turn_index picks the turn)
  manifest.json    # the persisted snapshot manifest, tree_path rewritten to case-relative
  prestate/        # the cloned pre-state tree, copied in (the bytes guarded_restore needs)
```
`corpus add` composes this from a flagged run: it already has `records`, the `manifest_dir`,
and the computed `TurnVerdict`; it copies the trace slice + the referenced tree, records the
verdict + policy + server_command, and takes the **human label as an explicit input** (never
inferred — see §5). `corpus run` iterates cases, calls `verify_turn` with the stored inputs,
and asserts the recomputed verdict equals `expected_verdict`, naming any mismatch.

**Named open question (the crux's unresolved half):** *how is the server provided at run
time, and does the case reference an external snapshot or bundle its own tree?* Bundling the
tree makes cases self-contained but fat and still substrate-locked; referencing an external
snapshot dir keeps them thin but fragile across checkouts/machines. And the server binary
cannot be bundled at all — the seed (SWE-bench + off-the-shelf MCP FS/shell servers) must pin
the server by version, and fixture-based cases can pin an in-repo fixture server
(`tests/fixtures/*_server.py`). This is a human decision for the PRD.

---

## 4. Label vs verdict, and the precision/recall definition

**Keep two independent things distinct:**
- **Engine VERDICT** = `TurnVerdict.status` ∈ {PASS, WARN, FAIL, UNVERIFIED}
  (`src/belay/verify/verdict.py:34-40`). It is what a case *asserts stays stable* under
  `corpus run` (the regression check).
- **Human LABEL** = ground truth from the Phase-0 audit ∈ {BAD (genuine violation), GOOD (no
  violation), UNADJUDICABLE ("unverifiable")}. It is what precision/recall is computed
  *against*. It is **authored by a human**, never by the engine (§5).

These are two different comparisons, and C6 needs both:
1. **Regression** (`corpus run`, the CI gate): *recomputed verdict* vs *stored expected
   verdict*. Deterministic; a mismatch fails CI naming the case.
2. **Quality** (precision/recall): *engine verdict* vs *human label*. A measured claim about
   detection.

**Confusion matrix** (define "positive" = the engine emitted **FAIL**; a detection):

| | Label BAD | Label GOOD |
|---|---|---|
| Verdict **FAIL** | **TP** | **FP** |
| Verdict **PASS** | **FN** | **TN** |
| Verdict **UNVERIFIED** | *excluded* (coverage) | *excluded* (coverage) |
| Label **UNADJUDICABLE** | *excluded from both* | |

(WARN is a non-FAIL, non-detection status — treat it with PASS as "not a positive" for
detection, or exclude it; note it explicitly in the PRD. It is rare in A1/A2 today.)

**Formulas the PRD should adopt:**
```
Precision = TP / (TP + FP)      # of what the engine FLAGGED (FAIL), how much was truly BAD
Recall    = TP / (TP + FN)      # of what was truly BAD, how much the engine CAUGHT (FAIL)
```
computed **only over cases where the engine verdict is decisive (FAIL or PASS) AND the human
label is adjudicable (BAD or GOOD).**

**UNVERIFIED handled explicitly — the honest, load-bearing part:**
- A case whose **engine verdict is UNVERIFIED is excluded from precision/recall entirely**
  (neither numerator nor denominator) and reported on its **own line as a coverage / UNVERIFIED
  rate**, broken down by named cause. This mirrors exactly how `replay/report.py` keeps
  `not-verifiable` **out of** the unverified numerator and on its own line
  (`report.py` module docstring, "not-verifiable is NOT unverified"). Folding UNVERIFIED into
  PASS/FN would treat "I could not check this" as "I checked and cleared it" — the precise
  UNVERIFIED-rendered-as-PASS the whole project forbids. Folding it into a positive would be a
  fabricated detection.
- A case whose **human label is UNADJUDICABLE** has no ground truth, so it too is excluded from
  P/R and reported separately.

**The guard against a vanity metric:** precision/recall computed over the decisive subset can
look perfect while the engine shrugs (UNVERIFIED) on everything else. So the report **must**
publish, side by side, three numbers: precision, recall, **and coverage** (fraction of
adjudicable cases the engine decided FAIL/PASS rather than UNVERIFIED). Precision/recall
without the coverage denominator is exactly the "detection improved as a vibe" the roadmap
says to avoid.

---

## 5. Guardrail check (Question C)

- **Axis touched: none new.** C6 stores and regresses the existing A1/A2 verdicts
  (`turn.py:186-210`); it introduces no third grounding. Confirmed against
  `CAPABILITY_ROADMAP.md:324-335` (format/add/run/metrics only).
- **LLM-judge risk — the single most important C6 guardrail.** The **label must be
  human-authored.** An auto-labeler is an LLM judge and is forbidden (CLAUDE.md non-goals;
  `_card/issue.md:49-51`). The specific trap: labeling a case "true positive" *because the
  engine FAILed it* — that conflates verdict with label, and would manufacture **100% precision
  by construction**, destroying the entire point of measuring precision/recall against
  independent ground truth. `corpus add` must take the label as an explicit human input (a
  flag, or leave it `pending` for later human audit), and precision/recall must **refuse to
  count `pending`/unlabeled cases**. Flag this loudly in the PRD.
- **No raw-data egress.** Cases live under `corpus/local/`, already gitignored
  (`.gitignore:19`); nothing uploads. A trace/tree is "as sensitive as the agent's most
  sensitive tool argument" (`TRACE_FORMAT.md:9-18`), so bundling the pre-state tree into a case
  keeps it local by design and is consistent with the guardrail — but the PRD should note the
  case dir inherits that sensitivity (owner-only perms, never committed).
- **UNVERIFIED-never-PASS in the metrics.** Enforced by §4: UNVERIFIED is excluded from P/R and
  reported on its own coverage line, never folded into PASS or into a positive.

---

## 6. Determinism & testability (Question D)

The acceptance is "deterministic, no network" (`CAPABILITY_ROADMAP.md:342`). Split the surface:

- **Pure metric math — no replay, no network, no darwin.** Precision/recall/coverage is a
  **pure function** of a set of `(expected_verdict, human_label)` pairs. Test it with a
  **fixture corpus** of cases carrying *recorded* verdicts + labels and assert the computed
  numbers equal hand-computed values (acceptance bullet 3, `CAPABILITY_ROADMAP.md:340-341`).
  This needs no `verify_turn` at all — exactly like `test_verdict.py` tests `reduce` purely.
- **Regression comparison — pure.** "A deliberately regressed detector fails `corpus run` with
  the exact case named" (`CAPABILITY_ROADMAP.md:339`) can be tested at the **comparison layer**:
  feed a stored `expected_verdict` and a (recomputed or injected) current verdict that differs,
  and assert `corpus run` reports the mismatch naming the case. The *comparison* is pure; only
  the *recompute* step is replay.
- **Real round-trip — darwin/Seatbelt-gated.** "A Phase-0 flagged run round-trips into a case
  and replays to the same verdict" (`CAPABILITY_ROADMAP.md:338`) requires real replay
  (`replay_turn` spawns a server inside macOS Seatbelt on APFS). This test carries the same
  `pytest.mark.skipif(sys.platform != "darwin", ...)` as `test_launch_demo.py:59-62`. So **the
  corpus is CI in two tiers**: the metric/comparison tier runs everywhere (the portable
  regression guard), and the real-replay tier runs only on the darwin substrate. `corpus run`
  itself must treat a substrate/capability-mismatch UNVERIFIED as a **skip, distinct from a
  regression**, so running the corpus off-substrate doesn't produce false CI failures.

---

## 7. Open questions for the PRD (human decisions)

1. **Case self-containment vs external reference (the crux).** Bundle the pre-state tree into
   each case (self-contained, fat, still substrate-locked) — requiring `load_snapshot` to
   resolve a case-relative `tree_path` — **or** reference an external snapshot dir (thin,
   fragile across checkouts/machines)? Absolute `tree_path` (`persist.py:111`) forces a choice.
2. **Server provisioning at `corpus run` time.** The live MCP server is load-bearing (its
   filesystem write is the delta) and cannot be portably bundled. How is it pinned — by
   versioned off-the-shelf server (SWE-bench seed), by in-repo fixture server (fixture cases),
   by a per-case declared command the operator must satisfy? What happens when it is
   unavailable — UNVERIFIED-skip, presumably, but confirm.
3. **Corpus directory layout & the label lifecycle.** Confirm `corpus/local/<case-id>/` with
   `case.json` + `trace.jsonl` + `manifest.json` + `prestate/`. How is the **human label**
   captured (`add --label`, or `pending` + a separate audit step) and how do
   unlabeled/`pending` cases get excluded from precision/recall?
4. **What "expected verdict" pins.** Just the reduced `Status`, or the per-sub-verdict
   axis/kind/status set (a stricter regression assertion that catches an axis silently flipping
   while the reduced status stays the same)? Recommend the latter.
5. **Seed source.** Phase-0 audited corpus does not exist on disk yet (§2e). Does C6 ship with
   `add` + a handful of fixture-server seed cases (deterministic, darwin-gated) and defer the
   ≥50 SWE-bench seed to the actual Phase-0 run, or block on that run first?
6. **Substrate/capability policy for `corpus run`.** Confirm that a capability-mismatch or
   non-darwin UNVERIFIED is a reported **skip**, never a regression failure, so the corpus is
   runnable (in its metric tier) on any CI box.
