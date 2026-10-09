# Understanding: claim-author-live-probe (Phase 2 dig)

Source: `docs/planning/_card/issue.md` (inline brief, belay-next pick 2026-10-10).
Two read-only agents mapped the code paths and the planning record; this note is their synthesis.

## What this work really is

R-D's deferred evidence run, made cheap: re-verify the two banked run-3 trajectory-FAIL
traces (`django-11422`, `django-14382`) through the **real CLI** with the shipped reference
claim author configured, and observe the `last_abstention` sub-cause that run 3 never
recorded (`AUDIT.md:87-91`: *"the ledger does not record which, and nobody observed it"*).
The question is one sentence from `claim-axis-legibility/prd.md:193-200`: Belay kills a
subprocess author at `AUTHOR_TIMEOUT = 60.0` s (`src/belay/verify/author.py:63`) while the
reference author allows its `claude -p` child 600 s (`reference_claim_author.py:65-67`) —
**"Changing the timeout is out of scope (it changes A3 behavior); if the next A3-enabled run
reads `AUTHOR_TIMED_OUT`, that is the next unit's evidence."** This unit is that run. If the
evidence reads `AUTHOR_TIMED_OUT`, a conditional aspect ships an operator-settable author
timeout; otherwise the unit stops at the finding.

Second value, same run: if the author produces a check, this is **C8's first real A3
verdict on real data** (exit 0 = silence D3, non-zero = FAIL — the first real intent-drift
verdict; either way an observation, never a corpus mutation).

## The probe surface (verified in code)

- **`belay verify <trace> --manifest-dir <dir> --claim-author CMD --server node <fs> '{workspace}' --json`**
  is the direct observation point: `--claim-author` at `cli.py:3613-3623`, A3 whole-trace-only
  at `cli.py:1146-1181` via `RecordingAuthor`; `claim.sub_cause`/`sub_cause_detail` ride
  `claim_record`/`sub_cause_fields` (`verify/json.py:301-336`). The e2e driver uses this exact
  shape (`tests/test_claim_axis_e2e.py:91-108`).
- **`corpus run` cannot drive an external author at all** — no `--claim-author` flag (refusal
  pinned at `tests/test_verify_claim_surfaces.py:202-219`), `_StoredCheckAuthor` only
  (`corpus/run.py:728-745`), and trajectory recompute passes `claim_author=None`
  (`corpus/run.py:624-640`). The banked cases are observed, never re-driven.
- **`phase0 run` is env-only** (`author_from_env()` at `cli.py:2964`; no `--claim-author` flag —
  its absencse is pinned). `gate baseline`/`gate check` DO take `--claim-author` (`cli.py:4384-4394`,
  `:4526-4537`).
- **The traces are reachable**: `/Users/aliz/dev/at/holder/belay/mint/cm6/batch/trace-django__django-11422.jsonl`
  (+ `.manifests` sibling), same for `14382`; each carries exactly one `claim` record (seq 24).
  Banked cases at `/Users/aliz/dev/at/holder/belay/corpus-local/trace-django__*‑trajectory/`
  (`human_label: pending`, schema v5, no `claim` expected key).

## Contradiction the brief carries — flag, do not paper over

The brief says "env + flag parity on **verify/phase0/corpus**". That is the
`--no-claim-axis` surface set, not the author-construction set. Reality:

| Surface | `--claim-author` flag | Author constructed? |
|---|---|---|
| `verify` | yes | yes (`cli.py:971`) |
| `gate baseline` / `gate check` | yes | yes (`cli.py:1990`, `:2145`) |
| `phase0 run` | **no** (env-only, pinned) | yes (`cli.py:2964`) |
| `corpus run` | no | **never** (`_StoredCheckAuthor`) |

So the knob's flag set is `{verify, gate baseline, gate check}` (the `--claim-author` row in
`tests/test_cli_flag_parity.py:152-158`, which is the registration site a new flag needs),
plus an env fallback that also reaches `phase0 run`. "Corpus" gets nothing. The PRD decides
and states this correction.

## Affected areas (conditional knob, if evidence reads TIMED_OUT)

`src/belay/verify/author.py` (a timeout source readable by `author_from_env` — note the
def-time default-arg trap, `surface-threading/plan_20260925.md:58-61`), `src/belay/cli.py`
(the three construction sites + new argparse + env), `tests/test_cli_flag_parity.py`
(`EXPECTED` row), `tests/test_verify_author.py` (`:121` pins `configured.timeout ==
AUTHOR_TIMEOUT` — keep the default unchanged and this pin survives), README (the operator
learns the knob; today README states no timeout value, `README.md:295,349`), docs
(CAPABILITY_ROADMAP C8 / STATUS "Not built" lines — additive only).

**Not touched:** `verify/claims.py` (vocabulary, evaluator), verdict reduction, A1/A2,
`authoring/protocol.py`'s separate `AUTHOR_TIMEOUT` copy (invariant-authoring path, out of
scope), `TRIAGE_TIMEOUT` (mirror decided `jev-triage/triage-seam/spec.md:33`; Jev measured
0.9 s — no evidence of starvation there in this unit).

## Precedent shapes this unit must mirror

- **Freeze protocol (Rule D, `phase0-mint-run/prd.md:97-101`)**: script committed first
  containing **no result** (grep-checked); run **once**; verbatim `.out` committed next,
  whatever it says; a second run only if declared. Freeze commit hash named in the findings.
- **Wrapper-record trick** (`tests/test_reference_claim_author_live.py:136-150`,
  `a3-author/live-run.md:80-84`): the `--claim-author` command is a wrapper that records each
  invocation to disk (and may time it) then `exec`s the shipped module, so *"the author ran"*
  is an observed fact. Assert `invocations >= 1` (a run where A3 never engaged must fail).
- **`manual`-marked, owner-run, never CI** (`pyproject.toml:77-94`; the live test FAILS with
  instructions rather than skipping when the model env is unset).
- **Three operator-error hazards already documented** (`live-run.md:91-105`): `--manifest-dir`
  required; `--server` needs the `{workspace}` token; the JSON key is `claim` (not
  `claim_record`).

## Open questions (for the PRD interview)

1. **Non-TIMED_OUT evidence**: if the observed sub-cause is `AUTHOR_EXITED_NONZERO` (with the
   reference author's one-line stderr) or `AUTHOR_DECLINED`/`AUTHOR_RAISED`, the unit stops at
   the finding — confirm the knob does NOT ship (brief says conditional; R-D's letter agrees).
2. **If TIMED_OUT**: keep the 60 s default and add the knob (`BELAY_AUTHOR_TIMEOUT` env +
   `--author-timeout` on the three author surfaces), or align the default upward? The
   conservative shape keeps the default (the `:121` pin and every existing behavior survive;
   an operator with a slow author opts in). Decide and state.
3. **Model + cost**: `claude-opus-5` (the live-run precedent), one author invocation per trace,
   owner subscription, `manual`-marked. Each verify replays the trace to materialize the final
   state before authoring (the expensive part).
4. **What the wrapper records**: sub-cause is the verdict; wall-time of the author invocation
   is a bonus fact the wrapper can observe (start/stop around the exec) — worth defining.
5. **Deliverables placement**: `docs/planning/claim-author-live-probe/` (freeze script + `.out`
   + findings); the manual test at `tests/test_claim_author_live_probe.py` (a new file, not an
   edit of the invariant-authoring live test).

## Guardrail check

A3 only (downgrade-only axis; a timed-out author is UNVERIFIED `NO_CHECK_AUTHOR`, never PASS);
BYOK, no egress (local `claude` CLI, owner subscription); no agent framework; no verdict
reduction, exit-code or gate change; **no published number moves** (`11/60 = 18.3%`,
`precision 0.00`, `1/15`, `4/16`, `recall 0.00`, `3/93` stand unedited); the two
`belay corpus label` judgments remain the owner's alone (`AUDIT.md:93-97`). Not a gate run;
produces no Phase-0 number. Suite baseline: **2895 passing** (45 skipped, 14 deselected;
`STATUS.md:25-26`).
