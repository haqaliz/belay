# Issue #54 — feat: live OTLP exporter for interop verdicts

## Why
C9 ships ingest+correlate+attach and export-back into an OTLP/JSON document with a fixture collector. A live collector (Langfuse/Phoenix) exporter was deferred by name at `observability-export-back` (2026-09-05).

## Scope
- Export enriched OTLP to a configured endpoint.
- Coverage line and UNVERIFIED-never-PASS in-band.
- No raw state egress; BYOK/self-hosted posture unchanged.

## Exit criteria
- Round-trip against a live local collector, not a fixture.
- Failure to export never changes a verdict or exit code.

## Status
Deferred by name; not launch-blocking.
