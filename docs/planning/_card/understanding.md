# Corpus Shell-Axis Recompute Routing — understanding

## What the work really is

`belay corpus run --shell-server <cmd>` — thread the second replay boundary into the
trajectory-case recompute path of the corpus. The engine seam is **already built and
pinned**: `run_corpus` / `run_case` / `_recompute_trajectory_case` accept
`shell_server_command` (`src/belay/corpus/run.py:701-784, 787-814`), and four tests in
`tests/test_corpus_trajectory_run.py` already prove per-turn routing inside the whole-trace
recompute, the byte-identical `None` default, the per-turn asymmetry, and the `run_corpus`
threading. **Only the CLI flag and its parity-table row are missing.**

## Affected areas (file:line)

- `src/belay/cli.py:3330-3372` — `corpus run` parser has only `corpus_dir` + `--no-claim-axis`;
  `_cmd_corpus_run` (1998-2097) calls `run_corpus(corpus_dir, disable_claim_axis=...)` with no
  shell command.
- `tests/test_cli_flag_parity.py` — `--shell-server` row (85) is `{verify, phase0 run, gate
  baseline, gate check}`; `corpus run` is not mentioned in its comment and is absent from
  the set. `--server` row (62) excludes `corpus run` because "each stored case carries its
  own resolved server command" — true for the fs boundary, false for the shell boundary (a
  case never stores the shell command). Both guard tests (167-175, 178-192) force the row
  edit the moment the flag lands.
- `src/belay/verify/turn.py:363-368` — a `run_process` turn replays against
  `shell_server_command` only when given; with `None` it replays against `server_command`.
  This is the silent mis-route the unit fixes.
- `src/belay/phase0/runner.py:536-538` — a trajectory case stores the **final turn's**
  resolved command; the whole-trace recompute therefore needs the second boundary
  caller-supplied (run.py:511-522).
- `src/belay/corpus/run.py:398-433` — `_classify_trajectory_case`: equal → MATCH / MISS_CLOSED;
  **everything else, including any UNVERIFIED recompute, → REGRESSION**. There is no SKIP
  vocabulary on the trajectory path.

## The defect being fixed (honest statement)

A two-server mint (`phase0 run --shell-server`) banks trajectory corrupt-success cases
whose stored command was resolved from the final turn. If that final turn was a
filesystem turn (the common Shape-A shape), the stored command is the fs command and
`corpus run` recomputes the trace's `run_process` turns against the fs server. The reply
is a JSON-RPC error, and the trajectory evidence seam can read that in **either**
direction (S1): as no-exit-0 evidence → recompute FAIL matches the stored FAIL (**false
agreement**, the regression suite certifying the wrong reason), or as unverifiable →
recompute UNVERIFIED → **false REGRESSION**. Both directions are corrupt. No real
two-server trajectory cases exist (the mint's 11 TPs were never bankable — no-backfill),
so the fix is forward-looking and changes only constructed fixtures, never real data.

## Design decisions to surface at the review gate

- **D1 — the flag:** `--shell-server CMD`, single string, shlex-split at use, fail-closed on
  un-lexable — the exact `phase0 run` shape (cli.py:3598-3610). No REMAINDER ordering hazard
  on this parser.
- **D2 — the honest no-flag behavior:** today a two-server trajectory case recomputes
  silently wrong. Options: keep byte-identical (the existing pin
  `test_trajectory_recompute_without_a_shell_command_is_byte_for_byte_today`) vs introduce a
  named-cause SKIP when the trace needs a boundary the operator didn't supply (the
  `CLAIM_AXIS_DISABLED` operator-omission precedent, not the `_SKIP_CAUSES` substrate
  class). Recommendation: named-cause SKIP — fail-closed, no real data affected.
- **D3 — the final-turn-is-`run_process` edge (S5):** the stored command IS the shell
  command then, and the fs turns have no expressible boundary (the flag can only supply the
  shell side). Faithful recompute is impossible for that shape → decide: always SKIP, or
  document as an accepted residual.
- **D4 — `corpus add --shell-server`:** `corpus add` today banks a `run_process` turn with
  the fs command (wrong); `phase0 run --shell-server` banks correctly. Include the flag in
  this unit (same parity row) or declare out? Recommendation: include — same one-line wiring,
  closes the manual-add path.
- **D5 — `corpus show`:** its trajectory recompute (cli.py:2385, 2417) shares the gap but is
  outside the parity guard (the guard's "corpus show replays nothing" comment is stale).
  Include the flag and correct the comment, or declare out by name.

## Scoping corrections from the dig

- **Claim half (S2):** `_recompute_claim_case` does not thread `shell_server_command`, but is
  self-consistent — the claim evaluator replays only the LAST turn and the stored command is
  that turn's resolved command. The brief's "trajectory/claim-case recompute" reduces to
  **trajectory only**. State in the PRD.
- **`interop correlate`/`export`** stay single-boundary (S9) — the documented default.

## Guardrails

Harness machinery only (corpus). No agent framework, no LLM judge. UNVERIFIED-never-PASS
holds. No verdict axis, schema, or published number moves — `11/60 = 18.3%`, `precision
0.00`, `1/15`, `4/16` stand unedited. The corpus is moat #2: this unit makes its highest-
value case class recompute faithfully.