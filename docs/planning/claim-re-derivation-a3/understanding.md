# Understanding — claim-re-derivation-a3

> Phase 2 output of `belay-begin-fast`, 2026-09-02. Source: `docs/planning/_card/issue.md`.
> Agent team: 3 explore agents (verdict pipeline / claim machinery / corpus+demo). All claims below cite files in this worktree (v0.26.0).

## What the work really is

C8, the last unshipped engine capability: **axis A3, claim re-derivation**. A model *writes* an
executable check for the agent's asserted post-conditions (the trace's `claim` record); the engine
*executes* it in the sandbox against the recorded final state; the **exit code — not the model's
opinion — decides**. A3 may emit only WARN / FAIL / UNVERIFIED, never PASS. `--no-claim-axis`
disables it; every PASS/FAIL verdict must survive unchanged (the refutation, enforced by test).

## What exists today (all verified by grep/read)

- **The claim record exists** (capture side): `src/belay/trace.py:389 append_claim_record`; readers
  get it as a `Skip` carrying `record` (`src/belay/replay/reader.py:63-69`); schema in
  `docs/technical/TRACE_FORMAT.md:241-300`. The demo capture's claim: *"All 6 tests pass. Fixed
  app.py…"* (seq 21, VERIFICATION-classified).
- **The claim classifier is a pure, reusable seam**: `classify_claim_text` (`src/belay/verify/trajectory.py:112-126`),
  closed deterministic regex vocabulary, abstain-first (`VERIFICATION`/`COMPLETION`/`AMBIGUOUS`/`NO_TEXT`).
- **The instance-level evaluation seam exists**: `evaluate_trajectory_rules` (`trajectory.py:575-622`),
  called at trace close from `belay verify` (`src/belay/cli.py:738-750`) and `phase0 run`
  (`src/belay/phase0/runner.py:369-384`). This is where an A3 evaluator sits beside A1's trajectory rule.
- **The verdict machinery is already A3-ready by construction**: `reduce` is axis-agnostic
  (`src/belay/verify/verdict.py:17-21, 99-117`); the A3 downgrade-only property "falls out for free".
  Rendering loops are per-axis (`cli.py:789-791, 1021-1027`).
- **`--no-claim-axis` does NOT exist anywhere in `src/`** — only in docs and a test comment
  (`tests/test_verify_zero_llm.py:150-152`, which is the zero-LLM guard's deliberate escape hatch).
  The flag + refutation test are the first deliverable.
- **No A3 code exists** — no check author, no synthesized-check runner, no A3 verdict path.
- **Zero runtime dependencies is load-bearing** (`pyproject.toml:44`); LLM SDKs live only in the
  `eval` extra. The A3 model client therefore cannot be a runtime dependency — it must be an
  injectable seam with an out-of-process / optional-author shape (BYOK, nothing proxied, no egress).
- **Execution machinery to reuse**: `contained(argv, workspace=…, network=…)` (`src/belay/sandbox/launch.py:188-248`),
  `load_snapshot` / `guarded_restore` (`src/belay/replay/persist.py:132`, `snapshot/substrate.py:409`),
  `scan_tree`/`diff_records` (`snapshot/bth1.py:393,414`). The replay engine's restore-then-run pattern
  (`replay/engine.py:602-637`) is the template for "restore final state, run the check".
- **Corpus**: case schema v4 added the instance-level `trajectory` expected field
  (`src/belay/corpus/case.py:82-88`); an A3 instance-level case mirrors that pattern (schema v5).
  `corpus run`'s `classify_case` exact-equality covers new axes with zero new code for per-turn
  sub-verdicts; instance-level needs the trajectory-style routing (`src/belay/corpus/run.py:479-543, 390-425`).
- **Cause bucketing**: `canonical_cause`'s `_PREFIX_LABELS` (`src/belay/replay/report.py:140-158`)
  needs `A3/...` prefix labels ahead of the catch-all, else A3 UNVERIFIEDs fall into a bland bucket.

## Axis placement (the verdict contract)

- A3 is **instance-level by construction**: the claim is session-level (one `claim` record per trace),
  and the check runs against the **recorded final state**. A per-turn A3 verdict has no meaning.
  The FAIL flags the instance (trajectory-style `VERIFIED_FLAGGED` disposition), banks an
  **intent-drift** corpus case, and never rewrites any turn verdict.
- A3 emits **no sub-verdict when the check exits 0** (the claim re-derives; the axis cannot certify,
  so it stays silent — silence is not PASS). FAIL on non-zero exit. UNVERIFIED with a named cause
  when: no claim, unclassifiable claim, no check author configured, check cannot execute, timeout,
  unrestorable final state.
- The refutation guarantee is near-trivial *per turn* (A3 never touches turns) and meaningful at the
  *instance* level: with and without `--no-claim-axis`, every stored case's expected verdict and
  every disposition must be identical — enforced by test over the corpus.

## Open questions (carry into the PRD interview)

1. **Acceptance (4) vs the amended demo.** C8's acceptance says *"the launch demo: 'all tests pass'
   re-derived against the original suite yields exit 1 → FAIL"* — written against the pre-2026-08-27
   demo (a corrupt success). The shipped demo is the **negative control** (agent fixes honestly,
   all green, claim TRUE at final state). Running the demo's check against its final state exits 0
   (claim re-derives → A3 silent → demo stays green). The FAIL path needs a fixture the final state
   does not satisfy — e.g. the mint's actual corrupt-success shape (*"edit source, claim success"*
   with a failing suite) — which is also the shape A1's trajectory FAIL catches: two independent
   axes, same fixture = the intended "corroboration". Propose re-scoping acceptance (4) to
   (a) demo stays green with A3 present (pinned by test), (b) a synthetic corrupt-success fixture
   yields A3 FAIL corroborating A1 FAIL. Needs owner confirmation.
2. **Check form and execution.** Check author produces one executable artifact (POSIX shell script
   or declared argv), run via `contained` against the restored final workspace, network deny-all,
   bounded timeout; exit code + captured output are the facts. Confirm.
3. **Author seam / BYOK shape.** Zero runtime deps must hold. Propose: a `CheckAuthor` protocol
   (injectable, deterministic fakes in tests) + out-of-process reference author invoked by
   subprocess (local CLI / user script / local model endpoint the user points at — nothing leaves
   the box). No author configured → A3 abstains `NO_CHECK_AUTHOR`. Confirm.
4. **`--no-claim-axis` surface.** Per-command flag on the surfaces where A3 can evaluate
   (`belay verify`, `belay phase0 run`, `belay corpus run`), declared in the CLI parity guard
   (`tests/test_cli_flag_parity.py:45-75`). Confirm.
5. **Exit-0 behavior** (silence vs WARN). Recommended: silence — WARN would downgrade every honest
   run and break the demo's pinned all-green. The spec's "exit code is the verdict" forces this
   reading since PASS is forbidden.

## Constraints that bind the plan

- Moat: sandbox / replay / execution-grounded verification + corpus. The model is a *check author*,
  never a judge; execution decides. No agent framework, no raw-data egress, no vendor key.
- UNVERIFIED is never PASS; every A3 abstention has a named cause in a closed vocabulary.
- Test-first: the five acceptances in `CAPABILITY_ROADMAP.md:792-802` are written as failing tests
  before any code; model calls never run in CI (fake injected; manual gate for the live path).
- The zero-LLM import guard (`tests/test_verify_zero_llm.py`) is updated as a deliberate, visible
  decision — never sidestepped.
- `NOT_COVERED` and the A1/A2 axes are untouched; `verdict.reduce` is not modified.