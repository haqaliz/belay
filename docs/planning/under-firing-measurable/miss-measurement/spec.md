# Aspect — `miss-measurement`

**Unit:** `under-firing-measurable` · **Order: LAST.** Covers PRD must-haves M-10 … M-13.

---

## Problem slice

v0.11.0 published **1/15 instances (6.7%)** and could not say whether the 14 silent instances were
clean or unseen. This aspect runs the instrument the first two aspects build, over the banked
captures, **once**, under the freeze protocol — and adjudicates the only held-out evidence that
exists.

It also closes a record defect found during the dig: **the v0.11.0 ledgers were never committed and
no longer exist**. The sole surviving artifact is aggregate prose in
`reverify-measurement/acceptance.out`, which contains zero per-turn lines. `docs/ROADMAP.md` claims
the number *"is re-derivable by a stranger from a committed ledger (`belay phase0 report` is a pure
re-render)"*. Nothing backs that today.

## User outcome

The Phase-0 record states, per instance, whether the detector had anything to judge; the published
number is re-derivable from an artifact in the repository; and the two held-out un-adjudicated turns
in the banked data have a human verdict, in their own evidence grade.

## What the data can support — pre-registered, and it is small

Static survey of all 24 captures (turn counts reproduce `acceptance.out` exactly, 392 non-control).
**17** writes to a `.py` file under a `tests`/`testing` path segment, across **6 of 15** instances;
**9 instances have zero exposure**. Of the 17: **7 flagged** (all `pytest-5227`, fitted-on), **7 are
the already-adjudicated false positives**, **1** is a known-correct PASS. Leaving:

| instance | stage | ledger turn | file |
|---|---|---|---|
| `pytest-dev__pytest-5692` | s3 | 8 | `testing/test_junitxml.py` |
| `pytest-dev__pytest-6116` | s3 | 15 | `testing/test_collection.py` |

**n = 2.** This is an **upper** bound — a write that *creates* a test file cannot weaken anything.

## In scope

- **The frozen measurement.** An `acceptance.sh` committed in a commit containing **no result**,
  run **once**, its **raw, complete, unedited** stdout committed in the next commit, whatever it
  says (`invariant-rule-wiring/acceptance.sh:9-14`, re-used unchanged by `reverify-measurement`).
  Default invariants only. Offline, no API key, no model call. Ingests into a **fresh** corpus dir,
  never `corpus/local/`. Absolute machine-specific paths, justified inline. The script **states
  what it cannot do, inside the script**.
- **`M-10a` — what "the run" means, pre-registered:** one invocation of the committed script, which
  loops the stages internally. An **abort** is **declared** in the write-up and the script re-run;
  clause 3 governs, and an undeclared re-run is a protocol violation. **A re-run to get a different
  answer stays prohibited.** The smallest stage is timed **before** the script is committed, so the
  budget is known rather than discovered.
- **The ledger(s) are committed.** A ledger holds only trace ids, counts, dispositions and causes —
  no raw data — so this does not touch the no-raw-data-egress guardrail, and it makes the number
  re-derivable by `belay phase0 report`.
- **Adjudication of the two held-out turns**, as **human** evidence, reported separately from
  execution. A turn adjudicated a weakening becomes a corpus case labeled `true-positive` **through
  `belay corpus label`** with a human `root_cause` key, plus the `corpus-recorded-miss`
  declaration. **A found-but-unflagged violation is a false negative, not a hand-audited TP** — the
  gate's TP count is untouched either way.
- **Label preservation.** The 7 existing human labels survive **byte-identical**, asserted **per
  case** — *"an aggregate count would let one silently-truncated note through."*
- **Record correction.** A dated `Correction — 2026-08-xx` in `PHASE0_RESULTS.md` carrying: the
  warning banner, originals kept with corrections appended, a literal *"what changed and what did
  not"* table, the **evidence grade** per claim, and what was deliberately left intact. Sync
  `CLAUDE.md`, `CHANGELOG.md` (`[Unreleased]`), `docs/ROADMAP.md` (gate block + R1 row),
  `docs/technical/CAPABILITY_ROADMAP.md`; `README.md:183` as its separate obligation; verify
  `VISION.md` needs no edit **and record that verification**.

## Out of scope

- **Re-deriving any published number.** `4/16`, `precision 0.00`, `3/93`, `0% UNVERIFIED`, `1/15`
  stand unedited; only annotations and new figures are added.
- **Rewriting `CHANGELOG.md`'s shipped entries or any dated planning document** — *"rewriting them
  destroys the provenance trail this project's credibility rests on."*
- Re-minting, re-capturing, moving or copying any banked capture. Both data worktrees stay.
- `subscription-model-client` and the re-mint.

## Acceptance criteria (test-first where testable; the rest are protocol obligations)

1. **The script is committed in a commit containing no result of the run**, names its own freeze
   point, takes **no parameters**, and runs under `set -u`.
2. **`acceptance.out` is the raw, complete, unedited stdout** of that one invocation.
3. **The run is offline** — no network, no API key. If it needs either, that is a defect.
4. **A committed ledger exists**, and `belay phase0 report` on it re-renders the published number —
   asserted by running the pure re-render, not by assertion in prose.
5. **Every instance resolves to one of the three exposure states** in the output; none renders a
   bare silence.
6. **The 9 zero-exposure instances are named**, not merely counted — the reader can check them.
7. **Instrument exposure does not exceed the static bound** (17 turns / 6 instances). Exceeding it
   means the instrument is wrong and **no exposure figure is published** until it is understood; a
   lower count is expected and fine.
8. **The 7 existing labels are byte-identical after the run**, asserted **per case**
   (`human_label` and `root_cause`), never as an aggregate.
9. **Both held-out turns receive a human verdict**, recorded with its evidence grade stated, and
   neither is labeled by the engine.
10. **The write-up's first paragraph states what this is not** — not a gate run (≥50 counts
    *instances minted*, detector-independent), not a precision number, not a base rate at n=2, and
    not comparable to the existing `recall 0.00 (0/1, n=1)`.
11. **The doc-sync inventory is fully addressed**, and no dated record is rewritten.

## Dependencies & sequencing

- **Depends on:** `a1-exposure-accounting` (to report exposure) **and** `corpus-recorded-miss` (to
  store an adjudicated miss). Strictly last.
- **Blocks:** the decision on whether to fund `subscription-model-client` and the re-mint.

## Open questions / risks

- **Runtime is unknown** — v0.11.0's wall-clock was never recorded, and the protocol permits one
  run. Mitigated by timing the smallest stage first (M-10a).
- **The top risk is misreading.** A recall figure at n=2 read as a base rate, or this run read as a
  gate run. Mitigated in the script, in the metrics, and in the write-up's first paragraph — three
  places, because two have not been enough before.
- **A clean adjudication is a success, not a null result** — but it is the outcome most likely to
  be narrated as failure. The pre-registered reading rule exists to prevent that.
- **The corpus stays machine-bound through `server_command`**; this aspect inherits that and does
  not worsen it.
