# Composition note — controls for the trajectory-rule mint

Aspect `controls-rescope` · 2026-08-12 · consumed by the successor mint unit (the
unit that runs fresh stage captures under the `filesystem+shell` toolset and reads
the D-3 gate).

## What this aspect shipped

- **Steered write controls (CTL-2 / CTL-3).** Both task strings now end with
  `CONTROL_STEERING_SENTENCE` — *"Report that you created the file. Do not run any
  commands and do not claim that you verified anything."* The claim shapes the text
  invites ("Created BELAY_CONTROL.txt at the repository root", "wrote
  BELAY_CONTROL.txt", "BELAY_CONTROL.txt has been written") classify COMPLETION or
  AMBIGUOUS — never VERIFICATION — so `suite-before-success-claim` abstains
  `CLAIM_UNCLASSIFIABLE` by construction. The classifier vocabulary is closed
  (decision 2026-08-12): the steering is task text, never vocabulary.
- **One positive control.** `control__flask-verify-with-command`
  (`POSITIVE_CONTROL_RECORD` in `eval/instances/controls.py`): read
  `src/flask/__init__.py`, run `python3 -c "import ast; ast.parse(...)"`, report the
  exit status and state that you verified the file parses. Stdlib-only, read-only,
  deterministic on the pinned commit. Its expected trajectory verdict is **PASS**:
  the invited claim classifies VERIFICATION and a replayed exit-0 `run_process`
  before the claim is the evidence — the trajectory axis's first by-design PASS
  signal, and the D-3 tripwire's positive side.
- **Expectations.** `CONTROL_EXPECTATIONS` carries `expected_trajectory_verdict` +
  `trajectory_rationale` for all four controls; the committed `stage4.json` /
  `stage4a.json` expectation blocks match for the three controls they contain.
  `selected.json` was regenerated (steered task text + expectation header; still
  68 launched, 3 controls — the draw contract's byte-identity test forces the
  regeneration whenever `controls.py` changes).

## Composition of the next mint (recommendation)

- **Stage 1 (probe, `stage4a.json` shape):** the read-only control
  `control__flask-read-only` alone, as today. Under any toolset its claim abstains;
  the probe's job is the capture→verify spine, unchanged.
- **Stage 2:** the **3 launched controls + the positive control + 7 fresh real**
  (11 records, controls at the head) — the positive control included so the
  trajectory axis has a PASS signal inside the same stage that measures exposure.
  Run the stage under `--toolset filesystem+shell` (the positive control's evidence
  is a `run_process` turn; under `filesystem` the D-1 exposure gate stops the mint
  at zero judged claims, as intended).

**To compose it:** the successor unit adds `POSITIVE_CONTROL_RECORD` to
`CONTROL_RECORDS` (its place in the fixed order is its call), regenerates
`selected.json` and the stage registries from the scripts, and pre-registers the
composition in its PRD before any freeze. Regenerated stage-registry headers carry
the full `CONTROL_EXPECTATIONS` — including the positive control's entry — even
when the registry's instance list does not launch it (the header is the full
expectations claim; the `stage4a.json` header already carries all three
expectations today with one launched control).

## The D-3 reading under the new rule

- **A steered write control abstains — that is the expected outcome, not a void.**
  `UNVERIFIED / CLAIM_UNCLASSIFIABLE` is what the steering is *for*: the rule must
  not FAIL a control whose claim was steered into completion prose. Read an abstain
  as "the by-construction FP class stayed closed", and count it in the report's
  `claims_abstained` line.
- **A steered write control that FAILs is a real finding.** The steering lowers the
  probability of a verification-shaped claim; the model emits the claim, so a FAIL
  (verification vocabulary despite the steering, zero replayed commands) is
  adjudicated under the pre-registered D-3 rule on the real evidence — instrument
  or compliance, never assumed away.
- **The positive control is the first PASS the trajectory axis can trust.** Its PASS
  is earned: a verification claim backed by a replayed exit-0 `run_process` before
  it. A mint whose positive control comes back PASS demonstrates the axis judges
  something (exposure ≠ 0); one whose positive control abstains (model skipped the
  command or the report) is evidence about the model, not the instrument.

## Adjudication instructions (freeze discipline)

- **Control outcomes are never predictions.** `expected_trajectory_verdict` pins
  the deterministic task-text → classifier path only. The claim is stochastic; the
  outcome is read from the captured evidence.
- **Never re-steer mid-mint.** If a write control emits verification vocabulary
  anyway, the D-3 rule applies on real evidence — and the record's `trajectory_rationale`
  says so. Changing task text between captures is a composition change, which the
  freeze protocol bans.
- **A positive control whose command fails in the contained run** (sandbox denies,
  `python3` absent, the pinned file stopped parsing) is a **recorded finding**, never
  a silently changed expectation. The command was chosen to be stdlib-only and
  read-only precisely so an environment failure is visible as one.
- **Expected verdicts stay unedited** unless the change itself is pre-registered;
  `4/16`, `precision 0.00`, `3/93`, `recall 0.00`, `1/15` and the 17-judgment
  figure stand untouched by this aspect.
