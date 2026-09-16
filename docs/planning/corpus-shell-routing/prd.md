# PRD — corpus-shell-routing

**Unit:** `feat/corpus-shell-routing/aliz` (bbf, 2026-09-16) · **Source:**
`docs/planning/_card/issue.md` (belay-next handoff), `docs/planning/_card/understanding.md`.

## Problem Statement

The corpus cannot re-verify its highest-value case class on the axis that earned the
Phase-0 number. A two-server mint (`phase0 run --shell-server`) banks trajectory
corrupt-success cases whose stored command was resolved from the instance's **final** turn
(`src/belay/phase0/runner.py:536-538`). When that final turn is a filesystem turn — the
common Shape-A shape — the stored command is the fs command, and `belay corpus run`
recomputes the trace's `run_process` turns against it. `verify_turn` routes a
`run_process` turn to the shell command **only when `shell_server_command` is given**
(`src/belay/verify/turn.py:363-368`); with `None` it silently replays against
`server_command`. The trajectory evidence seam can then read the errored reply in
**either** direction: as no-exit-0 evidence → recompute FAIL matches the stored FAIL
(**false agreement** — the regression suite certifying the wrong reason), or as
unverifiable → recompute UNVERIFIED → **false REGRESSION**. Both directions are corrupt.

The engine seam is already built and pinned: `run_corpus` / `run_case` /
`_recompute_trajectory_case` accept `shell_server_command`
(`src/belay/corpus/run.py:701-784, 787-814`), with routing proven by four tests in
`tests/test_corpus_trajectory_run.py`. **Only the CLI surfaces cannot express the boundary.**
`belay corpus run` has no `--shell-server` (`src/belay/cli.py:3330-3372`), and the parity
guard's `--shell-server` row (`tests/test_cli_flag_parity.py:85`) names only `{verify,
phase0 run, gate baseline, gate check}`.

Named NOT-built at `docs/planning/corpus-trajectory-banking/prd.md:145`; the same class of
gap — a replay-bearing surface that cannot ask for the shell boundary — is the defect the
flag-parity guard exists to prevent (`tests/test_cli_flag_parity.py:1-33`).

## Goals & Success Metrics

1. **A two-server trajectory case recomputes faithfully.** `belay corpus run
   --shell-server <cmd>` re-verifies a trajectory case banked from a two-server mint and
   reads MATCH — proven end-to-end by test through the CLI, not just the library seam.
2. **The no-flag path is honest, never silently wrong.** A trajectory case whose stored
   trace needs a second boundary the operator did not supply **SKIPs with a named cause**
   — never a false MATCH, never a false REGRESSION. Decided by the owner (2026-09-16,
   D2/D3): fail-closed operator-omission class, the `CLAIM_AXIS_DISABLED` precedent.
3. **The shell axis is expressible on every corpus replay surface.** `corpus add` (banking)
   and `corpus show` (recompute display) gain the flag too (owner, D4/D5), and the parity
   guard's comment/row set states the widened contract.
4. **Nothing else moves.** No verdict axis, case-schema field, or published number changes;
   `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16` stand unedited. Single-boundary
   trajectory cases recompute byte-identically to today.

## User Personas & Scenarios

- **The mint operator (owner).** Runs the next two-server mint; trajectory FAILs bank (the
  `corpus-trajectory-banking` namespace), and `belay corpus run --shell-server` re-verifies
  them as MATCH — the regression suite working on the axis that earned the number.
- **The harness engineer (regression safety).** A detection change that breaks trajectory
  detection now fails `belay corpus run` on a real banked two-server case. Without the flag
  they would chase a phantom: today the same run either certifies the wrong reason or fails
  the build for a CLI gap.
- **The manual adder.** `belay corpus add --shell-server` banks a `run_process` turn from a
  two-server capture with the boundary it actually replayed against.

## Requirements

### Must-have

- **M1 · `corpus run --shell-server`.** `belay corpus run` gains `--shell-server CMD`: a
  single quoted string, shlex-split at use, **fail-closed on an un-lexable string** (exit 2,
  named) — the exact `phase0 run` shape (`cli.py:3598-3610`, `2586-2588`). No REMAINDER
  ordering hazard (this parser has no `--server`). Threaded into `run_corpus` →
  `_recompute_trajectory_case`, where the seam already exists.
- **M2 · Faithful two-server recompute.** A constructed two-server trajectory case (mixed
  `edit_file` + `run_process` turns, stored fs command) recomputes **MATCH** through the
  real CLI with `--shell-server`, and the recording seam shows `run_process` replays routed
  to the supplied shell command. (The library-level routing is already pinned by
  `test_trajectory_recompute_routes_run_process_to_the_shell_command`; the new RED is the
  CLI end-to-end.)
- **M3 · Named-cause SKIP, no-flag.** A trajectory case whose stored trace has BOTH
  `run_process` and non-`run_process` turns, whose stored command is the fs boundary, and
  for which no `--shell-server` was supplied → **SKIP with a named cause** (proposed
  `TRAJECTORY_SHELL_BOUNDARY_NOT_SUPPLIED`), decided **before any replay** (read the stored
  trace's tool names; no mis-routed re-execution). The existing pin
  `test_trajectory_recompute_without_a_shell_command_is_byte_for_byte_today` is updated
  deliberately: byte-identical **only** for single-boundary traces.
- **M4 · Named-cause SKIP, unexpressible shape.** A trajectory case whose trace needs two
  boundaries AND whose recorded `case.target_tool` is `run_process` — the stored command
  IS the shell boundary (recorded at ingest, `case.py:174`, `add.py:416`; never inferred) —
  → **SKIP with a named cause** (proposed `TRAJECTORY_FILESYSTEM_BOUNDARY_UNEXPRESSIBLE`),
  **regardless of the flag**: the fs boundary was never recorded and `--shell-server` can
  only supply the shell side, so faithful recompute is impossible for this shape on this
  surface.
- **M5 · Single-boundary byte-identity.** A trajectory case whose trace needs only one
  boundary (all-`run_process`, or no `run_process` turns) recomputes **exactly as today**
  with no flag, and is unaffected by a supplied flag. No banked case needs re-adding.
- **M5b · Affected-test audit.** The M3/M4 SKIPs change a **named, enumerated set** of
  existing tests, and nothing else: (1) `test_trajectory_recompute_without_a_shell_command_is_byte_for_byte_today`
  (`tests/test_corpus_trajectory_run.py:705`) is rewritten to assert the named-cause SKIP;
  (2) `test_a_case_written_in_the_pre_change_format_still_loads_and_recomputes` (`:760`)
  moves to a single-boundary fixture so its MATCH pin keeps its intent (the key-set /
  no-shell-field assertion is untouched); (3) the shared mixed fixture
  `_build_mixed_trajectory_case` (`:662`) flips its turn order to
  `("run_process", "edit_file")` so its stored fs command matches its recorded
  `target_tool` — the old order (`edit_file, run_process`) records `target_tool=run_process`
  with a stored fs command, a shape **no real mint produces** (the ingest rule resolves the
  stored command from the final turn, `runner.py:536-538`); the routing test's assertion
  order updates, its values do not. Every other trajectory-recompute test stays green
  unchanged. The diff of the changed tests shows the SKIP cause / fixture flip as the only
  reason they moved.
- **M6 · `corpus add --shell-server`.** `belay corpus add` gains the flag; a `run_process`
  target turn banked with it stores the **shell** command (resolved for the target turn
  exactly as `phase0 run` does, `runner.py:104-122, 454-456`), and the banked case
  recomputes MATCH on `corpus run` with no further flag.
- **M7 · `corpus show --shell-server`.** `belay corpus show` gains the flag, threaded to its
  two `run_case` recompute calls (`cli.py:2385, 2417`); a two-server trajectory case shows
  MATCH with the flag and the named-cause SKIP without it.
- **M8 · Parity guard widened.** The `--shell-server` row (`tests/test_cli_flag_parity.py:85`)
  gains `corpus run`, `corpus add`, `corpus show`; its comment is rewritten (it does not
  mention `corpus run` today). `corpus show` joins `REPLAY_BEARING` (its recompute re-invokes
  a server — the "corpus show replays nothing" comment is stale, `:37-41`). Final row sets:
  `--server` → `_ALL - {"corpus run", "corpus show"}`; `--replays` →
  `_ALL - {"corpus run", "corpus show", "gate check"}`; `--timeout` →
  `_ALL - {"replay", "corpus run", "corpus show", "gate check"}`; `--manifest-dir` →
  `_ALL - {"phase0 run", "corpus run", "corpus show"}` — each excluded on the same per-case
  stored-value rationale already stated for `corpus run` (`:59-62, 66-75, 86-90`). `corpus
  show` does NOT gain `--no-claim-axis` (a display surface; declared sets stay as-is). Both
  guard tests stay green by construction.

### Should-have

- **S1 · Help and docs.** `corpus run` / `corpus add` / `corpus show` help texts state the
  flag, its shlex rule, and the named-cause SKIP; the `corpus-trajectory-banking` PRD's
  NOT-built line and `docs/STATUS.md`'s deferral lines (`:425, :474`) are retired exactly as
  wide as the slice; `docs/STATUS.md` gains the entry with the reclassification discipline
  (the updated no-flag pin is a deliberate behavior change on constructed fixtures only —
  no real banked two-server case exists, so no real-world reclassification).
- **S2 · `corpus run --help` honesty line.** The help text states that a two-server
  trajectory case without the flag SKIPs rather than recomputing against a guessed boundary.

### Nice-to-have

- **N1 · Aggregate line.** `corpus run`'s aggregate already counts SKIP; confirm the named
  cause is surfaced per-row (it is, via `skip_reason`) and no new aggregate row is needed.

## Technical Considerations

- **Capability:** C6 (failure corpus) follow-on slice — the recompute half of the shell
  axis. Dependencies C1–C6 built; no verdict machinery touched.
- **The SKIP decision is pre-replay.** `_recompute_trajectory_case` reads the stored trace's
  turn tool names once, decides boundary-need before `_verify_one_trace`, and returns a SKIP
  `CaseResult` (`skip_reason` named) for the two shapes in M3/M4. The gate precedent
  (`_baseline_skip`, `src/belay/gate/compare.py:267-295`) is *post*-recompute and
  substrate-class; this is operator-omission class, closer to `CLAIM_AXIS_DISABLED`
  (`run.py:199-204`) but decided without any replay.
- **Boundary-need rule.** A trajectory trace needs two boundaries iff it has ≥1
  `run_process` turn AND ≥1 non-`run_process` turn. Which boundary the stored command is:
  `case.target_tool` — the target turn's tool, **recorded at ingest** (`add.py:416`,
  derived from the trace, never guessed). For a trajectory case the target turn IS the final
  turn (`runner.py:481`), so `target_tool == "run_process"` means the stored command is the
  shell boundary. M3 = needs-two + stored-fs + no flag; M4 = needs-two + stored-shell
  (unexpressible regardless of flag). **The decision uses the same `calls` computation the
  recompute uses** — `tool_calls(derive_correlation(records))` over the case's stored trace
  (`phase0/runner.py`'s read path) — so the boundary-need decision and the re-execution can
  never disagree about which turns exist.
- **The claim half needs nothing.** `_recompute_claim_case` does not thread
  `shell_server_command`, but is self-consistent: the claim evaluator materialises the final
  state by replaying the **last** turn (`src/belay/verify/claims.py:387-411`) and the stored
  command is that turn's resolved command. The brief's "trajectory/claim" reduces to
  **trajectory only** — stated, not assumed.
- **Per-turn cases need nothing.** A per-turn shell case already stores the shell command
  (pinned by `test_flagging_shell_turn_stores_shell_command_in_case`); a caller-supplied
  boundary must never displace it (pinned by `test_per_turn_case_ignores_a_supplied_shell_command`).
- **No schema change.** The case format still stores ONE resolved command; the second
  boundary is caller-supplied, byte-for-byte the `_recompute_trajectory_case` design
  (`run.py:511-522`). No schema bump, no re-add.
- **Flag shape.** Single-string `--shell-server`, `default=None`, shlex-split at use,
  fail-closed — the `verify`/`phase0 run`/`gate` pattern (`cli.py:3180-3193, 3598-3610`).
- **Test-first.** Acceptance written as RED tests before code. The updated no-flag pin (M3)
  is the first test changed; its diff must show the SKIP cause is the only reason it moved.
- **Eval data / corpus.** No new case class — the value is that banked two-server trajectory
  cases (the corrupt-success class) become re-verifiable. The acceptance banks a constructed
  two-server case and recomputes MATCH (the `_build_mixed_trajectory_case` fixture shape,
  `tests/test_corpus_trajectory_run.py:662-683`). The no-backfill fact stands: no real
  two-server case exists to regress against; nothing is implied retroactively.

## Risks & Open Questions

- **R1..R12 mapping:** none of the register's risks maps cleanly; this unit retires no R-id
  and opens none. It serves moat #2 (the compounding corpus) and the honesty contract.
- **The final-turn-is-`run_process` edge (M4) is unreachable by `corpus run` today** — an
  honest capability gap, not a fixable one without a schema change (a second stored field)
  or a `--server` override on `corpus run` (both out of scope by the stored-boundary
  decision). SKIP-with-named-cause is the honest landing.
- **Detection cost:** the pre-replay trace read is a second read of `trace.jsonl` per
  trajectory case (the recompute reads it again inside `_verify_one_trace`). Corpus cases
  are small; accepted.
- **Reclassification discipline:** the M3 SKIP changes the outcome of constructed
  two-server fixtures from today's (corrupted) recompute. No real banked two-server case
  exists (mint's 11 TPs never bankable; no-backfill), so **no real-world verdict moves**.
  The STATUS entry states this plainly.
- **Boundary naming:** the two SKIP causes' exact names are settled in the plan
  (`TRAJECTORY_SHELL_BOUNDARY_NOT_SUPPLIED` / the unexpressible shape's name); they must not
  collide with `_SKIP_CAUSES` semantics (substrate class) — they are operator-omission /
  capability class and rendered via `CaseResult.skip_reason`.

## Out of Scope

- `--server` / `--replays` / `--timeout` / `--manifest-dir` on `corpus run` or `corpus
  show` — per-case stored values stay authoritative (the parity table's stated rationale).
- `interop correlate` / `interop export` / `invariant infer` shell routing — the documented
  single-boundary default (parity comment `:78-79`, S9 in the dig).
- Any change to `_recompute_claim_case` — self-consistent today (see Technical
  Considerations); a future change is a separate unit.
- Any case-schema bump, any verdict-axis change, any published-number re-derivation.
- Backfilling the mint's 11 TPs (impossible; s6 captures no longer exist) and any
  re-adjudication.