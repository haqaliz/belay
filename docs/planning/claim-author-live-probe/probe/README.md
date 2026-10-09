# Probe — the claim-author live probe (Phase A artifacts)

This directory holds the frozen, no-result artifacts of the `probe` aspect
(spec.md + plan_20261010.md in this folder, PRD at `../prd.md`): a recording
wrapper, a one-shot run script, a manual-marked probe test, and this README.

**What it measures.** Re-verify the two banked run-3 trajectory cases
(`django-11422`, `django-14382`, at
`~/dev/at/holder/belay/mint/cm6/batch/`) through the real CLI with the shipped
reference claim author (`python -m belay.verify.reference_claim_author --model
<full-id>`), and record the author's observed disposition — whatever it is.
Run 3's ledger could not say why those two abstained (`NO_CHECK_AUTHOR` without
a reason); the candidate cause (the engine's 60 s author bound vs the reference
author's own 600 s bound) is a hypothesis this probe answers by observation.

**The honesty rules.** This is NOT a gate run and produces NO Phase-0 number.
The traces are referenced by absolute path and never copied. The output is
committed verbatim next, whatever it says — no editing, no re-run without a
declared owner decision (Rule D, `phase0-mint-run/prd.md:97-101`).

## Files

| file | role |
|---|---|
| `claim_author_wrapper.sh` | `--claim-author` target: appends one byte to `probe-marker` per invocation, logs `date +%s` start/stop to `probe-wall`, then runs the shipped module as a child and propagates its exit code. "The author ran" is an observed fact, never an inference from an absent JSON key. |
| `run-probe.sh` | the frozen invocation: two `uv run belay verify --json` runs, one per trace, stdout to `run-trace-<id>.out` / stderr to `.err` verbatim. CONTAINS NO RESULT. |
| `tests/test_claim_author_live_probe.py` | manual-marked probe test, owner-run, never CI. One trace per invocation (`BELAY_PROBE_TRACE`); asserts the axis engaged (marker grew) and the document carries one of the three allowed record shapes. |
| `probe-marker`, `probe-wall`, `run-trace-*.out/.err` | produced BY the run; committed in the commit AFTER the freeze. |

## Owner run (one-shot freeze protocol)

1. Commit this directory (Phase A) — the run script must be committed BEFORE it
   runs, containing no result (grep-checked).
2. From the worktree root, run it once:

   ```sh
   uv run bash docs/planning/claim-author-live-probe/probe/run-probe.sh
   ```

   The pinned model is `claude-opus-5` — a probe parameter, override with
   `BELAY_REFERENCE_AUTHOR_MODEL=<full-id>` if the probe day needs a different
   full id (ask before choosing one; aliases are rejected by the module).
3. Commit the artifacts verbatim next: `run-trace-11422.out/.err`,
   `run-trace-14382.out/.err`, `probe-marker`, `probe-wall` — whatever they
   say. Name the freeze commit hash in the findings.
4. Do NOT run it a second time unless you declare one (Rule D).

After the run, the findings note (`FINDINGS.md`, Phase C) answers R-D: the
observed sub-cause quoted verbatim, any A3 verdict or D3 silence, author
wall-times vs the 60 s bound (from `probe-wall`), and the one-line reading on
whether the bound needs a knob.

## The assertion layer (optional second lens)

```sh
BELAY_PROBE_TRACE=~/dev/at/holder/belay/mint/cm6/batch/trace-django__django-11422.jsonl \
BELAY_REFERENCE_AUTHOR_MODEL=claude-opus-5 \
  uv run pytest tests/test_claim_author_live_probe.py -m manual -q -s
```

Same argv as the run script, one trace per invocation. It fails with re-run
instructions (never a skip) when the model or trace env is missing, and asserts
the two load-bearing facts: `invocations >= 1` and a document record of one of
the three allowed shapes.

## The three operator-error hazards (each read like an engine fault)

From `../a3-author/live-run.md:91-105` (the n=1 live proof's three zero-cost
attempts) — the run script encodes their fixes, but know them by name:

1. **`--manifest-dir` is required** (no default on this surface). Omitting it
   is `exit 2` with EMPTY stdout — argparse, before the engine runs. It must be
   the trace's **stem** + `.manifests` (the `.jsonl` suffix is not part of the
   directory name; `trace-django__django-11422.jsonl` ->
   `trace-django__django-11422.manifests`).
2. **The `'{workspace}'` argv token is mandatory** after the server command.
   The replay substitutes the scratch root it restored into; omit it and every
   turn degrades to a named "replay did not answer target" abstention — honest,
   but reads as an engine fault.
3. **The record is read from the document's top-level `claim` key** — not
   `claim_record`. Reading the wrong key made an earlier probe report an empty
   column against a payload that carried a perfectly good record. (The sibling
   D3-silence record is the top-level `claim_silence` key.)

Also: `--json` must sit BEFORE `--server` — `--server` is `nargs=REMAINDER`
and swallows everything after it; a trailing `--json` would land inside the
server argv and stdout would be the human report, not the JSON document.

## Precedents

- `../../phase0-corpus-mint/a3-author/live-run.md` — the n=1 live proof, the
  hazards table, the wrapper-record trick.
- `../../phase0-corpus-mint/mint-run/acceptance-cm-run3-stage2.sh` — the frozen
  run-3 script: freeze header, `BELAY_CLAIM_AUTHOR` wiring, the filesystem
  server absolute path, `--server` remainder ordering.
- `../../phase0-corpus-mint/mint-run/ledgers/cm-run3-stage2.json` — the run-3
  factuals this probe's outputs are compared against.
- `tests/test_reference_claim_author_live.py` — the wrapper-record trick in a
  test, the manual-marked / `pytest.fail`-when-model-unset shape.
- `tests/test_claim_axis_e2e.py` — the subprocess-driven `belay verify --json`
  pattern, env handling, wall-bounded waits, the `claim` / `claim_silence`
  record shapes.
- `src/belay/verify/reference_claim_author.py` — the shipped module the wrapper
  runs; full model ids only (aliases refused).