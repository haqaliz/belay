# Spec — aspect 2: `registry-rescope` (eval)

Unit: `feat/phase0-gate-mint` · Source: `docs/planning/phase0-gate-mint/prd.md` M6-M7 ·
Eval-only (NOT a product surface) · Deterministic + test-pinned.

## Problem slice

Three registry defects stand between the harness and a clean gate run:

1. **Unsteered write controls.** `stage4.json`/`stage4a.json` still carry the UNSTEERED
   CTL-2/CTL-3 task text (only `selected.json` was regenerated;
   `composition-note.md:44-51`). Reusing them re-opens the D-3 tripwire that voided the
   re-mint (an unsteered write control emitting a verification claim with zero commands →
   trajectory FAIL → void).
2. **CTL-4 composed nowhere.** `control__flask-verify-with-command` (expected trajectory
   PASS) is held out of `CONTROL_RECORDS` and every committed registry
   (`eval/instances/controls.py:220-224`). The PRD places it in **stage 1**.
3. **No fresh ≥50 pool.** The committed 68-draw contains ~15 already-observed ids
   (stage2/stage4/banked/smoke/s3); the gate counts ≥50 distinct FRESH verified instances.
   Stage 3 needs a fresh draw of 80 real + 3 controls with a new committed seed, excluding
   every previously-minted id. Also: `stage2.json`'s header (launched 68/real 65) contradicts
   its 10-record list — regenerated stage files must carry consistent headers.

## In-scope requirements

1. **Stage composition (per the PRD, interview-decided):**
   - Stage 1 (probe): CTL-1 + CTL-4 — 2 records.
   - Stage 2: CTL-2 + CTL-3 + 7 fresh real — 9 records, controls first.
   - Stage 3 (the ≥50 denominator): fresh draw 80 real + 3 controls from the 166-pool,
     new committed seed, excluding every previously-minted id.
2. **Observed-id set is derived and evidenced.** The previously-minted set = the real ids in
   committed stage registries (`stage2.json`, `stage4.json`, `stage4a.json`) + the banked
   corpus ids (`EXCLUDED_INSTANCE_IDS` in `eval/scripts/build_stage4_registry.py`) + the
   smoke instance (`pytest-dev__pytest-7432`) + the s3-partial observed ids (from the
   committed s3 ledger). The set is written to a committed artifact (e.g.
   `eval/instances/observed.json`) by a deterministic script, and every draw asserts **no
   overlap by test**.
3. **Regeneration is script-driven and byte-reproducible.** Extend/replace the committed
   generators (`eval/scripts/draw_mint_set.py` — targets, seed, exclusion;
   `eval/scripts/build_stage4_registry.py` — hardcoded 3+7 shape) so the three stage files
   regenerate deterministically from `pool.json` + `controls.py` + `observed.json`; the
   committed files are the script output (test-pinned: regeneration is byte-identical).
   Stage files carry the composition in their headers; the `stage2.json` inconsistency is
   fixed by regeneration (the stale file is replaced or its header corrected — decided at
   implementation, recorded in the run aspect).
4. **Control text always current.** Regenerated registries pull task text from
   `CONTROL_RECORDS` / `POSITIVE_CONTROL_RECORD` at generation time — steering sentences
   can never drift from `controls.py` again (test-pinned).
5. **Selection semantics preserved.** The 83% django+sympy rebalance, small-repo block,
   `_alternating_topup`, seed reproducibility, and no-silent-re-roll rules of
   `selection.py` are unchanged; only the exclusion set and target size differ.

## Out of scope

- Any change to `controls.py` content or `CONTROL_EXPECTATIONS` (the task texts and expected
  verdicts are the preceding unit's shipped artifact).
- Changes to `pool.json` (166-pool is the committed strict-eligible universe).
- The run itself (aspect 3); the verify composition (aspect 1).
- Migration of the 5 banked remint FP corpus cases (documented debt; they live in the remint
  worktree's gitignored `corpus/local/`).

## Acceptance criteria (tests written first)

- **AC-1**: `observed.json` derives exactly from the committed sources (enumeration is
  deterministic; regeneration is byte-identical; the set is asserted non-empty and excludes
  no control).
- **AC-2**: stage1 = CTL-1 + CTL-4 (2 records, in that order); stage2 = CTL-2 + CTL-3 + 7
  fresh (9, controls first, all 7 real ids ∉ observed.json); stage3 = 80 real + 3 controls,
  all real ids ∉ observed.json, seed recorded, controls appended.
- **AC-3**: every control record in every generated stage file carries the steering sentence
  for CTL-2/3 verbatim from `controls.py` and the CTL-4 mandated-command task text verbatim.
- **AC-4**: every real id appears in at most one of the three stage files (no cross-stage
  re-mint), and stage 3's 80 are distinct.
- **AC-5**: regeneration from committed sources is byte-reproducible (deterministic, no
  network; the draw seed and exclusion path are recorded in the file headers).
- **AC-6**: `load_registry` accepts all three regenerated files; headers parse; no instance
  is a control unless its id starts with `control__`.
- **AC-7**: stage3 contains ≥50 real ids that can still be verified fresh — the ≥50
  requirement is expressible as a test on the committed artifact.

## Dependencies & sequencing

- Requires: committed `pool.json`, `controls.py` (v0.17.0), the scripts above.
- Parallel-safe with aspect 1; needed by aspect 3 (the freeze scripts reference the new
  stage files by path, not content — so aspect 2 can land after aspect 1's CLI without
  coupling, but must land before the stage-1 freeze).
