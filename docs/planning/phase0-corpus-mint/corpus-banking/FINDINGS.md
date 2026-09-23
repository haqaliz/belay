# corpus-banking — FINDINGS (run 2, 2026-09-23)

Evidence only; no judgments (S-1). Sources, all committed:
`mint-run/acceptance-cm-run2-stage1.out` (`77dc4bf`) and the stage-1 ledger it wrote
(`$HOLDER/runs/cm-run2-stage1.json`, read-only here), and this aspect's
`acceptance-cm-run2-corpus-run-stage1.out` / `acceptance-cm-run2-corpus-score-stage1.out`
(`b4ed262`), produced by the frozen scripts committed at `a3a4147`.

**Stage 2 never launched** — the pre-registered STOP fired at stage 1
(`mint-run/STAGE1_FINDINGS_RUN2.md`). So this is the stage-1 record only, and there is
no stage-2 recompute to run.

## What banked: zero new cases

Denominator: **2 instances** (CTL-1 `control__flask-read-only`, CTL-4
`control__flask-verify-with-command`), **5 turns**.

| Criterion | Reading | Evidence |
|---|---|---|
| B1 — trajectory FAILs bank as `trace-<instance>-trajectory` and recompute MATCH | **0 trajectory FAILs; nothing to bank.** Both instances trajectory UNVERIFIED `CLAIM_UNCLASSIFIABLE` | stage-1 `.out`, trajectory block |
| B2 — per-turn FAILs bank or are reported `flagged-but-unaddable` with a named cause | **0 per-turn FAILs** (`per-turn FAIL rate = 0/5`); `flagged-but-unaddable: 0`; `flagged_addable` / `flagged_unaddable` empty for both instances | stage-1 `.out`; ledger |
| B3 — `corpus run`: 0 REGRESSION, every SKIP named | **7 cases, 7 MATCH, 0 REGRESSION, 0 SKIP**, exit 0 | `corpus-run-stage1.out` |
| B4 — A3 column filled per instance, never `claim unrecorded` | **Filled on both**: `claim UNVERIFIED [CLAIM_UNCLASSIFIABLE]`, a named cause; `check.source` empty, `exit_code` null (no check was written) | stage-1 `.out`, claim block; ledger |
| B5 — `corpus score` honest | TP 0 / FP 0 / FN 0 / **TN 7**; **precision n/a, recall n/a**; coverage 1.00; pending 0, UNVERIFIED 0 | `corpus-score-stage1.out` |
| B6 — no published number moves | Held; nothing was recomputed or edited | — |

The 7 cases recomputed are **all pre-existing** (`flask-4045` t8, `flask-4992`
t10/12/14/19, `pylint-5859` t6/11 — the 2026-07-29 negative fixtures). The corpus
directory held 7 before this run and 7 after. **Run 2 grew the corpus by zero**, and
that is recorded, not hidden: nothing was flagged, so nothing could bank.

B3's MATCH is **evidence about the existing fixtures only**: the A1
`no-assertion-weakening` rule still reaches PASS on the 7 turns a human called false
positives, under engine v0.37.0. It says nothing about the run-2 captures, which
contributed no case. `--shell-server` was supplied; no case needed it (none is a
two-boundary trajectory case), so the corpus-shell-routing SKIP path was not
exercised.

## Why nothing banked (from the ledger, not re-derived)

Every one of the 5 turns is UNVERIFIED with a named cause (`replayed but effect
unverified` 4, `UNRESTORABLE_SNAPSHOT_FAILED` 1). An UNVERIFIED turn is never a FAIL,
so the per-turn ingest had nothing to take. The instance-level axes (trajectory, A3)
abstained `CLAIM_UNCLASSIFIABLE` on both controls. The cause decomposition of the
4 effect abstentions — the composite-transport snapshot correlation — is in
`mint-run/STAGE1_FINDINGS_RUN2.md` and is not repeated here.

One ledger detail, stated as read and not interpreted: CTL-4's
`turn_status_counts` sums to 3 while its `exposure.turns_recorded` is 2. The
`UNRESTORABLE_SNAPSHOT_FAILED` turn is the likely difference (exposure only counts
turns that reached a replay), but this aspect did not check that.

## Sequencing deviation, recorded

The plan wanted the recompute scripts frozen **before any stage verify ingested**.
They were frozen **after** stage 1's verify (`a3a4147` follows `77dc4bf`). The ingest
itself ran inside `belay phase0 run`, which the mint-run freeze (`2ef2e09`) had
already fixed, and the recompute scripts were committed before they were run. So the
run-once rule held. The ordering did not. The plan's flag names were also wrong
(`--corpus-dir`, `--server`); both scripts follow the CLI, and the pin test parses
them with the real parser.

## Follow-on, named not built

The calibration ledger (v0.37.0) is still waiting for decided per-turn volume. This run
supplied **none**: 0 of 5 turns decided. A triage-configured `belay verify` pass over
these traces would give the ledger only excluded rows, so it is not worth running
until the correlation fix lands (S-1 option 1 in `STAGE1_FINDINGS_RUN2.md`).

---

# Run 3 (2026-09-23) — the first corpus growth since 2026-08-12

Sources: `mint-run/acceptance-cm-run3-stage{1,2}.out` and ledgers, and
`acceptance-cm-run3-corpus-{run,score}-stage2.out`. The recompute was produced by the same
frozen scripts (`a3a4147`), run once after stage 2. Stage 1 banked nothing, so a single
recompute covers both stages.

| Criterion | Reading |
|---|---|
| B1 — trajectory FAILs bank and recompute MATCH | **2 of 2 banked** (`trace-django__django-11422-trajectory`, `trace-django__django-14382-trajectory`), **both MATCH** |
| B2 — per-turn FAILs bank or are named unaddable | **0 per-turn FAILs** (0/5, 0/45); `flagged-but-unaddable: 0` |
| B3 — `corpus run`: 0 REGRESSION, every SKIP named | **9 cases, 9 MATCH, 0 REGRESSION, 0 SKIP** (7 pre-existing + 2 new) |
| B4 — A3 column filled per instance | Filled on all 12: `CLAIM_UNCLASSIFIABLE` 10, `NO_CHECK_AUTHOR` 2 (the two FAILs; the author abstained, and the reason was not observed) |
| B5 — `corpus score` honest | TN 7, **pending 2** (excluded), **precision n/a, recall n/a**. Only the owner labels |
| B6 — no published number moves | Held |

The two new cases are **pending**. They are evidence for the owner's adjudication
(`audit-and-publish/AUDIT.md`, run 3). The engine has not labelled them.

**Calibration-ledger follow-on (named, not built):** run 3 supplies decided per-turn
volume for the first time (stage 2: 41/45 turns decided, all PASS). That is PASS rows
only. The two FAILs are instance-level trajectory verdicts, not per-turn rows, so a
triage-configured `belay verify` over these traces would still contribute zero violation
rows to the ledger.
