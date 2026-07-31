# Aspect — `corpus-collision-guard`

**Unit:** `phase0-reverify-banked` · **Order: FIRST — safety before measurement.**
**Covers PRD must-haves M-1 and M-4a, and should-have S-1.**

> Sequenced first because every later aspect runs `belay phase0 run` against real captures, and
> until this lands, doing so can corrupt the only 7 human-labeled corpus cases in existence
> **and** fabricate an `INSTRUMENT SUSPECT`. This aspect is the reason the measurement is safe
> to run at all.

---

## Problem slice

`add_case` is not safe to call twice for the same case id, and nothing says so.

Traced end to end (all citations verified this session):

1. `case_dir.mkdir(parents=True, exist_ok=True)` (`corpus/add.py:268`) — succeeds silently on a
   populated directory.
2. `trace.jsonl` is opened `"w"` (`add.py:272`) — **the existing case's trace is truncated and
   rewritten before any collision is detected.**
3. `shutil.copytree(snap.snapshot.path, case_dir / "prestate")` (`add.py:279`) — no
   `dirs_exist_ok`, so an existing `prestate/` raises **`FileExistsError`**.
4. `write_case` (step 4) is never reached, so `case.json` — and with it `human_label` and
   `root_cause` — survives **by accident**, not by design.
5. `FileExistsError` is not a `ValueError`, so `runner.py:261`'s `except ValueError` misses it.
   It reaches `run_batch`'s catch-all (`runner.py:147`) and the **entire instance** becomes
   `Disposition.ERRORED` — every turn's data discarded, not just the colliding turn.
6. `ERRORED` is excluded from `violation_denominator()` (`ledger.py:114-120`), so the denominator
   silently **shrinks**; enough of them and `instrument_suspect()` fires (`report.py:65-87`).

The compound failure mode is the dangerous one: **a fake `INSTRUMENT SUSPECT`, i.e. a fake
PIVOT, manufactured by re-running a measurement.** No test covers a collision
(`tests/test_corpus_add.py` has 15 tests, none for re-add; `tests/test_phase0_runner.py`'s
ingester-exception test raises a hand-built `ValueError`, never a real collision).

## User outcome

Re-verifying captures is safe and honest: an existing case is never damaged, a human
adjudication is never overwritable by the engine, and a collision is reported as a named
outcome rather than swallowed into a lost instance or a shrunken denominator.

## In scope

**R1 · Detect before writing.** `add_case` determines whether the target case id already exists
**before** it mutates anything. No partial write may precede the decision — in particular
`trace.jsonl` must not be truncated on the way to failing.

**R2 · A named, runner-handled outcome.** A collision raises the error type the runner already
handles for "this turn could not be added" (`ValueError`, per `runner.py:260-262`), carrying a
message that names the case id and says the case already exists. Consequence: the turn lands in
`flagged_unaddable` with a cause, the instance keeps its real disposition and turn counts, and
**the denominator is unaffected**. It must be impossible for a collision to produce `ERRORED`.

**R3 · A human label is never overwritable by the engine.** Even on the success path,
`add_case`'s `human_label` is a pass-through (`add.py:301-305`) and `runner.py:255` always sends
`"pending"`; R1 makes the destructive path unreachable, and a test pins that an existing case's
`human_label`/`root_cause` are byte-identical after an attempted re-add.

**R4 · `--no-ingest` on `phase0 run`** (S-1). A pure measurement writes no corpus cases at all.
Flagged turns are still counted and still reported; they are simply not ingested, and the report
must make that visible (a measurement that silently added nothing must not look like a
measurement that found nothing).

**R5 · Fresh-corpus ergonomics** (M-4a). Nothing in this aspect may make the *intended* path
harder: ingesting into a new, empty, preserved corpus directory must work unchanged.

## Out of scope

- **Changing what gets ingested** (the `Status.FAIL` trigger, `runner.py:240`) — untouched.
- **Case format / schema version / v1→v2 upgrade** — untouched; a collision is not an upgrade.
- **An `--overwrite` or `--force` re-add.** Deliberately excluded: the engine must not have a
  supported path to overwrite a human adjudication. Re-adding is a human act (delete the case,
  or use a fresh corpus dir).
- **Corpus portability** — `server_command` stays machine-bound; known, unfixed, not here.
- **Merge/dedup, detector identity, control partition, the run, the record correction** — later
  aspects.

## Acceptance criteria (test-first — these are the failing tests, written before the code)

1. **Collision raises `ValueError`, not `FileExistsError`.** `add_case` called twice with the
   same `source_trace_id` + `target_turn_index` raises `ValueError` on the second call, and the
   message names the case id.
2. **No partial write.** After the failed second call, the existing case's `trace.jsonl`,
   `manifest.json`, `prestate/`, `task_prestate/` and `case.json` are **byte-identical** to
   before the attempt. (This is the test that fails against today's code for a reason other than
   the exception type — the truncation at `add.py:272` happens first.)
3. **A human label survives an attempted re-add.** A case labeled `true-positive` with a
   `root_cause`, re-added, still reads back `true-positive` with the same `root_cause`.
4. **A collision does not ERROR the instance.** Through the real `run_batch` with the real
   `add_case` against a corpus dir already containing the target case: the instance's
   disposition is its true value (`VERIFIED_FLAGGED`), the colliding turn appears in
   `flagged_unaddable` with a cause naming the collision, `turn_status_counts` is fully
   populated, and the instance **counts toward `violation_denominator()`**. (Today: `ERRORED`,
   empty counts, excluded from the denominator.)
5. **A denominator cannot be shrunk by re-running.** Two consecutive `run_batch` invocations over
   the same trace dir and same corpus dir produce the **same** `violation_denominator()` and the
   same `violating_instances()`; `instrument_suspect()` is False in both.
6. **`--no-ingest` writes nothing and hides nothing.** With the flag, no case directory is
   created, the flagged turn count is unchanged, and the report states that ingestion was
   disabled.
7. **The intended fresh-corpus path is unaffected.** Ingesting the same flagged turns into a new
   empty corpus dir succeeds and produces a case identical (modulo `captured_at`) to today's.
8. **Deterministic and offline.** No network, no key, no clock read inside `add_case`
   (`captured_at` stays injected).

## Dependencies and sequencing

- **Depends on:** nothing. First aspect.
- **Blocks:** `reverify-measurement` (must not run against the real corpus before this lands) and
  therefore `record-correction`.
- **Touches:** `src/belay/corpus/add.py`, `src/belay/phase0/runner.py` (only if the cause needs
  plumbing), `src/belay/cli.py` (the `--no-ingest` flag), plus `tests/test_corpus_add.py` and
  `tests/test_phase0_runner.py`.

## Open questions / risks

| Item | Assessment |
|---|---|
| **Is `ValueError` the right type, or should a distinct `CaseExistsError(ValueError)` subclass carry it?** | Leaning a subclass **of** `ValueError`, so `runner.py`'s existing handler catches it unchanged while callers can discriminate. Decide in the plan. |
| **Does the pre-write check need to be atomic?** | No. This path is single-threaded and sequential by construction (R7); a TOCTOU race is not in the threat model. State that rather than building a lock. |
| **Could an existence check mis-fire on a partially-written case dir** (e.g. from today's bug)? | Real: dirs already damaged by this bug may exist. The check should treat *any* existing case dir as a collision — conservative, and the operator's remedy is explicit deletion. |
| **Does refusing re-add block a legitimate re-store?** | Yes, by design (see Out of scope). `corpus-task-prestate` re-added the 7 cases deliberately, by hand, after deleting them — that remains the path. |
