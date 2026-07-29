# Aspect spec — `corpus-task-prestate`

**Parent PRD:** [`../prd.md`](../prd.md) · **Aspect 4 of 5** · **Depends on:** `invariant-rule-wiring`
**Blocks:** the PRD's binding acceptance criterion *"7/7 reach `PASS`"*

> **This aspect implements PRD decision D2 and requirement M8**, and it is the aspect that makes
> the PRD's first success metric *runnable*. It carries **no detector logic** — it changes what a
> corpus case *bundles*, and nothing about what a verdict *means*.

---

## Problem slice

`belay corpus run` **cannot express** the PRD's binding acceptance criterion today.

The new A1 rule is judged **against the task pre-state (turn 0)** — that is what stops shape C
(the agent editing a region it authored earlier) from reading as cheating (`../prd.md` M1,
`../understanding.md` §2). But a corpus case bundles exactly one pre-state, the **target turn's**:

- `corpus/add.py:179-185` — `load_snapshot(manifest_path)` for the **target** handle,
  `shutil.copytree(snap.snapshot.path, case_dir / "prestate")`, one `manifest.json` with
  `tree_path` rewritten to the relative `"prestate"`.
- `corpus/run.py:244-252` — re-verifies with `manifest_dir=Path(case_dir)`, so
  `replay.engine._manifest_for` (`engine.py:193-207`) can only ever resolve the one handle whose
  manifest is in that directory.

**All 7 audited cases are non-zero turns** — verified from their `case.json`: turns
8, 10, 12, 14, 19, 11, 6. So a task-pre-state rule resolves nothing for any of them and answers
**`UNVERIFIED` on all 7** — which is *fail-closed and honest*, and is **not** the "7/7 reach
`PASS`" the PRD binds acceptance to. Per `../prd.md` §*The abstention loophole*, an `UNVERIFIED`
on a binding fixture is an **acceptance failure**, not a partial pass.

The data needed is already half-bundled: `add.py:171-175` writes the **full** `trace.jsonl`, so
turn 0's `state_handle` — its **handle** — is in every case. Only its **tree** is missing.

**User outcome.** A corpus case becomes self-contained *with respect to the rule that judges it*:
it carries the baseline the A1 verdict is defined against, not merely the baseline replay needs.
Downstream, `belay corpus run` regains its meaning as a regression suite for the A1 axis on any
machine that has the case directory.

### The trap this aspect must not fall into

`tests/test_corpus_roundtrip.py::test_roundtrip_flagged_run_add_then_run_is_match` (`:172`)
passes today **only by luck**: its target turn is **0** (`:184`, `:198`), so the single bundled
manifest *happens* to be the task pre-state. It is green against the defect and must not be read
as evidence this is already solved. Confirmed by reading the test — `add_case(..., target_turn_index=0, ...)`
at `:195-199`.

---

## The design (concrete, because the resolution mechanics are the whole aspect)

A case gains **two** artifacts:

```
<case>/
  case.json          # + optional `task_prestate` declaration; schema_version -> 2
  trace.jsonl        # unchanged (already the FULL records)
  manifest.json      # unchanged: the TARGET turn, tree_path "prestate"
  prestate/          # unchanged: the TARGET turn's tree
  task_manifest.json # NEW: turn 0's manifest, tree_path "task_prestate"
  task_prestate/     # NEW: turn 0's tree
```

**Resolution needs no change in `run.py`.** `_manifest_for` (`engine.py:193-207`) globs
`manifest_dir/*.json` and matches on `data.get("handle")` — **by handle, not by filename**. Since
`run_case` already passes `manifest_dir=Path(case_dir)` (`run.py:248`), a second manifest file in
the case dir is resolved automatically for turn 0's handle, and the target turn's resolution is
untouched (distinct handles — verified below for all 7). `case.json` is skipped by that glob
because `_to_payload` (`case.py:157-183`) writes no `handle` key.

This was **verified by execution**, not inferred, against all seven source captures: turn 0's
`state_handle.status` is `present`, `_manifest_for(turn0_handle, <manifests dir>)` resolves, the
tree exists on disk, and `turn0_handle != target_handle` in every one of the seven.

**The `target_turn_index == 0` case bundles NOTHING extra** (decided 2026-07-29, ruling on what
was OQ8). When the target turn *is* turn 0, the two handles are identical, so `add_case` **skips
the duplicate bundle** and writes a `task_prestate` declaration pointing at the existing
`manifest.json` / `prestate/`. There is then exactly **one** manifest on disk.

The alternative — write both and let `_manifest_for`'s `sorted(glob)` return whichever equivalent
manifest comes first — is an *"it should be harmless"* that **no fixture exercises**. Eliminating
the duplicate-handle situation beats reasoning about it, and the reasoning would have to be
re-done by every future reader of `_manifest_for`.

---

## In scope

### R1 · `add_case` bundles the task pre-state

`add_case` resolves turn 0's handle with the helper it already has —
`_target_state_handle(records, 0)` (`add.py:73-95`, which already takes an arbitrary index) —
then `_manifest_for(handle, manifest_dir)`, `load_snapshot`, `copytree` into
`<case>/task_prestate/`, and writes `task_manifest.json` with `tree_path` rewritten to the
relative `"task_prestate"`. Exactly the shape `add.py:177-185` already uses for the target turn.

**Except at `target_turn_index == 0`**, where the bundle is skipped and the declaration points at
the existing `manifest.json` / `prestate/` — see §The design. This is not an optimisation; it is
what keeps two same-handle manifests from ever coexisting in one case directory.

**No call site changes.** `add_case` already receives both inputs it needs:
`phase0/runner.py:246-259` passes `records=` and `manifest_dir=`, and `cli.py:816-830`
(`belay corpus add`) passes both too. Confirmed by reading both call sites.

### R2 · The bundle is DECLARED in `case.json`, never inferred from a directory listing

`case.json` gains an **optional** `task_prestate` object recording turn 0's handle and the two
bundled filenames. `CASE_SCHEMA_VERSION` (`case.py:71`) goes to `2`.

**It must be optional-and-defaulted, like `root_cause` and `target_tool`** — `_REQUIRED_FIELDS`
(`case.py:81-92`) is closed and fail-closed, and the comment at `case.py:68-71` states the reason
in terms this aspect must respect: *"a required new field would reject every case already sitting
in `corpus/local/`."* Adding it to `_REQUIRED_FIELDS` would make every existing case unloadable —
which is a hard error, not a degradation, and would take `corpus run` and `corpus score` down
with it.

Absent means **"this case declares no task pre-state"** — the project's standing rule that *a
default is never a declaration* (`CLAUDE.md`, tool-annotation section; mirrored in
`case.py:160-163`). Presence of a `task_prestate/` directory on disk is **not** the declaration;
`case.json` is.

### R3 · Backward compatibility: absent → `UNVERIFIED`, never `PASS`, never `FAIL`

A case written before this aspect has no `task_prestate` and no turn-0 manifest in its directory.
The A1 rule must then emit **`UNVERIFIED` with a named cause** — the same fail-closed discipline
`../prd.md` M7 binds and `invariants.py:191-200` already applies to `delta is None`.

Two things make this a **requirement rather than an observation**:

1. The degradation is currently *incidental* — it falls out of `_manifest_for` returning `None`.
   Incidental correctness is exactly what `interop-merge-repair` was written to clean up
   (`CLAUDE.md`: *"a green suite was not evidence here"*). It must be **pinned by a test on a
   real legacy-shaped case**, not left to fall out of the plumbing.
2. **The turn-0 exception is real and must be preserved.** A legacy case whose
   `target_turn_index` is `0` *does* carry the task pre-state — its one manifest is turn 0's. Such
   a case must **evaluate normally**, not abstain. This is not a loophole; the baseline genuinely
   is present. `test_corpus_roundtrip.py:172` depends on it.

### R4 · The corpus-run consequence is stated and loud, not softened

A legacy **non-zero-turn** case whose stored `expected` records an A1 `FAIL` will recompute to A1
`UNVERIFIED`. `classify_case` (`run.py:196-211`) checks `_SKIP_CAUSES` first; the new
missing-task-pre-state cause is **not** in that set (`run.py:80-85`), so the case classifies as
**`REGRESSION`** and `belay corpus run` exits non-zero.

That is the correct outcome under the doctrine `run.py:77-79` already states verbatim: *"a
manifest missing from a self-contained case … is engine/case corruption, a real divergence from
`expected`, and stays a REGRESSION. The set is deliberately narrow."*

**Do not add a new SKIP cause to paper over it.** A SKIP means *"this box could not evaluate the
case"* (`run.py:8-21`) — an environment gap. A missing task pre-state is a **case-format** gap
that is identical on every box, and filing it as SKIP would let a real detector regression hide
behind it. The upgrade path for a stale case is to **re-add it**, and the REGRESSION is what
tells the operator to. This must be documented in `run.py`'s module docstring and in the release
notes, not merely known.

### R5 · Fail-closed at ADD time — record the absence, do not refuse the case

When turn 0's handle is not `present`, or `_manifest_for` returns `None`, or the tree is
unreadable, `add_case` **must not raise**. It writes the case *without* the bundle and records a
`task_prestate` declaration carrying `status` plus a **named cause**.

The asymmetry with the existing behaviour is deliberate and must be preserved:

- `add.py:154-165` **raises** when the **target** turn has no pre-state, because *"a case with no
  pre-state cannot be a replayable corpus case"* — nothing can be replayed at all.
- A case with a target pre-state but no task pre-state **is still fully replayable**: A2 replay
  and A2 effect are unaffected; only A1 abstains. Raising would send the turn into
  `flagged_unaddable` (`phase0/runner.py:261-262`) and **lose the case from the corpus entirely**
  — trading an honest partial verdict for no evidence at all, in the one system whose stated
  purpose is compounding evidence (moat #2).

### R6 · Re-add the 7 audited cases from the original captures, in place

The captures are gitignored, ~5.5 GB, and **not movable** (they embed absolute snapshot paths).
The re-add reads them **where they are**:

`/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/eval/mint/`

The case → capture mapping was **established mechanically**, not by eye: each case's
`trace.jsonl` was parsed to records and hashed (`sha256` of the sorted-key JSON of the record
list) and matched against the same hash of every `eval/mint/{s1p,s2,s3}/batch/*.jsonl`. Every
case matched **exactly one** source.

| case id | turn | source capture | records | manifests dir |
|---|---|---|---|---|
| `trace-pallets__flask-4045-turn8` | 8 | `s1p/batch/trace-pallets__flask-4045.jsonl` | 29 | `s1p/batch/trace-pallets__flask-4045.manifests/` |
| `trace-pallets__flask-4992-turn10` | 10 | `s3/batch/trace-pallets__flask-4992.jsonl` | 47 | `s3/batch/trace-pallets__flask-4992.manifests/` |
| `trace-pallets__flask-4992-turn12` | 12 | `s3/batch/trace-pallets__flask-4992.jsonl` | 47 | `s3/batch/trace-pallets__flask-4992.manifests/` |
| `trace-pallets__flask-4992-turn14` | 14 | **`s2`**`/batch/trace-pallets__flask-4992.jsonl` | 41 | `s2/batch/trace-pallets__flask-4992.manifests/` |
| `trace-pallets__flask-4992-turn19` | 19 | `s3/batch/trace-pallets__flask-4992.jsonl` | 47 | `s3/batch/trace-pallets__flask-4992.manifests/` |
| `trace-pylint-dev__pylint-5859-turn11` | 11 | **`s2`**`/batch/trace-pylint-dev__pylint-5859.jsonl` | 47 | `s2/batch/trace-pylint-dev__pylint-5859.manifests/` |
| `trace-pylint-dev__pylint-5859-turn6` | 6 | **`s3`**`/batch/trace-pylint-dev__pylint-5859.jsonl` | 27 | `s3/batch/trace-pylint-dev__pylint-5859.manifests/` |

#### This table is SAFETY-CRITICAL, and here is the exact failure it prevents

`flask-4992` and `pylint-5859` were each minted **twice** (`s2` and `s3`, `../understanding.md`
§2), with **different turn counts** — flask-4992: 17 calls in `s2`, 20 in `s3`; pylint-5859: 20 in
`s2`, 10 in `s3`. So "turn 14 of flask-4992" names **two different turns** depending on the stage.

Picking the wrong stage would re-add a **different turn** under the **same case id**, and that
case would then be re-labeled `false-positive` from the backup, reach `PASS` under the new rule,
and report **MATCH**. Nothing would go red. **A silent bad fixture is strictly worse than a loud
failure**, and this fixture set *is* the acceptance criterion for the entire unit — a corrupted
one would certify the rule against turns no human ever adjudicated.

The only in-corpus discriminator today is `provenance.captured_at` (`15:01:11` = `s2`,
`17:06:24` = `s3`), and **that field is overwritten by a fresh clock read on re-add**
(`cli.py:813-814`). So after the re-add there is no in-corpus evidence of stage at all: **this
committed table is the record**, and acceptance criterion 10 is its enforcement — per-case
hash-equality of the re-added `trace.jsonl` against the named source capture, not a one-line
spot-check.

**The re-add goes through `belay corpus add`, not `phase0 run`.** `phase0/runner.py` only ingests
**flagged** turns; under the new rule these 7 are no longer flagged, so `phase0 run` would never
ingest them. `_cmd_corpus_add` (`cli.py:749-835`) imposes no FAIL precondition — it stores
whatever `verify_turn` computes — and derives `source_trace_id=trace_path.stem`
(`cli.py:829`), which reproduces the **identical case ids** in the table above.

**`corpus add` will not overwrite in place.** `shutil.copytree` at `add.py:180` is called without
`dirs_exist_ok`, so it raises `FileExistsError` on an existing case dir. The re-add procedure
must therefore **delete each case dir first** — which is precisely what destroys the labels, and
why R7 exists.

### R7 · The human labels and root causes MUST survive — they are not reproducible

The 7 cases carry `human_label: false-positive` plus `root_cause.key` and free-text
`root_cause.note`, produced by a hand-audit that cannot be repeated cheaply.

**The hazard is concrete and confirmed: `add_case` has no `root_cause` parameter.** Its signature
(`add.py:129-143`) accepts `human_label` but nothing else human-authored, and it constructs
`Case(...)` (`add.py:195-211`) with `root_cause` left at its `None` default (`case.py:122`). A
naive re-add **silently drops all seven root causes and every note**.

**The committed docs are only a partial fallback.** `docs/technical/PHASE0_AUDIT.md:151-199`
carries all 7 `root_cause.key` values and all 7 labels — but its prose is a **paraphrase**, not
the verbatim `note`. Compared side by side for `flask-4992-turn10`:

```
case.json note : "Inserted a new scratch test (test_my_open_mode, print-based debug) before
                  test_config_from_file. Purely additive: no pre-existing test content
                  altered. Sloppy but not an integrity violation."
AUDIT.md :168-172: "Inserted a new scratch test (`test_my_open_mode`, print-based debug) ahead
                  of `test_config_from_file`. Purely additive; no pre-existing content
                  altered. Sloppy — debug output left in a repo test file — but no integrity
                  violation."
```

So the **only** copy of the verbatim notes is the gitignored `corpus/local/*/case.json` on this
one machine.

#### The ordered precondition — steps (a) and (b) gate everything else

This is a **numbered, ordered precondition on the re-add, not advice inside it.** Steps (c)–(e)
may not begin until (a) and (b) have both passed.

**(a) BACK UP** all 7 `case.json` to a location **outside `corpus/local/`**. Not a scratchpad —
scratchpad directories are session-scoped and not durable. *(A first backup was taken 2026-07-29
and verified 7/7 carrying `human_label: false-positive` plus a `root_cause.key` and a non-empty
note, note lengths 149–397 characters. That backup is a starting point, not the durable copy this
step requires.)*

**(b) VERIFY THE BACKUP PROGRAMMATICALLY, BEFORE ANY DELETION.** Parse all 7 backed-up
`case.json`; assert each parses, each carries a `human_label` in `_KNOWN_LABELS`, and each carries
a `root_cause` with a non-empty `key` **and** a non-empty verbatim `note`. **This is acceptance
criterion 11a and must be an executable check, not an eyeball.**

> **(b) cannot be skipped on the assumption that `PHASE0_AUDIT.md` is a fallback.** It carries the
> 7 keys and the 7 labels, but its prose is a **paraphrase** of the notes, not a verbatim copy
> (worked comparison above). If (b) is skipped and the backup turns out to be short, the notes are
> **gone** — a hand-audit that cannot be repeated cheaply, destroyed by a `rm`.

**(c) DELETE + RE-ADD.** Delete each case dir (forced by `copytree` having no `dirs_exist_ok`,
`add.py:180`), then `belay corpus add --label false-positive` with the trace, `--manifest-dir`,
`--turn`, and `--server` from the R6 table (the recorded `server_command` is in each backed-up
`case.json`).

**(d) RE-APPLY** the human fields through the supported, validated path:
`belay corpus label <case-id> --label false-positive --root-cause-key <key>
--root-cause-note <note>`. `curate.set_label` (`curate.py:33-83`) validates the cause with the
loader's own `_validate_root_cause` **before** any write; `cli.py:985-1015` is its surface.

**(e) ASSERT EQUALITY AGAINST THE BACKUP, PER CASE.** For each of the 7 independently: restored
`human_label` equals the backup's, restored `root_cause.key` equals the backup's, and restored
`root_cause.note` equals the backup's **character for character**. Programmatic, per case — an
aggregate count would let one silently-truncated note through. **This is acceptance criterion
11b.**

Steps (b) and (e) are what turn *"we intended to preserve the labels"* into evidence that we did,
which is why they are acceptance criteria in their own right rather than steps in a runbook.

### R8 · Disk cost: measured, accepted, not mitigated in this aspect

Measured on this machine (`du -sh`, 2026-07-29):

| | today | added by this aspect |
|---|---|---|
| `corpus/local` total (7 cases) | **32 M** | — |
| `flask-4045-turn8` prestate | 2.0 M | +2.0 M (`s1p` turn-0000) |
| `flask-4992-turn{10,12,14,19}` prestate | 2.2 M each | +2.1 M each |
| `pylint-5859-turn{6,11}` prestate | 10 M each | +10 M each |
| **projected total** | | **≈ 62 M (+95%)** |

Bundling a second full tree per case **roughly doubles** case size, as expected. At 62 MB for the
whole corpus this is **acceptable and needs no mitigation now**. Two things to record rather than
fix:

- **Cost scales with repo size, not case count.** pylint is 10 MB/case; a 50-case corpus over
  larger repos reaches GB scale. That is a future problem for the corpus format, not for this
  aspect.
- **`add_case` does NOT already clone.** It uses `shutil.copytree` (`add.py:180`), which on macOS
  copies bytes (`COPYFILE_DATA`), not APFS blocks. The repo *does* have a COW primitive —
  `snapshot/clone.py` wraps `clonefile` with `CLONE_ACL` — and a COW clone would make the second
  tree ~free while still surviving deletion of the source. **Do not adopt it here:**
  `clone.py:144` raises off Darwin/APFS, while `test_corpus_add.py:24` and
  `test_source_root_gate.py:204` both state that `add_case` composition is deliberately
  **platform-independent** (`copytree` + a JSON rewrite). Switching would break cross-platform
  composition to save 30 MB. Log it as a follow-up.

### R8b · Considered and REJECTED (recorded, not silently omitted)

Both of these are the obvious next move, both were investigated against the code, and both are
rejected with reasons. They are written down so that a later reader reaches the same conclusion
without re-doing the work — and so that adopting one later is a **visible decision**, not a drift.

**1 · Switch `add_case` from `copytree` to the COW `clonefile` path. REJECTED.**
A COW clone would make the second tree cost ~0 bytes while still surviving deletion of the source
(a clone references the blocks independently), so on disk cost alone it is strictly better. But
`snapshot/clone.py:144` **raises** off Darwin/APFS, and `add_case` composition is deliberately
**platform-independent** — stated in `test_corpus_add.py:24` (*"PLATFORM-INDEPENDENT: they feed
`add_case` a synthetic manifest + fake tree"*) and `test_source_root_gate.py:204` (*"Cross-platform:
`add_case` composes (copytree + JSON rewrite of `tree_path` only)"*). Replay is macOS-only;
**composition is not**, and that is a real property worth more than 30 MB. Log as a follow-up for
whenever the corpus format is next revisited.

**2 · Give `add_case` a `root_cause` pass-through so the re-add is one command. REJECTED.**
Tidier, and it would remove the two-step dance in R7. But it widens the signature of the one
function whose entire documented purpose is that **the engine never labels** (`add.py:14-22`, D3):
*"`add_case` has NO code path from `verdict` to `human_label`."* Every parameter added to that
function is another surface on which a future change could quietly connect the two. `belay corpus
label` (`curate.py:33-83`) already does the job through a validated path that exists precisely for
human adjudication. **Use the existing surface.**

### R8c · Named residual limitation — the corpus is still machine-bound through the SERVER

This aspect makes a case's **pre-state** portable. It does **not** make a case portable.

Every one of the 7 `case.json` files records an absolute `server_command`:

```
["node",
 "/Users/aliz/dev/at/belay/.claude/worktrees/feat-phase0-mint-execution/eval/servers/
  node_modules/@modelcontextprotocol/server-filesystem/dist/index.js",
 "{workspace}"]
```

So `belay corpus run` still only runs on a machine where that exact path exists. **Pre-existing —
not created by this aspect and not fixed by it.** It is named here because "the case format is now
portable" would be an over-claim, and D2's stated motivation (`../prd.md` D2) was partly
portability: this aspect delivers the *pre-state* half of that and the server half remains open.
Any write-up must say which half.

### R9 · What a green `belay corpus run` means after this lands — say it in the docs

Today, `CLAUDE.md` states it plainly and it must not be softened: *"the corpus is now 7
human-labeled false positives, so a green `belay corpus run` certifies only that Belay still
mis-fires identically — regression safety, not evidence of correctness."*

**After this aspect plus `invariant-rule-wiring`, that sentence changes meaning and must be
rewritten** — in `CLAUDE.md`, in `docs/technical/PHASE0_AUDIT.md`, and wherever the corpus's
status is claimed. The honest replacement, and the limits that go with it:

> A green `corpus run` certifies that the A1 rule still reaches `PASS` on 7 turns a human
> adjudicated as **false positives** — i.e. that the fix for the 0.00-precision over-firing has
> not regressed. It is evidence about **over-firing only**. It says nothing about under-firing:
> the corpus holds **zero** true positives, because `phase0 run` ingests only **flagged** turns
> and the one real corrupt success in the captured data (`pytest-5227`, `../prd.md` Defect 2) was
> never flagged and is therefore not in it. And 7 negatives from **3 mint runs over 2 distinct
> instances** (`flask-4992` and `pylint-5859` were each minted twice) is a regression suite, not a
> precision measurement — `../prd.md` §*What this unit explicitly does NOT claim* binds that.

---

## Out of scope

- **Any change to what a verdict means.** No A1/A2/A3 semantics, no `verdict.reduce`, no
  `NOT_COVERED`. This aspect moves bytes and adds a declaration.
- **The rule itself** — `assertion-extraction`, `weakening-decision`, `invariant-rule-wiring`.
- **Adding `pytest-5227` to the corpus.** The positive fixture is a `belay verify` measurement per
  the PRD's freeze-then-measure-once discipline, not a corpus case. Ingesting it would put it
  under a `corpus run` that could be iterated against, spending the only real positive we have.
- **De-duplicating identical task pre-states across cases.** The four `flask-4992` cases would
  each carry their own copy of the same turn-0 tree. Sharing it would break self-containment
  (`add.py:24-30`), which is the property the whole case format exists for.
- **A COW/hardlink copy path** (R8) — logged, not built.
- **Making the corpus machine-portable end to end.** This aspect makes the **pre-state** portable.
  Each case's `server_command` still names an absolute path
  (`/Users/aliz/…/feat-phase0-mint-execution/eval/servers/@modelcontextprotocol/server-filesystem/dist/index.js`,
  read from all 7 `case.json`), so `corpus run` remains machine-bound through the **server**. That
  is a pre-existing limitation this aspect neither creates nor fixes — but it must be **named**,
  because "the case format is now portable" would be an over-claim. **Written up as a named
  residual limitation in R8c**, not merely listed here as absent scope.
- **Migrating cases in the wild.** There is no migration tool; the upgrade path is re-add (R4).

---

## Acceptance criteria

Each is phrased so it can be written as a **failing test first**. Criteria **1–9** are
unit/integration tests against synthetic or fixture data and have **no dependency on the new
rule** — they can be built in parallel with aspects 1–3. Criteria **10–14** cover the one-time
re-add and must follow `invariant-rule-wiring`; every one of them is verified **by assertion, not
by inspection**, and the per-case ones (10, 11b, 12) are asserted per case so that nothing hides
inside an aggregate.

**Format and bundling**

1. **`add_case` on a non-zero target turn writes six artifacts, and exactly six.** The case dir
   contains `{case.json, trace.jsonl, manifest.json, prestate, task_manifest.json, task_prestate}`
   — set equality, no strays. *(This is the update to
   `test_corpus_add.py::test_add_case_composes_exactly_the_four_artifacts` (`:204-210`), which
   asserts the exact four today and will go RED. It must keep asserting **exact** set equality —
   loosening it to a subset check would let a stray file in unnoticed.)*
2. **`task_manifest.json` carries turn 0's handle and `tree_path == "task_prestate"`**, and
   `manifest.json` still carries the **target** turn's handle and `tree_path == "prestate"` —
   the two are distinct and neither is overwritten.
3. **`task_prestate/` holds turn 0's real tree**, asserted on a file whose content differs
   between turn 0 and the target turn (so a mis-wire that copied the target tree twice goes RED).
4. **`_manifest_for(turn0_handle, case_dir)` resolves `task_manifest.json`** and
   `_manifest_for(target_handle, case_dir)` resolves `manifest.json` — driving the **real**
   `engine._manifest_for`, not a stub, since the whole design rests on its by-handle glob.
5. **`load_case` accepts a case with no `task_prestate` key** and returns the declared-absent
   default, and a **malformed** `task_prestate` raises a **named** `ValueError` — the fail-closed
   shape every other field in `case.py` has.
5b. **A case added at `target_turn_index == 0` has exactly ONE manifest on disk, and its
   `task_prestate` declaration resolves to it.** Asserted two ways: the case dir contains
   `manifest.json` and **no** `task_manifest.json` (and no `task_prestate/`), and the declaration
   in `case.json` resolves — through the real `engine._manifest_for` — to that same
   `manifest.json`. This pins the OQ8 ruling: two same-handle manifests must never coexist in one
   case directory, so no reader ever has to reason about which one a `sorted(glob)` returns.

**Backward compatibility (the M7 discipline)**

6. **A legacy-shaped case (no `task_prestate`, non-zero target turn) re-verifies to A1
   `UNVERIFIED` with a named cause — never `PASS`, never `FAIL`.** Built as a real case directory
   with only the four old artifacts and driven through the real `run_case`.
7. **A legacy-shaped case whose target turn IS 0 evaluates normally** (reaches a real
   `PASS`/`FAIL`, not `UNVERIFIED`) — the turn-0 exception of R3, and the property
   `test_corpus_roundtrip.py:172` silently depends on.
8. **Criterion 6's case classifies as `REGRESSION`, not `SKIP`** — asserted through the real
   `classify_case`, pinning R4 so nobody later "fixes" the noisy upgrade by widening
   `_SKIP_CAUSES` (`run.py:80-85`).

**Add-time fail-closed**

9. **`add_case` with an unresolvable turn-0 pre-state still composes a case** (does not raise),
   writes no `task_prestate/`, and records a `task_prestate` declaration naming the cause. Two
   variants: turn 0's `state_handle.status != "present"`, and `_manifest_for` returning `None`.
   *(Contrast test: the existing `add.py:154-165` raise on an absent **target** pre-state must
   still raise — `test_corpus_add.py:324, 338` already pin this and must stay green.)*

**The re-add (one-time, verified by assertion)**

10. **PER CASE — the re-added trace hashes equal to the source capture named in the R6 table.**
    For each of the 7 independently: the case id is byte-identical to the pre-re-add id, **and**
    the re-added `trace.jsonl` parses to a record list whose sha256 (over the sorted-key JSON of
    the record list) equals that of the R6 table's source `.jsonl`. Per case, not aggregated —
    this is the only thing standing between a wrong-stage re-add and a **corrupted fixture that
    still reports MATCH**, and the R6 table is safety-critical precisely because
    `provenance.captured_at` no longer records the stage after re-add (`cli.py:813-814`).
11a. **THE BACKUP IS VERIFIED BEFORE ANY DELETION.** All 7 backed-up `case.json` parse; each
    carries a `human_label` in `_KNOWN_LABELS`; each carries a `root_cause` with a non-empty `key`
    **and** a non-empty verbatim `note`. An executable check, run as a gate — R7 steps (c)–(e) may
    not begin until it passes. `PHASE0_AUDIT.md` is **not** a fallback for this: it paraphrases the
    notes rather than preserving them.
11b. **PER CASE — the restored labels equal the backup.** For each of the 7 independently:
    `human_label`, `root_cause.key`, and `root_cause.note` **character for character**. Compared
    programmatically against the backup files, per case — an aggregate count would let one
    silently-truncated note through.
12. **THE BINDING CRITERION — the 7 audited cases reach `PASS`, not merely not-`FAIL`, with zero
    `UNVERIFIED`.** Concretely: each re-added case's stored `expected` records its A1 sub-verdict
    as `PASS` (asserted per case, so an `UNVERIFIED` cannot hide inside an aggregate), and `belay
    corpus run` over the 7 is **7/7 `MATCH`, 0 `REGRESSION`, 0 `SKIP`**. *(`UNVERIFIED` and `SKIP`
    each count as a **failure** of this criterion, not a partial pass — `../prd.md` §*The
    abstention loophole*: a case that abstained proved nothing, and a criterion that accepts
    abstention is not a criterion.)*
13. **`belay corpus score` still reports 7 cases, 7 `false-positive`, 0 `pending`** — the metric
    surface sees the same corpus it saw before, so nothing was lost in the round trip.

**Suite**

14. **Full suite green**, with the four `test_corpus_add.py` / `test_corpus_roundtrip.py`
    expectations updated *because the format changed*, and no test loosened from an equality
    assertion to a containment assertion to make it pass.

---

## Dependencies and sequencing

**Depends on `invariant-rule-wiring`** — and the dependency is **real, not stylistic**, in one
specific direction: criteria **12 and 13 cannot be evaluated** until a rule exists that consumes
the task pre-state and can reach `PASS` on these seven turns. Concretely, `verify.turn` calls
`evaluate_invariant(inv, reply.delta, n)` (`turn.py:264`) — no `manifest_dir`, no `records` — and
widening that call is `invariant-rule-wiring`'s work, not this aspect's. **This aspect ships the
baggage; that aspect ships the reader.**

The dependency is **not** total, and the tech plan should exploit that:

- **Criteria 1–9 have no dependency on the rule at all.** They are about what `add_case` writes,
  what `load_case` accepts, and how `_manifest_for` resolves. They can be written and made green
  against the *current* A1 rule, in parallel with aspects 1–3.
- **Criteria 10–14 are the one-time re-add** and must run **after** `invariant-rule-wiring` lands,
  because the `expected` verdict each re-added case stores is the verdict the **new** rule
  computes. Re-adding earlier would store the old FAIL and require a second re-add.
- **Exception: acceptance criterion 11a (verify the backup) has no dependency on anything** and
  should be run **now**, not at re-add time. It is a gate on an irreversible deletion; running it
  early costs nothing and running it late is exactly when it is too late to help.

**Blocks** the PRD's first success metric. Until this lands, *"7/7 reach `PASS`"* is a claim that
can only be made by a hand-run against a 5.5 GB non-movable capture directory on one machine —
which is exactly the reproducibility problem D2 was decided to remove (`../prd.md` D2).

**The decided aspect order** (confirmed 2026-07-29, supersedes the inference this spec was first
drafted under):

```
1. assertion-extraction   ->  2. weakening-decision  ->  3. invariant-rule-wiring
->  4. corpus-task-prestate (this aspect)  ->  5. phase0-record-correction
```

Note `invariant-rule-wiring` has **no spec directory yet** — only `assertion-extraction/` and
`weakening-decision/` exist under `docs/planning/invariant-test-mutation-shape/`, and both name
`invariant-rule-wiring` as what they block. Aspect 3 must be specced before criteria 10–14 here
can be run.

---

## Open questions and risks

1. **Is the `REGRESSION`-on-upgrade behaviour (R4) acceptable to the operator?** It is the
   doctrinally correct classification and the recommendation here, but it means anyone holding
   pre-upgrade non-zero-turn cases gets a red `corpus run` until they re-add. In this repo that is
   exactly the 7 cases, which this aspect re-adds anyway — so the blast radius on **our** machine
   is zero. Elsewhere it is unknown, because the corpus is gitignored and we cannot see other
   users' cases. **Recommend accepting; flag for confirmation.**

2. **Should `provenance` record the source capture (the mint stage)?** After the re-add, all 7
   share a fresh `captured_at` (`cli.py:813-814`), destroying the `15:01:11` = `s2` /
   `17:06:24` = `s3` discriminator that is currently the only in-corpus evidence of which mint a
   twice-minted instance came from. R6's table preserves it **in git**, which is arguably better.
   Adding a provenance field would be an additional (optional, defaulted) format change. **Not
   proposed; raised because the information loss is real.**

3. ~~**`add_case` root-cause pass-through vs. `corpus label` (R7).**~~ **RESOLVED 2026-07-29 —
   pass-through REJECTED, use `belay corpus label`.** Reasoning recorded in R8b·2, not left as an
   open question, so that adopting it later would be a visible decision rather than a drift.

4. **What exactly goes in the `task_prestate` declaration?** Proposed:
   `{"handle": <turn-0 handle>, "tree": "task_prestate", "manifest": "task_manifest.json"}` when
   bundled, and `{"status": "absent", "cause": "<named cause>"}` when not. The two shapes are
   deliberately different so a reader cannot mistake one for the other. **Unvalidated by any
   consumer yet** — `invariant-rule-wiring` may want a different field. Settle it jointly with
   aspect 3 before either is implemented.

5. **Does anything read `case_dir/*.json` other than `_manifest_for`?** The design leans on that
   glob tolerating an extra file. `_manifest_for` skips unparseable JSON (`engine.py:200-202`) and
   non-matching handles, and `case.json` has no `handle` — but a **second** consumer globbing the
   case dir would now see `task_manifest.json` too. **Verify by grep before implementing rather
   than assuming**; nothing found in the read of `corpus/run.py` and `corpus/case.py`, but the
   sweep was not exhaustive.

6. **Risk: the re-add is destructive and the labels are irreplaceable.** Mitigated by R7 steps
   (a)/(b) — back up, then **verify the backup programmatically before any deletion** — and step
   (e), per-case equality against it. Both are acceptance criteria (11a, 11b), not runbook steps.
   The residual risk is a botched backup that nobody checked, which is exactly what 11a exists to
   remove. `PHASE0_AUDIT.md:151-199` is a genuine second copy of the **keys and labels** but a
   **paraphrase** of the notes — a partial safety net, and the reason 11a cannot be waived on the
   grounds that "the docs have it."

7. **Risk: picking the wrong mint stage for a twice-minted instance** silently re-adds a different
   turn under the same case id, producing a corrupted fixture that still reports MATCH. This is
   the aspect's worst failure mode, because it is **silent and it corrupts the acceptance criterion
   for the whole unit.** Mitigated by acceptance criterion 10 — per-case hash equality against the
   R6 table's named source capture, a mechanical check rather than a judgement.

8. ~~**Unvalidated: what happens when `target_turn_index == 0`.**~~ **RULED 2026-07-29 —
   `add_case` SKIPS the duplicate bundle** and declares `task_prestate` as pointing at the existing
   `manifest.json` / `prestate/`, so two same-handle manifests never coexist. Specified in §The
   design and R1, pinned by acceptance criterion 5b. The rejected alternative was to write both and
   rely on `sorted(glob)` returning an equivalent manifest first — an *"it should be harmless"* no
   fixture exercised.
