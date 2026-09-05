# Aspect spec — `export-docs`

**Parent PRD:** `docs/planning/observability-export-back/prd.md` (C9, second aspect)
**One-line boundary:** retire the deferral lines the shipped slice actually retires, and
only those; leave every honesty line that the slice does not achieve exactly where it is.

---

## Problem slice & user outcome

Every surface that names the export-back deferral must say the slice shipped — and the
"no Langfuse integration" lines must survive, because an OTLP/JSON fixture-collector
export is not a Langfuse integration. A reader of any doc must be able to tell what the
slice did and did not achieve without reading the PR.

## In-scope requirements (from the PRD should-have 8; Risks/Open Questions)

1. **`docs/technical/CAPABILITY_ROADMAP.md`** — the C9 "as built" deferral line
   (`:859-861`): "exporting verdicts back into a collector" → shipped slice (fixture-
   collector round-trip; live collector export still deferred); **drop the stale
   `NOT_COVERED` reclassification item** (shipped via `interop-merge-repair`,
   `STATUS.md:660-673` — a correction, not a reclassification); keep multi-trace-directory
   aggregation deferred. Sequencing-table row `:900` (🟡 → ✅ second slice, export-back
   shipped at data-format level).
2. **`docs/ROADMAP.md`** — `:272` (deliverable row: "first slice built: ingest+correlate+
   attach, export-back deferred" → "...ingest+correlate+attach+export-back (fixture-
   collector round-trip)") and `:263` (the demo honesty line: the "exporting verdicts
   back into a collector is a named deferral" half updates to "verdict export ships as
   OTLP/JSON into a fixture collector; a live collector or Langfuse integration is not
   built"; the "Do not stage a Langfuse screenshot" prohibition survives verbatim).
3. **`docs/planning/observability-interop/prd.md` + `ingest-correlate-attach/spec.md`** —
   the deferral lines (`prd.md:38`, `:184-186`, `:192-196`; `spec.md:5`, `:51-52`) gain a
   pointer to the shipped second aspect; the C9 planning dir's "No export-back" boundary
   becomes "no live-collector export".
4. **`docs/STATUS.md`** — append an entry per repo convention (current cut, what shipped,
   what it does NOT do, honesty notes, suite count before/after).
5. **`CHANGELOG.md`** — entry per repo convention (the v0.5.0 interop entry's "exporting
   verdicts back into a collector ... are named follow-ups" line now points at the
   shipped slice; new release entry at the top).
6. **`README.md`** — grep for "export-back"/deferral mentions; update only lines the
   slice achieves.
7. **`CLAUDE.md`** — grep for the interop/export-back status lines; update only what the
   slice achieves (the standing "Langfuse export-back" non-goal lines stay — the
   integration is still not built; only the "exporting verdicts back into a collector is
   a named deferral" halves retire).

## Out-of-scope boundaries

- **`docs/planning/launch-demo/ph-assets.md` and the launch-demo PRD lines** — launch
  claims are owner territory (three questions left open for the owner there,
  `CHECKLIST.md:330-334`); this unit does not rewrite them. If the owner later wants the
  "export-back is deferred" claim refreshed, it is a launch-asset change, not this unit's.
- **The L7 checklist box** — owner-ticked by pre-registration; untouched.
- Any re-derivation or restatement of published numbers (`11/60`, `precision 0.00`,
  `1/15`, `4/16` — all stand unedited).
- The launch checklist's "READY TO PUBLISH" gate — export-back is not a publish
  condition; no checklist box moves except none.

## Acceptance criteria (testable — written first, the repo is test-first)

- **AC1** A grep for `export-back` across `docs/`, `README.md`, `CHANGELOG.md` yields no
  line that still calls the whole capability deferred: every surviving "deferred" claim
  names exactly what remains deferred (live collector export, Langfuse integration,
  multi-trace aggregation).
- **AC2** The "no Langfuse integration" / "never stage a Langfuse screenshot" lines
  survive verbatim wherever they exist (`ROADMAP.md:263`, `CHECKLIST.md:266`,
  `launch-demo/prd.md`, `ph-assets.md` untouched).
- **AC3** `CAPABILITY_ROADMAP.md` no longer lists the `NOT_COVERED` reclassification as
  deferred.
- **AC4** `STATUS.md` entry follows the repo's honesty format: what shipped, what it
  does NOT do, no published number re-derived, suite count.
- **AC5** Full suite green after the docs changes (no doc-consistency test exists for
  these lines; the suite is the guard).

## Dependencies & sequencing

- Last aspect: describes the shipped artifact, so it runs after `export-engine` +
  `export-cli` are merged into the branch.
- Sequence within the aspect: code surfaces (CAPABILITY_ROADMAP, ROADMAP) → planning
  dirs → repo record (STATUS, CHANGELOG, README, CLAUDE.md).

## Open questions / risks specific to this aspect

- **Scope discipline is the whole risk.** The honest direction is under-updating: when a
  line is ambiguous ("export-back deferred" could mean the whole capability), the
  replacement must name exactly what shipped. The PRD's caveat governs: "update only
  what the shipped slice actually achieves."
- **`CLAUDE.md` is a strategic doc** — its status block is rewritten on the repo's
  release cadence; keep the edit minimal and factual, in the established voice.