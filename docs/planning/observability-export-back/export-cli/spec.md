# Aspect spec — `export-cli`

**Parent PRD:** `docs/planning/observability-export-back/prd.md` (C9, second aspect)
**One-line boundary:** `belay interop export <otlp> <trace>` — the CLI surface that runs
the export-engine pipeline and writes the OTLP/JSON document to `--out` or stdout, with
fail-closed errors and settled exit semantics.

---

## Problem slice & user outcome

The engine aspect proves the shape; the operator needs the command. One invocation turns
their spans + trace + server into a collector-ready OTLP/JSON document with verdicts
attached — without opening a second tool.

## In-scope requirements (from the PRD must-haves 1, 4; should-have 7; nice-to-have 9)

1. **`belay interop export` subcommand** in the existing `interop` argparse group
   (`cli.py:2886-2936`), mirroring `correlate`'s flags: positional `otlp`, positional
   `trace` (single file; directory rejected with the same clear error as correlate),
   `--server` (`nargs=REMAINDER`), `--manifest-dir`, `--replays`, `--timeout` — plus
   `--out FILE` (default: stdout) and `--json` (machine summary).
2. **Streams settled:** the OTLP/JSON document goes to `--out FILE` or stdout; the human
   (or `--json`) summary always goes to **stderr** — stdout carries exactly one artifact,
   so `belay interop export ... > verified.otlp` is always safe.
3. **Exit semantics:** rc 0 on successful export; rc 1 on operational failure
   (missing/malformed files, unreadable trace, write failure) — fail-closed. Verdict
   contents never gate the exit code (settled at the PRD interview).
4. **Fail-closed errors** mirroring correlate: missing otlp/trace file, malformed OTLP
   (`OtlpParseError` → named error, never empty success), directory trace argument,
   `--server` without manifest dir resolving — each a clean error message + rc 1.
5. **Help text honesty line:** states that uncorrelated/unverified spans export as
   `UNVERIFIED`, never `PASS` (mirrors
   `test_help_states_the_no_server_unverified_behavior`).
6. **`--json` summary** on stderr: the correlation summary (`correlation_summary` from
   `report.py:50`, matched/total with denominator + uncorrelated by cause) plus the
   export path; stdlib-serialized.
7. Heavy imports lazy inside the handler (repo convention).

## Out-of-scope boundaries

- The pure export function — `export-engine` aspect (CLI consumes it).
- Live OTLP exporter/collector; anything Langfuse-specific; multi-trace aggregation.
- Changing `correlate`'s surface or exit semantics.
- Writing any file other than `--out` (no implicit sidecars).

## Acceptance criteria (testable — written first, the repo is test-first)

- **AC1** `belay interop export <otlp> <trace> --out out.json` writes a document that
  parses with `parse_otlp` and carries the verdict attributes (end-to-end, stub-free).
- **AC2** With no `--out`, the document is the **entire** stdout (stdout purity; the
  summary is on stderr).
- **AC3** Exit codes: rc 0 with `--out` written even when every exported verdict is
  `UNVERIFIED` (verdict contents never gate); rc 1 on missing otlp file, missing trace
  file, malformed OTLP, directory trace argument, and unwritable `--out` path — each
  with a named error message.
- **AC4** `--json` summary on stderr carries `correlation` (`matched/total`,
  `uncorrelated` by cause) and the export path, stdlib-serialized (round-trips with
  `json.loads`).
- **AC5** Help text states the UNVERIFIED-never-PASS behavior.
- **AC6** End-to-end with a real replay (seatbelt-gated, mirroring
  `test_ac5_end_to_end_matched_turn_replays_and_attaches_a_real_pass`): a matched span
  exports its real replayed `PASS` verdict + coverage line.
- **AC7** Deterministic, no network — all fixtures, CI-runnable.

## Dependencies & sequencing

- Depends on the `export-engine` aspect (the pure function) and slice 1's `correlate`
  machinery.
- Natural internal order: (a) the subcommand + handler with the summary/stderr + `--out`
  plumbing → (b) fail-closed error tests → (c) help text + `--json` summary → (d) the
  seatbelt-gated end-to-end test.

## Open questions / risks specific to this aspect

- **Summary content.** Human summary mirrors `report.render`'s style but must not print
  the document to stdout; keep it minimal (correlation rate + per-cause counts + the
  export path). The `--json` shape is `{"export": "<path|->", "correlation": {...}}`.
- **`--json` + stdout document.** With `--json` and no `--out`, the machine summary is
  on stderr and the document on stdout — asserted by AC2/AC4 so the two streams never
  collide.