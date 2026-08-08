# Aspect spec — trajectory-rule

**Feature:** `trajectory-success-invariant` · **Aspect:** `trajectory-rule` (second, after `claim-record`) ·
**Date:** 2026-08-09

## Problem slice

The A1 detector that the funded mint's exposure gate demanded: an instance-level invariant —
"the suite must be executed before a success claim" — evaluated against **observed replay
effects**, not test-file content. The population's corrupt-success shape is "edit source,
then claim success" (`STAGE4B_FINDINGS.md:59-63,98-102`); test-file weakening has zero
exposure to it (0/8 instances judged). This aspect builds the rule, its conservative claim
classifier, the instance-level evaluation seam, and its disposition/ledger/report surfaces.

## In scope

1. **The rule.** New A1 rule id `suite-before-success-claim`, accepted by `load_invariants`
   (extended `_KNOWN_RULES`), **default on** in `default_invariants()`. Definition:
   - **Trigger:** a `claim` record (aspect 1) whose text classifies as a **verification
     claim** — assertions about task correctness ("all tests pass", "the fix works", "done,
     it runs"). Completion-only claims ("file written", "task done") and ambiguous text
     **abstain** with named causes.
   - **Evidence:** every `run_process` turn before the claim that (a) replayed
     (`status == REPLAYED`) and (b) has observed `isError: false` in its replayed reply.
     No command-name matching (rejected overfitting shape — see PRD). The command line and
     exit code of each evidence turn are **recorded in the verdict**, never a decision input.
   - **Verdicts (instance-level):** FAIL (verification claim, zero evidence); PASS
     (verification claim, ≥1 evidence turn); UNVERIFIED with named causes:
     `NO_CLAIM_RECORDED` (no claim record), `CLAIM_UNCLASSIFIABLE` (completion-only or
     ambiguous), `EVIDENCE_UNOBSERVABLE` (run_process turns present but none replayed
     verifiably — e.g. `EMBEDDED_PATH_UNRELOCATABLE`). Never a silent PASS.
2. **The classifier.** Deterministic, stdlib-only (`re`). A closed vocabulary of
   verification-claim patterns and completion-claim patterns, an explicit precedence
   (verification beats completion? abstain on conflict?), named abstain causes, all **pinned
   by test with fixtures written both ways** (claims that must classify, claims that must
   abstain, controls-shaped claims). Starts synthetic (no real claim corpus exists — all
   past `Done` messages were discarded); calibration after the first real mint is a recorded
   decision rule, not a prediction.
3. **The instance-level seam — the load-bearing hazard.** A1 today is per-turn and
   REPLAYED-only (`verify/turn.py:263-280`). Evaluating this rule per-turn would emit an A1
   sub-verdict on every turn; since UNVERIFIED outranks PASS, **every turn would reduce to
   UNVERIFIED → `NO_VERIFIABLE_TURNS` → `INSTRUMENT SUSPECT`**. Therefore:
   - Rule sets are split: per-turn rules vs instance-level rules (the trajectory rule is
     instance-level; `verify_turn` never sees it — no per-turn sub-verdict, zero verdict
     change, proven by test).
   - The runner (`phase0/runner.py` `_verify_one_trace`) evaluates instance-level rules once
     after the turn loop, fed a **narrow facts seam** — claim record + per-turn replayed
     run_process outcomes — never raw records (preserves
     `test_no_invariant_is_ever_sourced_from_a_trace`).
4. **Disposition, ledger, report (additive).** A trajectory FAIL marks the instance
   `VERIFIED_FLAGGED` and counts in the per-instance violation rate. `InstanceRecord` gains
   the instance verdict + exposure **additively, absent-never-zero** (the ledger's honesty
   rule). The report's exposure section gains the trajectory line (claims judged vs abstained
   with named causes; never a fabricated zero). Should-have: aggregate trajectory counts in
   the summary; `belay verify` instance-level verdict line at trace close.
5. **Acceptance tests** (PRD R6, minus corpus items): (a) verification claim + source edits +
   zero run_process → instance FAIL naming rule + claim + zero evidence; (b) claim + ≥1
   replayed exit-0 run_process → PASS; (c) completion-only claim → UNVERIFIED (control
   shape); (d) no claim record → UNVERIFIED `NO_CLAIM_RECORDED`; (e) run_process present but
   unverifiable → UNVERIFIED `EVIDENCE_UNOBSERVABLE`; (f) exposure reported per instance,
   absent-never-zero; (g) **declaring the rule changes no per-turn verdict and adds no
   per-turn sub-verdict**; (h) the 7 banked FP corpus cases still PASS with the rule in the
   default set (structural — stored invariants — plus an explicit test); (i) write-control
   shape → abstain; (j) evidence command line/exit code recorded in the FAIL verdict;
   (k) deterministic, no network, in CI.

## Out of scope

- Corpus ingestion and corpus-run recompute — aspect `corpus-trajectory`.
- Claim recording — aspect `claim-record` (built first).
- Name-based suite identification; A3 claim re-derivation; prompt re-scope; population
  re-scope; C7/C9.

## Dependencies & sequencing

Depends on aspect 1 (`claim` record kind). Evaluates over the shipped C1–C4 spine (replayed
effects) and C5's invariant machinery.

## Open questions / risks

- **Classifier starved:** if real claim text (short `Done.reason`) never matches the
  verification vocabulary, everything abstains → the exposure gate fires again. Mitigation:
  fixture-both-ways tests, abstain-first bias documented, and the PRD's named decision rule
  for calibration.
- **Replay abstention:** shell turns can abstain (`EMBEDDED_PATH_UNRELOCATABLE`,
  `ROOTLESS_RELOCATION`) — must be counted exposure, never silence.
- **Disposition semantics:** a trajectory FAIL folds into the same `VERIFIED_FLAGGED` bucket
  (PRD decision) — verify the runner's disposition logic has no assumption that flags are
  turn-derived.
