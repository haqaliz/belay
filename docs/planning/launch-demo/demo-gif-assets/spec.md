# Aspect: demo-gif-assets (A3)

Part of `docs/planning/launch-demo/prd.md` (launch checklist L7). The launch visual and
the honest record: fresh gif, corrected docs, PH assets draft.

## Problem slice

`assets/belay-demo.gif` (43.8K) has no generator and its README alt text says "Turn
1's write" while the roadmap says "turn 7" — neither matches the committed capture's
truth. No recording machinery exists. The launch visual is the console; the gif must
show the console rendering the demo capture with the red FAIL + diff.

## In-scope requirements (PRD M5, M6, S1)

- A Playwright-driven gif generator (`console/scripts/record-demo-gif.mjs`,
  `npm run record:demo`, **manual-marked** — never CI): drives the console (local
  server) against the committed demo capture (A1), scripted steps with fixed waits —
  the capture is a static artifact so the sequence is deterministic (feed appears →
  FAIL turn expands → diff visible → a beat), screenshots → gif via a pure-JS encoder
  (gifenc; no ffmpeg dependency) → `assets/belay-demo.gif`.
- README `<img>` updated: the alt text states the REAL flag turn and the truth of the
  committed capture (A1-only verdict, coverage line, never a network claim).
- **Honest doc corrections (M6):** (a) the roadmap's "turn 7" wording corrected to the
  committed capture's real flag turn or made generic ("the exact turn") everywhere it
  appears (README:22-26, ROADMAP.md:255, CAPABILITY_ROADMAP.md:715 if it appears
  there, docs/planning/live-console/prd.md:12 if it appears there); (b) the "green
  Langfuse trace" line restated as the honest juxtaposition — the console's red
  verdict beside the agent's session transcript — with the real Langfuse integration
  named deferred (C9 export-back).
- `docs/planning/launch-demo/ph-assets.md` (S1): tagline, the number (11/60 = 18.3%
  with its decomposition), the demo gif reference, the honest coverage line.

## Out of scope

- A real Langfuse integration; A3; the PH submission itself.

## Acceptance criteria

1. `npm run record:demo` (manual) produces `assets/belay-demo.gif` from the committed
   capture via the console; the operator runs it once and commits the result.
2. The gif's README alt text matches the committed capture's real flag turn and
   carries the coverage-line honesty (no network claim).
3. Grep: no "turn 7" remains in README/ROADMAP/CAPABILITY_ROADMAP/live-console docs
   (or it is made explicitly generic); the Langfuse line is the restated
   juxtaposition with the deferral named.
4. `ph-assets.md` exists with the five PH-listing elements.
5. No CI change: the generator is manual-marked; the gif is committed, not generated.

## Dependencies & sequencing

- After A1 (the capture's real flag turn) and A2 (the console server the script
  drives). The script itself can be written against the local dev server before A2
  merges; the recording run happens after.

## Open questions / risks

- Playwright needs a browser download (dev-dep install, operator machine) — manual
  by design; the script must degrade with a clear error if no browser is installed.
- The gif's duration/size must stay launch-appropriate (a few seconds, small) — the
  script's fixed waits keep it deterministic.