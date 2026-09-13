# Understanding — ci-regression-gate

Source: `docs/planning/_card/issue.md` (belay-next handoff brief). Phase 2 of `bbf` — read 2026-09-13 in the worktree.

## What the work really is

`docs/ROADMAP.md:305` (Phase 2 goal #1): *"CI regression gate: a past run replays in CI;
a new agent version that breaks a previously-passing trajectory fails the build. This is
the first surface with obvious budget attached."* And the Phase-1→2 gate's buildable
criterion (`ROADMAP.md:295`): ≥2 users ask for a shared/CI surface. The brief's engine
slice: **baseline-bank + re-run compare** — diff a new capture's trajectory/verdicts
against a stored baseline, report divergence with named causes, bankable into the corpus.

## What exists already (the engine is built, not greenfield)

- `belay verify` — per-turn (`verify_turn`, `src/belay/verify/turn.py:321`) + instance-level
  trajectory (`evaluate_trajectory_rules`, `src/belay/verify/trajectory.py:575`) + A3 claim
  (`evaluate_claim`, `src/belay/verify/claims.py:248`); `--json` machine surface with pinned
  contract (`src/belay/verify/json.py`, `tests/fixtures/verify_json_snapshot.json`).
- `belay phase0 run` — batch verify of a trace dir with `_verify_one_trace(ingest=False)`
  as a pure measurement (`src/belay/phase0/runner.py:241`).
- `belay corpus run` — the detector-side regression gate: `classify_case`/`_divergences`
  (`src/belay/corpus/run.py:436,289`) compute **exact equality of the recomputed sub-verdict
  set** vs the banked expected, with named `(axis, kind)` divergence rows and SKIP-first
  discipline (`_SKIP_CAUSES`). **This is the comparison model the CI gate generalizes.**
- Corpus case schema v5 (`src/belay/corpus/case.py:93`) — expected verdict + stored trace +
  self-contained manifests; `add_case` deterministic ids (`-turnN` / `-trajectory` / `-claim`).

## The gap

- **No run identity in the trace.** Identity is the filename stem only (`trace-<stamp>-<uuid8>`);
  `trace_id` is explicitly NOT unique across stages (`src/belay/phase0/population.py:12-16`).
  A baseline bank needs its own keying (task/instance id). The trace format's unknown-kind
  rule (`src/belay/trace.py:50-54`) makes a new `baseline`/`run_metadata` record kind addable
  without a schema break — but nothing today distinguishes two captures of "the same" run.
- **No capture metadata** (model/prompt/task): proxy records wire bytes only; `claim` text is
  the sole session-level datum.
- **No "expected trajectory" concept at run level** — only at case level (v4 `trajectory`,
  v5 `claim` expected declarations). The bank generalizes "expected verdict of one case" →
  "expected verdicts of a whole run".
- Trajectory comparability is **verdict-dimension** comparison, not structural: per-turn
  status/cause/sub-verdict set + trajectory status/cause/evidence_count + claim status.

## Open questions for the PRD (user to decide)

1. **Banking unit**: baseline = the `--json` report of a verified capture (verdicts only),
   or the full trace + manifests (replayable re-verification, like a corpus case)? Replayable
   costs snapshots on disk; verdict-only costs re-derivation fidelity.
2. **Identity key**: how does the gate know two captures are "the same run"? Explicit
   `--run-id` at capture time (env/flag), or filename convention, or a new trace record?
3. **CI shape**: engine-side CLI only (e.g. `belay gate check --baseline … --capture …`)?
   Where does the build's "new agent version" come from — a fresh capture driven through the
   proxy in CI, or a user-supplied trace?
4. **Divergence policy**: which diffs FAIL the gate vs UNVERIFIED (substrate mismatch,
   nondeterministic turns, toolset changed)? Corpus precedent: SKIP-first, exact-equality.

## Axes / guardrails

- Deterministic spine (A1/A2 + trajectory) only — no LLM, no A3 involvement. Banking keeps
  the corpus compounding (moat #2).
- Not an agent framework; not an LLM judge; UNVERIFIED never rendered as PASS; named causes
  on every abstention; no raw-data egress (baselines stay on the box).
- Flag-parity guard (`tests/test_cli_flag_parity.py`) will demand a deliberate widening
  decision for any new replay-bearing surface carrying `--shell-server`/`--timeout`.

## Contradictions surfaced (flag, don't paper over)

- The belay-next handoff says "no ☐ item remains open, so this pick starts Phase 2" — true of
  the launch checklist (`CHECKLIST.md` gate TRUE 2026-09-06), BUT the Phase-1→2 gate's
  demand-pull criterion (≥2 users ask for a shared/CI surface) is **not** satisfied; the
  roadmap lists the CI gate as Phase-2 goal #1 anyway. The brief's caveat — "roadmap-listed,
  not demand-validated; keep CLI/compose wiring minimal; acceptance tests carry the shape" —
  is the agreed answer: build the engine slice thin, treat UI/compose as follow-on.