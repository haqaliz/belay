# Aspect: verify-json (A1)

Part of `docs/planning/live-console/prd.md` (launch checklist L6 / C7). The engine seam
the console depends on: structured verdict output.

## Problem slice

`belay verify` emits human text only; the only `--json` in the CLI is
`interop correlate` (`cli.py:2587-2591`). A console cannot parse human text (fragile,
against the repo's machine-checked culture), and must never compute verdicts itself.
The seam: `belay verify --json` emitting exactly what the human report says, from the
**same objects** — one computation, two renderers.

## In-scope requirements (PRD M1)

- `--json` flag on `belay verify` (and it must work with `--turn N` and `--replays`).
- The JSON document carries: per-turn records (ordinal, tool, reduced status, every
  sub-verdict with axis/kind/status/message — including NOT_COVERED and UNVERIFIED with
  its named cause), the aggregate, the **coverage line block** (always present — the
  honesty contract applies to the machine surface), exposure facts, and the trajectory
  disposition.
- **One computation, two renderers:** the text report and the JSON are rendered from the
  same structured objects; a divergence fails a test. Existing text output stays
  byte-identical (the suite pins it).
- **Always-valid JSON:** on internal failure the command emits no half-written document
  and exits non-zero (decided: an explicit `{"error": {"cause": ...}}` record, or
  nothing + non-zero — pinned by test).
- **Exit codes unchanged** (FAIL/UNVERIFIED → non-zero).
- Stdlib-only; zero-dep preserved.
- The JSON shape is a **machine contract**: pinned by a committed fixture snapshot from
  the first RED test.

## Out of scope

- `belay replay --json` (PRD N1 — the console's replay path uses `verify --turn N
  --json`).
- Any verdict-logic, reduction-rule, or trace-format change.

## Acceptance criteria (test-first)

1. `belay verify --json` on a fixture trace yields the pinned JSON snapshot (the RED
   test); the snapshot's per-turn statuses, sub-verdicts, coverage block and causes
   match the human report's content.
2. A `--json` run whose human report shows PASS on every turn carries the coverage line
   in the JSON (the "PASS without its coverage line" shape fails this test).
3. NOT_COVERED sub-verdicts appear in the JSON as NOT_COVERED with their message —
   never as PASS, never dropped.
4. UNVERIFIED turns appear with their named cause in the JSON.
5. A forced internal failure emits valid JSON (or nothing) and a non-zero exit — never a
   truncated document with exit 0.
6. Exit codes identical with and without `--json`.
7. The existing text-output tests pass unchanged (byte-identical text).

## Dependencies & sequencing

- First aspect: it pins the shape the console consumes. A2's server tests can start
  against the pinned fixture once A1 GREEN lands.

## Open questions / risks

- The exact key names of the contract — decided in the spec's fixture and locked by the
  snapshot test; changes are deliberate contract changes (documented + snapshot
  re-pinned).