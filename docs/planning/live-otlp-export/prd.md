# PRD — live OTLP/JSON exporter

**Issue:** #54 · **Slug:** `live-otlp-export` · **Branch:** `feat/54/aliz`

## Problem

`belay interop export` enriches an OTLP document and writes a **fixture**: a file or stdout.
A team that runs Langfuse/Phoenix must then hand-carry the file into the collector. The live
transport was deferred by name at `observability-export-back` (2026-09-05).

## What ships

`belay interop export <otlp> <trace> --otlp-endpoint URL [--otlp-header NAME=VALUE ...]`

- Builds the **same** enriched document (`build_enriched_document` unchanged), serializes it
  with the same `dumps`, and POSTs it as `application/json` (OTLP/JSON over HTTP) using
  stdlib `urllib.request` only.
- `--otlp-endpoint` and `--out` are mutually exclusive: both given → exit 2 named.
- 2xx → exit 0. Connection failure, timeout, non-2xx or unreadable URL → exit 1, naming the
  endpoint and the cause. The document is never retried and never partially written.
- `--otlp-header` is repeatable (`Name: Value` or `Name=Value`); malformed → exit 2.
  Documented truthfully: **headers are visible in process arguments** — do not pass secrets
  on a shared host (a BYOK/self-hosted posture unchanged; nothing is read from the
  environment).
- Summary stays on **stderr** exactly as today; the `export` field of the JSON summary is the
  endpoint URL instead of a path.
- Verdicts are untouched: the exported statuses, causes, sub-verdicts and coverage line are
  byte-identical to the `--out` document.

## Non-goals

- No protobuf/gRPC OTLP transport (JSON over HTTP only), no batching/queueing, no retries.
- No auth discovery, no secret storage, no env-var headers.
- No Langfuse-specific adapter, and **no implication of a Langfuse integration** — the
  prohibition on staged screenshots stands.
- No change to correlation, replay, verdicts, or the fixture round-trip.
- No multi-trace aggregation (`interop correlate`'s separate deferral).

## Acceptance criteria

1. A local HTTP collector receives exactly `dumps(document)` — byte-identical to the
   `--out` file for the same inputs — with `Content-Type: application/json`.
2. 200 → exit 0; summary on stderr; stdout carries nothing.
3. 500 → exit 1, message names the endpoint and the status; no document on stdout.
4. Connection refused / bad URL → exit 1, named; never a verdict change.
5. `--otlp-endpoint` + `--out` → exit 2 named.
6. A malformed `--otlp-header` → exit 2 named.
7. Headers arrive at the collector exactly as given.
8. An uncovered span's coverage attribute still exports (`[]` present), provable from the
   posted body.
9. Docs: README, STATUS, CHANGELOG, ROADMAP and the module docstring stop claiming "no
   network"; the Langfuse/screenshot prohibition survives verbatim.

## Risks

- **R-a:** egress is now real. Accepted: opt-in, operator-chosen endpoint, no env secrets,
  and the document holds verdict metadata, not raw trace/state.
- **R-b:** a header value leaks via `/proc`. Documented; no env fallback added.
- **R-c:** a collector rejects the payload shape. The body is the same document the fixture
  round-trip already proves; a non-2xx is a named failure, never a silent success.

## Open questions

- 🟡 **Q1:** include `--otlp-header` at all, or defer auth? Included — without it the
  exporter cannot reach a hosted collector, which is the point of the slice.
