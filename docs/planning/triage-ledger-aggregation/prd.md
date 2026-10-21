# PRD — triage ledger over many verify documents

**Issue:** #52 · **Slug:** `triage-ledger-aggregation` · **Branch:** `feat/52/aliz`

## Problem

`belay triage-ledger <verify.json>` measures **one** stored `verify --json` document per
invocation (deferred by name at `calibration-ledger`, 2026-09-22). A run set — several
mints, several agents — cannot be measured as one calibration column without hand-merging.

## What ships

`belay triage-ledger <verify.json> [<verify.json> ...]` — one or more positional documents.

- Rows are concatenated in **argument order**; the four counts are summed. The invariant
  `turns_total == decided + unverified + skipped + unscored` holds by construction.
- **Single document is byte-identical** to today: same text, same JSON, same key set, same
  `trace` header. The two byte snapshots must pass unmodified.
- With N > 1 the header/`trace` field becomes `"N documents"` — no paths, no raw data. The
  JSON key set is unchanged.
- **Fail closed, never partial:** any unreadable, malformed, triage-less or corrupt document
  refuses the whole invocation with exit 2 and names the offending path.
- **Duplicate paths are refused by name** (exit 2): silently double-counting the same
  document would inflate the denominator.
- Zero decided rows across all documents keeps the existing named refusal
  (`NO_DECIDED_ROWS`, no rates, exit 0) over the summed counts.
- `ordinal` stays document-local; the only order-sensitive consumer is `top_n_sweep`'s
  tie-break, which is sequence order — now argument order, documented.

## Non-goals

- No directory input: `belay triage-ledger runs/*.json` is the shell's job, and the shell's
  order is the documented order.
- No new flags, no `--out`, no schema bump, no new JSON keys, no per-turn status rendering.
- No budget auto-tuning (issue #53), no replay, no re-verification — still a pure re-render.
- No raw path stored in output; no raw data egress.

## Acceptance criteria

1. Two distinct documents → summed `turns_total`/`turns_decided`/exclusions, rows in argument
   order, violation rate and ECE computed over the merged rows.
2. Single document: the existing `_EXPECTED_TEXT` and `_expected_json_document` byte
   snapshots pass **unmodified**.
3. Duplicate resolved path → exit 2, message names the path and `duplicate`.
4. One malformed document among several → exit 2, message names that path; nothing rendered.
5. All-UNVERIFIED across several documents → `NO_DECIDED_ROWS` refusal, exit 0, summed counts.
6. A top-level JSON value that is not an object → exit 2 with a named error (today it
   tracebacks with `AttributeError`), single and multi.
7. Determinism: the same argv renders byte-identically twice.
8. Docs (README, `CLAUDE.md`, capability roadmap, STATUS, CHANGELOG) stop saying "one
   document per invocation" and name the argument-order contract.

## Risks

- **R-a:** a caller passing the same file twice inflates the denominator — refused (AC-3).
- **R-b:** aggregation changes the meaning of `ordinal` — documented as document-local; only
  the top-N tie-break is order-sensitive, and argument order is explicit.
- **R-c:** a corrupt document silently contributes zero rows — refused whole (AC-4).

## Open questions

- 🟡 **Q1:** header for N > 1 — proposed `"N documents"` (no paths). Alternative: first
  document's trace plus a count; rejected as misleading.
