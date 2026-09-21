# Spec — aspect `budget`

**Problem slice:** the pure decision machinery — given per-turn triage scores, which turns
get the expensive replay, and the honest vocabulary for the ones that do not.

**In scope**
- Pure functions: threshold (replay iff confidence ≤ threshold) and top-N-least-confident
  (replay exactly the N most suspicious), composable.
- Shadow mode: a configured command with no budget knobs ⇒ replay everything, scores
  recorded alongside, nothing skipped.
- The named skip cause: `TRIAGE_SKIPPED_BY_BUDGET` (or a cause family) registered in the
  closed vocabulary (`src/belay/replay/report.py:69-138,152-172` `_PREFIX_LABELS`) with
  the closed-vocabulary guard pattern (`tests/test_interop_attach.py:476-494`) applied.
- A skipped turn is `UNVERIFIED`-by-budget — never PASS, never WARN, never a silent skip.

**Out of scope:** the turn loop integration (surfaces), the ledger, any verdict authority.

**Acceptance (test-first)**
- Threshold and top-N each skip exactly the named turns on a fixture score set; combined
  behavior is the intersection or union as specified in the PRD (union — either knob may
  spare a turn).
- Shadow mode (no budget knobs) skips nothing and records every score.
- The skip cause renders on every surface that reports turns, and the closed-vocabulary
  guard fails if a new bucket is added without registration.
- An empty / all-abstain score set (every triage call returned None) ⇒ nothing is skipped
  — fail-open, full replay.

**Dependencies:** `triage-seam`. **Sequencing:** third (before surfaces, which consumes
the decision).

**Open questions:** none blocking — knob combination semantics resolved to union above.