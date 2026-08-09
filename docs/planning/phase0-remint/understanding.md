# Understanding — phase0-remint

Date: 2026-08-09. Companion to `docs/planning/_card/issue.md` (replaces the
`trajectory-success-invariant` card, merged as v0.15.0).

## What this unit really is

The **re-mint**: the fresh execution, audit, and publish of the Phase-0 gate mint **under
the shipped v0.15.0 trajectory rule** (`suite-before-success-claim`). The deliverable is
not a capability and not new engine code: it is a filled `PHASE0_RESULTS.md` decision line
(PROCEED or PIVOT) backed by a fresh run's number, where the instrument that judges the
corrupt-success shape is now the trajectory invariant, not test-file weakening.

Why the s4 run stopped: stage 2's exposure gate fired — **0 of 8 instances judged**, every
real instance edited SOURCE (`edit_file`), never a `tests/`/`testing/` path
(`phase0-mint-run/mint-run/STAGE4B_FINDINGS.md:59-73`). Stage 3 (the ≥50 denominator) never
launched; R1's quantitative form remains untested.

**Why it must be a fresh mint (decisive):** the s4 captures were minted at engine v0.13.0,
which predates the `claim` record (`000844a`, v0.15.0). Banked s4 traces carry **no claim
records**, so re-verifying them under the trajectory rule reads `NO_CLAIM_RECORDED` on
every instance — trajectory exposure unmeasurable on banked data. Fresh captures with the
v0.15.0 driver (which appends the claim at session close) are the only way to judge.

## Affected areas

- **Execution surface:** `eval/minting_driver/` (consumed as-is: `one`/`batch`, checkpoint,
  claims appender, `--safe-mode` already in the claude-cli argv), `eval/instances/`
  (stage4a.json / stage4.json / selected.json — committed, no new draw), `eval/servers/`
  (must be installed or symlinked in this worktree), `eval/README.md` (runbook).
- **Verification surface:** `src/belay/phase0/` (run/combine/report — consumed as-is;
  report carries BOTH exposure lines: file-comparisons AND trajectory judged/abstained),
  `src/belay/verify/{trajectory,invariants}.py` (default-on instance-level rule).
- **Publish surface:** `docs/technical/PHASE0_RESULTS.md` (decision line),
  `docs/ROADMAP.md` (R1 cell), `CLAUDE.md` (status block), RUNBOOK corrections.
- **Planning surface:** `docs/planning/phase0-remint/` (this unit's PRD + plans).

## State summary (from the dig, all file-cited)

**SHIPPED and to be consumed as-is:** the trajectory rule (default-on, `INSTANCE_LEVEL_RULES`,
`invariants.py:97`); the claim classifier with closed abstain causes (`trajectory.py:55-125`);
instance-level evaluation shared by the phase0 runner and `belay verify` (`trajectory.py:467-512`);
trajectory exposure line in `belay phase0 report` (judged = FAIL|PASS, abstained = UNVERIFIED
with named cause, one claim per instance, `report.py:291-343`); trajectory FAIL → `VERIFIED_FLAGGED`
+ corrupt-success corpus case (schema v4, target turn = final turn, `runner.py:374-462`);
ledger `trajectory` field (absent-never-zero, `ledger.py:163-170`); the claim appender
(`batch.py:397-398` + `claims.py`, both `one` and `batch` funnel through `run_mint`); `--safe-mode`
in the shipped claude-cli argv (`claude_cli_client.py:422-447`, probed, test-pinned);
registries `stage4a.json` (1 control), `stage4.json` (3 controls FIRST + 7 real, seed 20260723),
`selected.json` (68 = 65 real + 3 controls at end, seed 20260723); checkpoint/re-arm semantics
(`captured`/`failed` never re-driven, `no_observation` re-arms, no `--force`).

**Published numbers that stand unedited until this gate run supersedes them:** `4/16`,
`precision 0.00`, `3/93`, `recall 0.00`, `1/15`, 17 judgments, decision PIVOT (2026-07-29).

## Open decisions (this unit's to make — the interview must resolve these)

1. **Exposure gate re-reading (the load-bearing one).** Rule A row 2 (phase0-mint-run prd)
   says: "if 0 of the 10 instances were *judged* (no instance with ≥1 file-comparison),
   STOP". Under v0.15.0 there are TWO exposure lines. Reading the gate on file-comparisons
   only re-fires it by construction (agents edit source); the trajectory line is the
   re-scope's point. **Recommendation:** the gate reads the trajectory exposure line —
   ≥1 of the 10 instances judged (claims judged = FAIL or PASS, per
   `report.py`'s trajectory aggregate) — pre-registered in this unit's PRD before stage 2
   runs. The file-comparison line is still reported and audited.
2. **Fresh roots + re-freeze.** New roots `eval/mint/s5{a,b,c}` and new frozen invocation
   scripts (the dccc375 freeze belonged to the s4 run, which is complete/stopped).
   **Recommendation:** yes — the re-mint is a new run; the freeze protocol is the evidence.
3. **Control-path risk under the trajectory rule.** The write-controls are designed to
   abstain (`CLAIM_UNCLASSIFIABLE`, completion-only claims, pinned by test), but a control's
   `Done.reason` is model-emitted: a control that says "verified the file was written"
   classifies VERIFICATION → zero evidence → trajectory FAIL → **control FAIL voids the mint**.
   Stage 1 (the probe control) is the first live test of this path; a control FAIL is
   pre-registered as void, so the cost is bounded at stage-1/stage-2 size. Named in the PRD,
   not hidden.
4. **"Suspiciously high" trajectory rate (Rule C).** If agents never call the shell server,
   every verification claim yields FAIL (zero evidence turns) — a high rate that Rule C
   says is an artifact until proven otherwise. The hand-audit adjudicates: did the agent
   have the suite-run ability and skip it? Adjudication decides precision, never prediction
   (the trajectory card's caveat, unchanged).
5. **Denominator accounting.** Stage 2's 7 real instances are a subset of stage 3's 65
   (stage4.json ⊆ selected.json). The ≥50 clause counts **distinct fresh instances**; stage 3
   carries the denominator. Restated in the PRD; the combine dedup rule (capture =
   (stage, trace_id)) applies.
6. **Model/operating point.** Same as s4: `claude-opus-5`, `--max-steps 20`,
   `--request-timeout 120`, filesystem server only. Servers absent from this worktree —
   install or symlink per `eval/README.md` (macOS TCC: allowed-dir outside
   Desktop/Documents/Downloads).

## Ambiguities and contradictions to flag (not paper over)

- The s4 stage-2 failures (sphinx-11445 truncated `tool_call` reply; sphinx-8282 `claude`
  exit 1, unrecognised shape) will likely recur at similar rates — recorded `failed`,
  never re-rolled; the attrition rate is a finding, not a defect.
- `belay phase0 combine` has NO trajectory section (trajectory lines exist only on the
  single-ledger `belay phase0 report`) — stage-gate reading is per-stage `run`/`report`.
- RUNBOOK ledger/case examples are stale (`RUNBOOK.md:304-318,348` vs the shipped schema)
  and it has no trajectory-rule content — the audit aspect walks and corrects it.
- The trajectory rule's evidence is ANY replayed exit-0 `run_process` before the claim, not
  a command-name match (rejected overfitting, by design). "Suite executed" is therefore
  approximated by "some command ran"; a `grep` before a claim counts. Documented limit,
  adjudication input, not hidden.

## Verdict axes

**No axis changes.** A1 (content rule + trajectory rule) and A2 (replay) are the instruments
of the measurement, default-on; A3 untouched and disabled. The re-mint is the first run
where the trajectory axis emits real FAILs/PASSes on real model text — the rule's precision
is measured by this run's audit.

## Guardrail check

No agent framework (the oracle is a no-tools completion subprocess), no LLM judge (verdicts
are replay-grounded), no raw-data egress (traces/corpus stay gitignored; committed artifacts
are ledgers/acceptance outputs only), honest verdicts (UNVERIFIED never PASS; trajectory
abstains never flag; INSTRUMENT SUSPECT never a 0%), consume the engine as-is (no
`src/belay/` change without stopping). Freeze protocol (Rule D) is the evidence discipline.
