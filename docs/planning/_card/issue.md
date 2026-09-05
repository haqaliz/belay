# Issue / Brief — observability-export-back

> Source: inline brief (belay-next handoff, 2026-09-05), the belay-next pick.
> Branch: `feat/observability-export-back/aliz` · Worktree: `.claude/worktrees/feat-observability-export-back`
> Type: feat · No GitHub issue (slug id).

## Brief

Ship C9's second aspect: export Belay verdicts back into an OpenTelemetry collector as span attributes/events, completing the locked Phase-1 interop deliverable whose export-back half is a named deferral (docs/technical/CAPABILITY_ROADMAP.md:859-861; docs/ROADMAP.md:272,263). Acceptance tests first, per C9's spec: (1) exported verdicts round-trip into a fixture collector with axis and status intact; (2) the export carries the coverage line — which spans were verified and which are UNVERIFIED/NOT_COVERED with named causes, and a non-replayable ingested span exports UNVERIFIED, never PASS (R5 — the interop path is where over-claiming is easiest); (3) deterministic, no network, fixture collector only. Caveat: scoping to OTLP-into-fixture-collector does NOT by itself retire the demo's "no Langfuse integration" honesty lines — re-read them in the same PR and update only what the shipped slice actually achieves; keep multi-trace-directory aggregation out of this slice. The slice's eval data is the correlation rate (R6 measurement) that slice 1 already produces; the launch-checklist ordering rule is reconciled — L7's box is owner-ticked by pre-registration, and this is the first open item an implementer can ship.

## Source-of-truth references

- `docs/technical/CAPABILITY_ROADMAP.md:819-862` — C9 spec (what we build, acceptance, eval data, dependencies, "as built" + the named deferral of the second aspect).
- `docs/technical/CAPABILITY_ROADMAP.md:63-68` — the MCP 2026-07-28 revision makes trace context protocol-native: "C9 got easier AND more urgent".
- `docs/ROADMAP.md:272` — Phase-1 Key Deliverable: "Interop | Ingest OTel/OpenLLMetry spans; sit beside Langfuse/Phoenix (C9 — first slice built: ingest+correlate+attach, export-back deferred)".
- `docs/ROADMAP.md:263` — launch demo honesty line: "A real Langfuse integration is NOT built: C9's first slice ingests and correlates OTLP spans; exporting verdicts back into a collector is a named deferral. Do not stage a Langfuse screenshot to imply an integration that does not exist."
- `docs/ROADMAP.md:373` — R9 risk register entry (incumbents add replay; interop makes us complementary, not a target).
- `docs/ROADMAP.md:371` — R5 risk register entry (replay verifies fidelity, not correctness — interop is where over-claiming would be easiest; UNVERIFIED-never-PASS).
- `docs/planning/observability-interop/` — the C9 planning dir (prd.md, understanding.md, ingest-correlate-attach spec + plan).
- `docs/planning/launch-readiness/CHECKLIST.md` — L7 row (demo) and the publish gate; export-back is the first open item an implementer can ship (L7's box is owner-ticked by pre-registration).
- `docs/STATUS.md` — v0.5.0-era C9 entry and the standing "Langfuse export-back" non-goal lines (STATUS.md:43, 72).