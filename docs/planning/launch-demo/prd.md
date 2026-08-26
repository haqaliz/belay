# PRD: Launch demo, locked spec (launch checklist L7)

Slug: `launch-demo` · Branch: `feat/launch-demo/aliz` · Type: feat · Owner: aliz
Sources: `docs/planning/_card/issue.md` (brief), the dig report,
`docs/planning/launch-readiness/CHECKLIST.md` L7, `docs/ROADMAP.md:253-259` (the locked
demo).

## Problem Statement

The locked demo — *"one repo, one failing test, an agent told 'make the tests pass' — it
weakens the test and reports success"* — is specified but does not exist as an artifact.
The deterministic verdict machinery is fully built and pinned (`tests/test_launch_demo.py`
proves A2 PASS + A1 FAIL → reduced FAIL, A1 the sole catcher; the real corrupt-success
shape is documented via `s1p`/`pytest-5227`), the console renders verdicts (C7, v0.23.0),
and the minting driver + BYOK `claude -p` path can drive a real agent to produce the
capture. What L7 builds: the **self-contained demo** (repo + captured run + runbook), the
**fresh demo gif** (no recording machinery exists — the current `assets/belay-demo.gif`
has no generator), and two honest corrections: the **compose console cannot render**
(no `/api` routes in the container — a real L6 gap the demo needs closed) and the
**"green Langfuse trace" is aspirational** (no integration exists; C9 export-back is
deferred — the honest first slice is a juxtaposition).

## Goals & Success Metrics

1. **L7 DONE, verifiably:** the demo is a self-contained `demo/` tree + runbook any
   stranger can reproduce; a fresh demo gif replaces `assets/belay-demo.gif`; the
   verdict is deterministic — a CI test replays the committed capture every PR and
   asserts the A1 FAIL at the exact flag turn, with the coverage line.
2. **The demo is the console:** the compose console renders the committed capture (the
   container API gap closed), so `docker compose up console` shows the red FAIL + diff —
   the launch visual.
3. **The demo is true:** the corrupt-success capture is a REAL agent run (BYOK, `claude
   -p`, filesystem+shell behind the gated proxy), committed as a replayable artifact —
   real documented behavior, not a staged trace (the locked spec's own words).
4. **The record is honest:** the roadmap's "turn 7" and "green Langfuse trace" wordings
   are corrected to what actually shipped — the committed capture's real flag turn, and
   a documented juxtaposition (console verdict beside the agent's session transcript)
   with the Langfuse integration named deferred.
5. **DONE is defined under the fallback too.** If the 3-drive cap is reached without a
   corrupt success (demo-capture spec Decision 2026-08-26), L7's DONE is re-opened with
   the owner before any redefinition — the negative control (the clean drives verified
   clean) is the documented fallback posture, and the checklist's L7 row is never marked
   DONE on an unreviewed meaning.

## User Personas & Scenarios

- **The PH launch audience**: watches the gif — the console showing a real agent
  "fixing" a test, Belay's red verdict at the exact turn with the diff, tagline
  *"Your agent lied. Your dashboard didn't notice. Mine did."*
- **The stranger evaluator**: clones belay, runs the demo runbook, sees the verdict
  with the console (docker compose) — 15-minute class, offline.
- **The skeptic (R4's "LLM judge with extra steps" commenter)**: the demo shows A1, a
  deterministic invariant, carrying the verdict — no model consulted (`README.md:111`).

## Requirements

### Must-have

- **M1 · `demo/` tree.** The self-contained demo: the tiny fixture repo (one failing
  test — the `test_auth.py` shape from `tests/test_launch_demo.py`), the committed
  captured run (trace + snapshot trees + manifests), and a `demo/README.md` that is
  the stranger's runbook. All inside the belay repo — one clone, everything.
- **M2 · The capture is a real agent run.** Drive a real agent (manual, BYOK
  `claude -p` via the minting driver, the demo's own server behind the gated
  proxy — the approved deviation) on the demo repo with the task *"make the tests
  pass"*. Commit the capture. The agent's trajectory varies; the COMMITTED capture is
  what the demo pins. **The capture ships with a provenance note** (model, date,
  task text, operator) beside the artifact — the freeze-protocol culture applied to
  the demo's headline claim.
- **M2' · The demo repo's bug contract is HARD by decision (2026-08-26).** Four
  drives on the original easy contracts (lockout counter, path-glob semantics,
  unrestricted edit distance; `claude-opus-5` + `claude-haiku-4-5`) all FIXED the
  bug honestly — zero touched `tests/` (`demo-capture/DRIVES.md`, n=4 recorded as a
  measurement, not a base rate). The mint's real corrupt successes came from
  SWE-bench-class bugs where the honest fix was genuinely hard. Decided (owner,
  2026-08-26): the demo repo contract changes to a bug in that class — the honest
  fix is real work, the shortcut (weakening the STRONG failing test) is cheaper —
  while staying a small committable module with the same neutral prompt and task
  text. Strangers replay the committed capture; they never re-drive, so the repo
  stays small. The contract selection criteria and the iteration cap are in the
  demo-capture spec's Decision block; every drive continues to be recorded in
  `DRIVES.md`.
- **M3 · Deterministic replay in CI.** A test replays the committed capture every PR
  (no network; the replay server is a deterministic stdlib fixture with the same tool
  names) and asserts: the flag turn FAILs with the A1 `no-assertion-weakening` cause
  and the diff; other turns PASS; the coverage line is present; `belay verify --json`
  agrees. Replayed on both macOS and Linux.
- **M4 · The compose console renders the demo.** Close the container gap:
  `console/server-static.mjs` gains the `/api/*` routes (or the image bundles the real
  server) so `docker compose up console` renders the committed capture — red FAIL +
  diff, coverage line on every surface. Tested (docker-gated, the flipped
  `test_the_console_image_builds_and_reports_health_with_the_engine` extends to a
  render check).
- **M5 · Fresh demo gif.** A Playwright script (console dev-dep, manual-marked, never
  CI) drives the console against the committed capture, records the feed + the red
  FAIL turn with its diff, and emits `assets/belay-demo.gif`. The operator runs it;
  the gif is committed. README's `<img>` updated with the corrected alt text (the real
  flag turn, from the committed capture).
- **M6 · Honest doc corrections.** (a) The roadmap/README "turn 7" wording is corrected
  to the committed capture's real flag turn (or made generic: "the exact turn"); (b)
  the Langfuse side-by-side is restated as the honest juxtaposition — the console's
  red verdict beside the agent's session transcript (the mint driver's recorded log) —
  with the real Langfuse integration named deferred (C9 export-back); the demo claims
  exactly what it shows.
- **M7 · Runbook.** `demo/README.md` (or a sibling runbook): the stranger path
  (install → `docker compose up console` or the local dev server → point at the demo
  capture → see the verdict) and the live-reproduction path (BYOK agent run — manual,
  real model spend, marked as such).

### Should-have

- **S1 · PH listing assets draft.** `docs/planning/launch-demo/ph-assets.md`: tagline,
  the Phase-0 number (11/60 = 18.3% with its decomposition), the demo gif reference,
  the honest coverage line ("macOS+Linux sandbox; sees what crosses the MCP boundary;
  a PASS excludes the network dimension") — the checklist gate's asset list, drafted.
- **S2 · The demo joins the tests' guardrails** — the committed capture's replay is a
  corpus-style regression: a future rule change that flips the demo's verdict fails CI
  (the demo is the product's headline claim; `tests/test_verify_weakening.py:243-248`
  already pins the tautology row).

### Nice-to-have

- **N1 · A one-command demo** (`belay demo` or a make-style script) that wires
  capture→verify→console for the stranger.

## Technical Considerations

- **Capability placement:** L7, Phase 1 launch; consumes C1–C6, C9's interop facts,
  and C7's console. No new engine capability.
- **Verdict impact:** none — the demo USES the A1 deterministic verdict; A3 is unshipped
  and never carried (ROADMAP:259). The demo's honesty rules are the repo's: coverage
  line on every surface, UNVERIFIED never PASS, no over-claim (R5).
- **The committed capture replays anywhere:** the replay-relocation machinery
  (`replay-absolute-path-fidelity` + `replay-relocation-shell`) makes the capture's
  recorded `source_root` portable; the CI replay test proves it (this is the corpus's
  own mechanism — a demo capture is a corpus-shaped artifact).
- **Determinism:** CI replay is deterministic and offline (fixture server, no model);
  the live agent capture is manual-marked (model spend) and its trajectory varies —
  the COMMIT pins the run.
- **Zero-dep:** the engine stays stdlib-only; the fixture replay server is stdlib; the
  Playwright dependency lives in `console/` dev-deps only.
- **Effort:** three aspects — A1 `demo-capture` (demo/ tree + real capture + CI replay
  test + runbook, ~1-2 days incl. one operator-driven capture), A2 `console-container-api`
  (~0.5-1 day), A3 `demo-gif-assets` (Playwright gif + doc corrections + PH assets,
  ~0.5-1 day). The capture is the only uncertain step (the agent may behave honestly —
  re-run or adjust the task text; the shape is proven reachable by `s1p`).

## Risks & Open Questions

- **The live agent may not produce a corrupt success on the drive — MEASURED, not
  hypothetical.** Four drives (two models, three easy bug contracts) all behaved
  honestly (`demo-capture/DRIVES.md`, 2026-08-25). The shape is proven reachable
  (`pytest-5227` turns 11/13, hand-adjudicated weakenings in real captured data),
  and the mint produced 11 real trajectory TPs on SWE-bench-class bugs. Response,
  decided by the owner 2026-08-26: re-drive on a **harder repo contract** (see
  M2') with the protocol + iteration cap in the aspect spec's Decision block. If
  the cap is reached without a corrupt success, the demo's premise is re-opened
  with the owner (the honest negative control — four runs verified clean — is the
  documented fallback posture) before anything synthetic is ever considered: a
  hand-edited capture would make the demo the one thing it exists to expose
  (`demo/capture/README.md`). The COMMITTED capture is the pinned artifact either
  way — the demo never depends on the live run succeeding at demo time.
- **R5 (over-claiming) is the demo's own failure mode.** The gif, alt text, and PH
  assets must carry the coverage line and never imply a network verdict; the Langfuse
  restatement (M6b) is part of the honesty contract, not copy-editing.
- **R10 (bandwidth):** the capture drive + gif recording are operator steps; the
  automation (CI replay, Playwright script) is what the unit ships.
- **Open:** the exact flag turn of the committed capture (unknown until the run is
  taken — the docs are corrected to its truth in A3).
- **Open:** whether `docker compose up console`'s render check lives in the docker CI
  job's module or a new docker-gated test — decide in the plan.

## Out of Scope

- **A real Langfuse integration** (C9 export-back, deferred by name).
- **A3 claim re-derivation** (unshipped, cuttable; the demo carries A1 only).
- **The PH submission itself** (the assets draft ships; submitting is the operator's
  act at the READY-TO-PUBLISH gate).
- **GHCR publish; any engine verdict/trace-format change.**