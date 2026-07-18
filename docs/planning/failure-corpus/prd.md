# C6 — Failure corpus: PRD

**Capability:** C6 (CAPABILITY_ROADMAP.md §C6). **Depends on:** C1–C5 (all merged, 377 tests green).
**Slug:** `failure-corpus`. **Base:** master @ 5ed31f8. Test-first.
**Source:** `docs/planning/_card/issue.md` + `docs/planning/failure-corpus/understanding.md` (Phase-2 dig).

This PRD resolves the dig's four open questions with recommendations (§Decisions) and flags them for the
review gate. Nothing here is built until the gate approves.

---

## Problem statement

Belay catches corrupt success (A1) and trace infidelity (A2) **per run, then forgets**. Every caught
failure is thrown away after the verdict prints. That wastes the one asset a competitor cannot clone by
reading our source: **labeled, replayable failure cases**. Without a corpus:
- There is **no regression guard** — a change to the detector can silently stop catching a failure it
  used to catch, and nothing notices.
- "Detection improved" is a **vibe**, not a measured claim — we cannot state precision/recall against
  ground truth.
- The Phase-0 gate mints ≥50 hand-audited flags **once** and they evaporate; there is no compounding
  asset.

C6 makes the failure corpus **moat #2, made durable**: each caught failure becomes a stored case, and
`belay corpus run` re-replays the whole corpus asserting each case still reaches its expected verdict —
**the corpus IS the regression suite** — while precision/recall against **human-audited** labels turns
detection quality into a measured number.

## Goals & success metrics

- **G1 — Regression guard exists.** `belay corpus run` re-verifies every case and fails (naming the
  case) when a recomputed verdict diverges from the stored expected verdict. A deliberately regressed
  detector is caught.
- **G2 — Detection quality is measured, not asserted.** Precision, recall, **and coverage** are computed
  against human labels, with UNVERIFIED excluded from P/R and reported on its own coverage line. Matches
  hand-computed values on a fixture corpus.
- **G3 — The Phase-0 audit becomes durable.** A Phase-0 flagged run round-trips into a case and replays
  to the same verdict; the ≥50 audited flags seed the corpus instead of evaporating.
- **G4 — Privacy by construction.** Cases live under the already-gitignored `corpus/local/`; nothing
  uploads, ever. A case is as sensitive as the trace/tree it bundles and is owner-only, never committed.

## Users & scenarios

- **The engineer running agents unattended (Belay ICP).** After a run flags a corrupt success, they
  `belay corpus add` it with a human adjudication, building a private regression suite of real failures.
- **The Belay maintainer.** Runs `belay corpus run` in CI: a detector change that breaks a past case
  fails the build with the exact case named. Publishes precision/recall/coverage as the honest headline.

## Decisions (the dig's four open questions, resolved — flagged for the gate)

- **D1 · Cases are SELF-CONTAINED (bundle the pre-state tree).** A case directory carries its own
  `trace.jsonl`, `manifest.json`, and `prestate/` tree copy. Rationale: a corpus that references external
  scratch dirs evaporates when those are cleaned — durability is the entire point of moat #2. **Cost:**
  `load_snapshot` must resolve a **case-relative** `tree_path` (today it stores an absolute path,
  `persist.py:111`); that small engine change is in-scope. Cases are fat and substrate-locked — accepted.
- **D2 · The server is a per-case STORED `server_command`; unavailability → UNVERIFIED-skip.** The live
  MCP server is load-bearing (its filesystem write is the delta A1/A2 ground on — a recorded-reply stub
  would produce no delta and defeat the check), so it cannot be bundled. The case stores the command
  (pinned by version for off-the-shelf servers; an in-repo fixture server for fixture cases). When the
  server, substrate (darwin/APFS), or capability set is unavailable, `corpus run` reports the case as
  **UNVERIFIED-by-substrate, DISTINCT from a regression** — never a false pass, never a false CI failure.
- **D3 · Layout `corpus/local/<case-id>/`; the human label is an explicit input, default `pending`.**
  `corpus add --label {true-positive|false-positive|unverifiable}`; omitting it stores `pending`.
  Precision/recall **refuses to count `pending`/unlabeled cases**. The engine NEVER authors a label.
- **D4 · The expected verdict pins the PER-SUB-VERDICT set (axis/kind/status), not just reduced status.**
  Catches an axis silently flipping (e.g. A1 FAIL→PASS) while the reduced status is unchanged — a
  stricter, more honest regression assertion.

## Requirements

### Must-have (M)
- **M1 · Corpus case format.** A `corpus/local/<case-id>/` directory: `case.json` (id, target_turn_index,
  expected verdict as the per-sub-verdict axis/kind/status set + reduced status, human_label
  [default `pending`], invariants [scope/rule list], server_command, replays, timeout, provenance [source
  trace id, capture timestamp passed in — never `Date.now()` in engine code], capture platform +
  capability set), `trace.jsonl` (the self-contained slice), `manifest.json` (tree_path rewritten
  case-relative), `prestate/` (the copied tree). Documented format doc.
- **M2 · `load_snapshot` resolves a case-relative tree.** The minimal engine change enabling D1, with the
  absolute-path behavior preserved for existing callers (no C1–C5 regression).
- **M3 · `belay corpus add`.** From a flagged run (records + manifest_dir + computed TurnVerdict for a
  turn), compose a self-contained case: copy the trace slice + referenced tree, record the per-sub-verdict
  expected verdict + policy + server_command, take the human label as explicit input (default `pending`).
- **M4 · `belay corpus run`.** Iterate cases, re-`verify_turn` with the stored inputs, assert the
  recomputed per-sub-verdict set equals the stored expected; on mismatch, report a **regression naming the
  case and the diverging axis/kind**. A case whose recompute is UNVERIFIED-by-substrate/missing-server is
  reported as a **SKIP distinct from a regression**. Exit non-zero on any regression; a pure skip is not a
  regression.
- **M5 · Precision/recall/coverage metric (pure function).** Over cases with a decisive engine verdict
  (FAIL/PASS) AND an adjudicable label (BAD/GOOD): `Precision = TP/(TP+FP)`, `Recall = TP/(TP+FN)`,
  positive = engine FAIL. **UNVERIFIED engine verdicts and `unverifiable`/`pending` labels are EXCLUDED
  from P/R** and reported on a separate **coverage** line (fraction of adjudicable cases the engine
  decided rather than shrugged), broken down by cause. Publishing P/R without coverage is forbidden.
- **M6 · Honest verdict discipline throughout.** UNVERIFIED is never folded into PASS or into a positive
  (mirrors `replay/report.py`'s "not-verifiable is NOT unverified"). The label is never engine-authored.
- **M7 · Two-tier tests.** Pure metric-math + regression-comparison tests run **everywhere** (no replay,
  no network). The real round-trip test (flagged run → case → re-replay → same verdict) is
  **darwin/Seatbelt-gated** exactly like `test_launch_demo.py`. `corpus run` off-substrate skips honestly.

### Should-have (S)
- **S1 · Seed from the Phase-0 audit.** A path to ingest the ≥50 hand-audited Phase-0 flags as labeled
  cases (the corpus starts non-empty). May be a thin adapter over `corpus add`.
- **S2 · `belay corpus label <case-id> --label ...`.** Adjudicate a `pending` case after the fact, so
  `add` need not block on the human.

### Nice-to-have (N)
- **N1 · `belay corpus list` / `corpus show <case-id>`** — inspect the corpus without reading JSON by hand.

## Technical considerations

- **Verdict axis impact: NONE new.** C6 stores and regresses the existing A1/A2 verdicts (`turn.py`);
  it introduces no third grounding and no LLM. This is a persistence/replay/metrics layer.
- **Replay determinism.** `corpus run` re-uses `verify_turn` unchanged; determinism is inherited. The one
  engine change (M2) must not perturb existing replay. No clock/network/random in the corpus path; any
  timestamp is passed in, never read from `Date.now()`/the clock inside engine code.
- **CLI.** New `corpus` subparser group (`add`/`run` + `label`/`list`/`show`), mirroring the `verify`
  subparser + `_cmd_verify` structure in `src/belay/cli.py`.
- **Privacy.** `corpus/local/` is already gitignored (`.gitignore:19`); cases inherit trace sensitivity
  (owner-only perms, never committed, no upload path anywhere in C6).

## Risks & open questions

- **R (moat) — this capability IS the moat asset; under-building it (no coverage line, or an auto-label)
  quietly guts it.** Mitigated by M5/M6.
- **🔴 The 100%-precision-by-construction trap.** If `add` labeled a case "true positive" because the
  engine FAILed it, precision is 100% by construction and meaningless. **Mitigation (non-negotiable):**
  the label is a human input, independent of the verdict; P/R refuses `pending`. A test asserts an
  engine-labeled case cannot be counted.
- **Server availability at run time.** Cases are not hermetic (D2). Mitigated by UNVERIFIED-skip; the risk
  is honestly surfaced, never papered over.
- **Substrate lock (darwin/APFS).** The real round-trip is darwin-gated; the portable tiers (metric math,
  regression comparison) carry CI everywhere. Off-substrate `corpus run` skips, does not fail.
- **Open for the gate:** the four Decisions (D1–D4). Also: should S1 (Phase-0 seed) be in v0 or the very
  next slice, given Phase 0's audited corpus is the actual seed source?

## Out of scope (explicit)
- **Corpus SHARING / sync / any upload** — Phase 2+, opt-in, pattern-level; not v0.
- **Auto-labeling / an LLM adjudicator** — forbidden (that is the LLM-judge non-goal).
- **A corpus UI / dashboard** — that is C7 (live console).
- **Cross-machine / cross-substrate portability guarantees** — a case is honestly substrate-locked; we
  report UNVERIFIED-by-substrate rather than pretend portability.
- **A new verdict axis** — C6 stores and regresses A1/A2; it grounds nothing new.

---

## Aspect decomposition (proposed)
1. **`corpus-format`** — the case format + `load_snapshot` case-relative tree (M1, M2). Foundation.
2. **`corpus-add-run`** — `corpus add` + `corpus run` regression, UNVERIFIED-skip distinct (M3, M4, M6).
3. **`corpus-metrics`** — precision/recall/coverage pure function + report (M5, M6).
(One plan per aspect in Phase 5, built in this order; S1/S2/N1 fold in where cheap.)

## Self-critique (Phase 4)

- 🟢 **Problem/moat alignment** — squarely moat #2; no framework drift, no LLM judge, no egress.
- 🟢 **Honest verdicts** — UNVERIFIED excluded from P/R + coverage line; label never engine-authored;
  regression vs skip kept distinct. The project's contract is enforced in the metric, not just the engine.
- 🟡 **The load-bearing risk is the label trap** (100% precision by construction). The PRD makes the human
  label mandatory-for-counting, but this must be a WATCHED test, not a comment — flagged for the plan.
- 🟡 **Server provisioning (D2) is the weakest seam** — cases depend on an external server binary. The
  honest fallback (UNVERIFIED-skip) is correct but means a shared corpus is only as re-runnable as the
  server pins. Acceptable for a LOCAL v0; note it plainly in the format doc.
- 🟡 **D1 vs D3 scope** — bundling trees makes the corpus fat. Fine locally; if it ever bites, a
  content-addressed shared tree store is a later optimization, not v0.
- 🟢 **Testability** — the metric math + regression comparison are pure and run everywhere; only the real
  round-trip is darwin-gated, matching the existing test discipline.

**Areas to strengthen before building:** (1) make the label-trap test explicit in the plan; (2) confirm
D1 (self-contained + the `load_snapshot` change) is acceptable scope; (3) decide S1 (Phase-0 seed) in-v0
vs next-slice.
