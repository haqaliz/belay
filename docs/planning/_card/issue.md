# Card — `feat/phase0-corpus-mint/aliz`

No GitHub issue: `phase0-corpus-mint` is a descriptive slug, not an issue id.
Source is the inline brief below, produced by `belay-next` on 2026-09-19 and
accepted by the user when they invoked `bbf feat phase0-corpus-mint`.

## Brief

Run a corpus-filling mint under the current engine composition to convert three
shipped-but-unexercised capabilities into measured results.

The corpus today holds 7 cases, all A1 false-positive negatives, and zero true
positives — so `corpus score` reads `precision n/a`, recall is unmeasured, and the
A3 column has only a synthetic fixture (`CHECKLIST.md:407-408`; verified by listing
`~/dev/at/holder/belay/corpus-local/`).

Reuse the 2026-08-12 shell-toolset composition (`--toolset filesystem+shell`,
composite transport, verbatim `run_process`) since it is the only one measured to
produce TPs — the two earlier mints were stopped by their own exposure and control
gates, which is this unit's main feasibility risk.

Acceptance is test-first and about *banking*, not a new rate: trajectory FAILs bank
as `trace-<instance>-trajectory` cases and recompute MATCH; an A3 intent-drift FAIL
banks a real (non-synthetic) case; `corpus score` reports precision and recall with
real denominators instead of `n/a`; and **no published number moves** —
`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00` stand unedited,
with any new figure stated as an addition.

Fold in the flag-parity gap found during the pick: `belay verify` has
`--claim-author` but `phase0 run` does not, so A3 is reachable only via
`BELAY_CLAIM_AUTHOR` — the same defect class the parity guard exists to catch.

> **⚠️ CORRECTED 2026-09-19, during the Phase-2 dig — this sentence is WRONG and must
> not reach the PRD.** The absence of `--claim-author` on `phase0 run` is **a recorded
> decision, not a defect and not a parity gap.** The parity table declares the flag's
> surface set as exactly `{verify, gate baseline, gate check}` with the reason stated
> in-line (`tests/test_cli_flag_parity.py:131-137`): *"the INTERACTIVE A3 author
> surface … the batch surfaces are env-only (`BELAY_CLAIM_AUTHOR`) by design (plan open
> question, decided at plan time)."* The open question is at
> `docs/planning/claim-re-derivation-a3/author/spec.md:53-55` and was decided at
> `.../surfaces/plan_20260902.md:19-22`. It is **pinned by a test that asserts
> `phase0 run --claim-author` exits 2** (`tests/test_verify_claim_surfaces.py:202-219`).
> Adding the flag is therefore *blocked-until-recorded*, not required: it would turn
> two guards RED and would mean reversing a decision, which needs its own justification.
> **The cheap path needs no flag at all** — export `BELAY_CLAIM_AUTHOR` into the
> environment of the `belay phase0 run` process (`cli.py:2593`).

Never rewrite recorded paths in the eval data (measured to break replay 0/11→7/11).

## Why this unit (from `belay-next`, 2026-09-19)

Three shipped capabilities are still labelled "a capability, not a result", and all
three wait on the same single action — a mint run under the current composition:

- `claim-re-derivation-a3` (`CHECKLIST.md:407`): *"no real intent-drift case exists
  yet — the fixture is synthetic, the mint's next run fills the A3 column."*
- `corpus-trajectory-banking` (`CHECKLIST.md:408`): *"nothing backfilled (s6 captures
  gone) — the value is forward-looking: the next mint's trajectory FAILs bank."*
- `CAPABILITY_ROADMAP.md` C6: *"No miss has been banked, so recall remains unmeasured
  and precision still reads `n/a`."*

Nothing has been minted since **2026-08-12** (`mint-shell-toolset-run`). Five
capabilities shipped after that date that a mint would exercise or fill:
`corpus-trajectory-banking` (09-01), `claim-re-derivation-a3` (09-02),
`invariant-library` (09-12), `ci-regression-gate` (09-13), `approval-gate` (09-15),
`invariant-authoring-experiment` (09-15).

## Measured state of the substrate (this session, 2026-09-19)

Run before any planning, because the unit depends on the eval substrate working.

### ⚠️ FINDING — the three load-bearing eval symlinks were MISSING, and are restored

`~/dev/at/holder/belay` holds all eval data. Three stub dirs under
`.claude/worktrees/` carry an `eval` symlink into it, so that absolute paths recorded
*inside* the banked traces/manifests still resolve after the original worktrees were
deleted. All three were absent at the start of this session.

Measured impact before restore — recorded references that did not resolve:

```
1344  /Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status
  17  /Users/aliz/dev/at/belay/.claude/worktrees/feat-subscription-model-client
   0  /Users/aliz/dev/at/belay/.claude/worktrees/feat-phase0-mint-execution
```

Restored with the recorded recipe (changes **no recorded byte** — that is the whole
reason the fix is a symlink and not a path rewrite):

```sh
for w in feat-verdict-coverage-status feat-phase0-mint-execution feat-subscription-model-client; do
  mkdir -p ~/dev/at/belay/.claude/worktrees/$w
  ln -sfn ~/dev/at/holder/belay ~/dev/at/belay/.claude/worktrees/$w/eval
done
```

**Verified after restore, by running it, not by asserting it:**

- `belay corpus run ~/dev/at/holder/belay/corpus-local` → **7/7 MATCH**, 0 REGRESSION,
  0 SKIP, 0 STILL_MISSED. Matches the recorded baseline.
- `belay phase0 run ~/dev/at/holder/belay/mint/s1p/batch --no-ingest --server …` →
  **VERIFIED_CLEAN 1, ERRORED 0**, exposure `judged 1 file-comparison(s)`,
  `effect:network NOT_COVERED 11/11`, **0 UNVERIFIED**. Matches the recorded
  baseline (`s1p` → `VERIFIED_CLEAN`, 0/11 UNVERIFIED).

**Open question for the PRD:** a *new* mint records absolute paths under this
worktree (`.claude/worktrees/feat-phase0-corpus-mint/`). When the worktree is removed
at `belay-end-fast`, the new captures inherit exactly this defect. The unit must
decide where a mint writes, or pre-register the stub+symlink as part of its own
teardown. This is a real recurrence, not a hypothetical — it has now bitten twice.

### Corpus contents — confirmed zero true positives

`~/dev/at/holder/belay/corpus-local/` holds exactly 7 cases, all the 2026-07 A1
false-positive negatives:

```
trace-pallets__flask-4045-turn8
trace-pallets__flask-4992-turn{10,12,14,19}
trace-pylint-dev__pylint-5859-turn{6,11}
```

No trajectory case, no A3/claim case, no true positive, no recorded miss.

### The s6 captures are confirmed gone

`~/dev/at/holder/belay/mint/` contains only `s1  s1b  s1p  s2  s3
live-smoke-claude-cli`. There is no `s6`, which corroborates the repeated doc claim
that the shell-toolset mint's captures no longer exist on disk and that its 171
per-turn FAILs and 11 hand-audited TPs **cannot be backfilled**.

### Pinned MCP servers are present

`~/dev/at/holder/belay/servers/node_modules/` — the filesystem server resolves:
`node …/@modelcontextprotocol/server-filesystem/dist/index.js {workspace}`.
Corpus cases already pin this absolute path in `server_command` (the one safe
path rewrite, done 2026-08-06).

### Two CLI facts the plan must respect

- **`phase0 run` has no `--claim-author`.** `belay verify` does; `phase0 run` exposes
  only `--no-claim-axis`. A mint reaches A3 exclusively through the
  `BELAY_CLAIM_AUTHOR` env var. This is the flag-parity defect class named in the
  brief (it bit `--timeout` in L7 and again in the console).
- **`--server` is `nargs=REMAINDER`.** It must come last and take the rest *without*
  a `--` separator; `--server -- node …` fails with `unrecognized arguments`. Same
  REMAINDER class as the three runbook defects found on 2026-09-06.
- **`--shell-server` must PRECEDE `--server`** for the same reason
  (`eval/README.md:792-794`, `entrypoint.py:686-690`).

### ⚠️ THE REAL A3 BLOCKER (found in the dig; distinct from the corrected non-gap above)

`eval/minting_driver/entrypoint.py:1029-1035` calls `phase0_runner.run_batch(...)`
**without `claim_author=`**. `run_batch`'s default is `claim_author=None`
(`src/belay/phase0/runner.py:153`) and A3 only engages when `claim_author is not None`
(`runner.py:419`). So **the mint's in-process `--verify` path can never fill the A3
column, no matter what `BELAY_CLAIM_AUTHOR` is set to.**

The README presents `--verify` and the printed `belay phase0 run` command as
equivalent (`eval/README.md:727-729`). They are not: the printed command reads the env
var (`cli.py:2593`), `--verify` does not. Two ways out, to be decided in the PRD:
(a) run the CLI command with the env var exported, or (b) thread `author_from_env()`
into `run_verify` at `entrypoint.py:1029`, respecting the lazy-`belay`-import
constraint documented at `entrypoint.py:1011-1018`.

### ⚠️ NO A3 REFERENCE AUTHOR EXISTS

There is **no shipped `claude -p` author for the A3 claim axis** anywhere in `src/`.
What exists: a `python3 -c` one-liner *example* in `README.md:155-161`, a manual live
gate that drives whatever the operator points at
(`tests/test_verify_author_live.py`), and a deterministic CI fake
(`tests/test_verify_author.py`).

Two reusable precedents, both with the **scrub-by-absence** idiom
(`env.pop(name, None)` over `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`/
`ANTHROPIC_BASE_URL`, never `""`):
`src/belay/authoring/reference_author.py:60-64, 177-190` (for `invariant infer`, the
closest analogue) and `eval/minting_driver/clients/claude_cli_client.py:117-121,
709-723`. Note `SubprocessAuthor` passes **no `env=`** (`author.py:107-113`), so
scrubbing is the author command's job, not Belay's.

**Writing an A3 reference author is therefore real scope in this unit**, not a
configuration step.

### ⚠️ FEASIBILITY: a real intent-drift case may not be producible on demand

For A3 to FAIL rather than fall silent, the drive must end with the agent
**voluntarily asserting verification** in its `Done` text (classified `VERIFICATION`
by `trajectory.py:112-127`) while the final state contradicts it. The claim record is
written post-capture from `transcript.done.reason` (`eval/minting_driver/batch.py:525-526`
→ `trace.py:616+`); a session that stops on `max_steps` or an error records nothing.

This is the **same shape the launch demo could not produce**: 18 observed drives
across two frontier models, an easy bug, a hard bug and an expensive-suite lever
yielded **zero** corrupt successes
(`docs/planning/launch-demo/demo-capture/DRIVES.md`). A plan that assumes the A3
column will fill with a real FAIL is assuming away a measured negative result. The
honest framing: a run that produces no intent-drift case is **a recorded result, not
a failure of the unit** — the same rule `invariant-authoring` applied to a model that
produces nothing calibratable.

## Out-of-band state at the time of branching

`PR #38` (`feat/corpus-shell-routing`) is open, code-complete and **RED**:

- `AttributeError: 'types.SimpleNamespace' object has no attribute 'shell_server'`
  at `src/belay/cli.py:2383` — pre-existing args stubs in
  `tests/test_coverage_rendering.py` and `tests/test_verify_boundary_cause.py`.
- `tests/test_docker_inimage.py:197` — the in-image skip-cause check rejects
  `replay-reinvokes-seatbelt` as unnamed on Linux.

This branch is cut from `master` (`2dec7c0`, v0.33.0) and does not include #38.

## Guardrails this unit must not violate (`CLAUDE.md`)

- Harness only — no agent framework. The minting driver is **eval-only**, never a
  product surface, never the `belay` CLI.
- No bare LLM judge. A3's model writes a check; **execution** decides; A3 can never
  emit PASS.
- `UNVERIFIED` is never rendered as `PASS`.
- **No published number moves.** `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
  `recall 0.00` stand unedited. Any new figure is an addition, stated with its
  denominator.
- R6/R7 hold by construction: the oracle gets no tools, one `tools/call` in flight.
