# Card: feat/phase0-live-mint

**Type:** feat · **Slug:** phase0-live-mint · **Owner:** aliz
**Branch:** feat/phase0-live-mint/aliz

No GitHub issue (`gh issue list` → "No Issues"; the tracker is empty). Task source is the
inline brief below, produced by `/belay-next` on 2026-07-21.

## Source of truth (already in repo)

- `docs/ROADMAP.md` — Phase 0 plan (weeks 3–4: "≥50 agent runs through the harness on
  SWE-bench-lite"), the Phase 0 success metrics, and the 🚦 Phase 0 → Phase 1 gate.
- `docs/ROADMAP.md` risk register — **R1** (the premise is wrong; Low probability, **Fatal**
  impact), **R6** (false zero), **R7** (nondeterminism → UNVERIFIED default).
- `docs/technical/PHASE0_RESULTS.md` — the results template; every number is **TO-BE-FILLED**.
- `docs/planning/phase0-corpus-run/RUNBOOK.md` — the reproduce-the-number procedure.
- `eval/README.md`, `eval/instances.md` — the minting driver's usage and the **single** curated
  instance (`pallets__flask-4045`).
- `src/belay/phase0/` + `belay phase0 run/report` — the already-built consumer of the traces.

## Brief

Run the live Phase-0 mint and fill `docs/technical/PHASE0_RESULTS.md` with the real number.
Everything upstream is built: the minting driver (`eval/minting_driver/`, v0.3.0) drives an
LLM's file/shell actions through `python -m belay.proxy`, and `belay phase0 run/report`
already computes the per-instance violation rate with its denominator plus per-turn FAIL,
UNVERIFIED-by-cause, and false-positive rates.

The missing pieces are:

1. **A batch mint harness** over many SWE-bench-lite instances — instance pool selection,
   per-instance workspace prep at base commit, sequential drive, capture-dir layout, and
   resume-after-failure. `eval/instances.md` curates only **one** instance today.
2. **The hand-audit** of every flagged turn, feeding the corpus with human labels.

## Caveat to dig into FIRST (before spending inference budget)

The macOS-runnable, Docker-free, single-file-edit constraint that produced
`pallets__flask-4045` may not yield 50 instances. Verify the achievable pool size against the
real dataset **before** scaling. An under-filled denominator makes `belay phase0 report` emit
`INSTRUMENT SUSPECT` (the R6 false-zero defense) — which is a failed measurement, not a
cleared gate.

## Acceptance (test-first, per repo convention)

1. Deterministic test: the batch harness selects/preps/drives N instances **sequentially**,
   and is **resumable** after a mid-run failure, with never >1 `tools/call` in flight
   (R7 by construction).
2. Deterministic test: a short-denominator run reports `INSTRUMENT SUSPECT` rather than 0%.
3. The live mint itself stays `manual`-marked and out of CI.
4. The gate needs **≥3 hand-audited true positives** and a **stated false-positive rate**
   (`docs/ROADMAP.md` Phase 0 Success Metrics). PROCEED or PIVOT gets written down honestly
   either way.

## Guardrails this work must not violate

- The driver/harness is **eval-only** — not `src/belay/`, not the `belay` CLI, not a product
  surface. Growing it into planning/memory/multi-step autonomy is agent-framework drift.
- BYOK; no vendor default key, no raw-state egress.
- `UNVERIFIED` is never rendered as `PASS`; a suspect instrument is never a clean 0%.
