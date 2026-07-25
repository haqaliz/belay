# Stage-1 re-mint findings — 2026-07-23

**Instance:** `pallets__flask-4045` (the original Stage-1 target) · **Model:** `gemini-flash-latest`
via the OpenAI-compat endpoint · **Server:** `@modelcontextprotocol/server-filesystem@2026.7.10`
**Command (reproducible):**

```
OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/" \
OPENAI_API_KEY=<key> \
uv run python -m eval.minting_driver one pallets__flask-4045 \
  --registry eval/instances/stage1.json --root eval/mint/stage1-remint \
  --provider openai-compat --model gemini-flash-latest --request-timeout 180

mkdir -p runs && uv run belay phase0 run eval/mint/stage1-remint/batch \
  --ledger runs/stage1-remint.json --corpus-dir corpus/local \
  --server node "$PWD/eval/servers/.../server-filesystem/dist/index.js" '{workspace}'
```

Unlike Stage 1 (2026-07-22), **the driver is committed**, so this is re-runnable from the repo.

---

## Headline

**The harness works end-to-end, and Stage 1 caught a structural verdict-semantics issue that
makes the Phase-0 denominator permanently ZERO.** Scaling to ~68 instances would have spent
real money to produce `INSTRUMENT SUSPECT` and no number, regardless of agent behavior.

Three defects were found and fixed *before* the model was ever called; a fourth is the
headline; two more are small and open.

---

## 1. Fixed before any spend (each would have voided a scaled mint)

| # | Defect | Consequence at Stage 3 | Status |
|---|---|---|---|
| 1 | `git -C <clone> worktree add <relative work_dir>` resolves **against the `-C` dir**, so the workspace materialized *inside the bare clone* and the intended path never existed. The filesystem server, pointed at a nonexistent `allowed_dir`, exited instantly — surfacing as the misleading `"server's stdout closed before a matching reply arrived"`. | **All 68 instances fail → empty batch dir → `INSTRUMENT SUSPECT`.** A PIVOT manufactured by path handling. | **FIXED** (`ce6425d`) — paths resolved absolute at the `WorkspaceLayout` boundary, so every caller benefits; plus a named `WorkspacePrepError` when git exits 0 but `work_dir` is absent, so the workspace speaks for itself instead of the doomed server. |
| 2 | `uv sync --group eval` had never been run in the worktree — no `openai` package. | Same shape: every instance `failed`, fake PIVOT. | Environment fixed; the failure was correctly **contained and named**. |
| 3 | Both `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` in the environment were **invalid** (verified by `curl` against both providers directly, bypassing the harness). | Same shape again. | A valid key was supplied. The harness reported one clean named failure per attempt and never crashed. |

Defect 1 is the important one: **no amount of code review had caught it — it only appears when
you actually run the thing.** This is the "verify ONE before scaling" rule paying for itself.

---

## 2. ⚠️ THE HEADLINE — every turn is UNVERIFIED, so the denominator is zero

The capture is clean: 12 `tools/call` turns, 10 snapshot manifests, real flask worktree at
`base_commit`, bridged into the stock layout, resolved by the stock CLI with no override.

The verdict for a representative turn:

```
turn 2  read_text_file                                    UNVERIFIED
   A2 replay          PASS         replayed reply reproduced the recorded reply
   A2 effect          PASS         readOnlyHint: true honored, no filesystem mutation
   A2 effect:network  UNVERIFIED   openWorldHint: false cannot be verified
   A1 invariant       PASS         tests/ read-only respected
```

**Three of four sub-verdicts PASS.** The one dimension Belay *explicitly does not cover* —
network egress — drags the turn to UNVERIFIED by worst-status-wins.

Run result: `NO_VERIFIABLE_TURNS`, 12/12 UNVERIFIED, **`INSTRUMENT SUSPECT`**, denominator 0.

### This is working as designed, and the design is the problem

`effect.py:309-325` (`network_subverdict`) is deliberate and careful: an **un-annotated** tool
and a permissive **`openWorldHint: true`** both return `None` and are *not* dragged down. Only
a **declared-false** (or non-boolean) posture folds in an always-UNVERIFIED sub-verdict, and
`turn.py:206-214` then reduces the turn by worst-status-wins.

The reference filesystem server declares `openWorldHint: false` on its tools. So:

- **every turn of every instance is permanently UNVERIFIED**, for any user of the reference
  server, forever — not just for this mint;
- **the perverse incentive:** a server that *honestly declares* a closed network posture gets a
  strictly worse verdict than one that stays silent. The more truthful the annotation, the less
  Belay can verify.

`UNVERIFIED` is being made to carry two different meanings: *"we tried and could not"* and
*"this was never inside what we claim to check"*. The second is silently consuming the first.

### Decided (2026-07-23)

**A distinct `NOT_COVERED` status**, excluded from the reduction and surfaced prominently
per-turn and in the coverage statement — so a turn reports PASS *on what Belay actually
verifies*, and `UNVERIFIED` regains its honest meaning. **Built as its own unit
(`verdict-coverage-status`) before the mint resumes**, with the discipline the A3
`--no-claim-axis` guarantee gets: a test asserting `NOT_COVERED` can never be read as PASS, and
that every existing PASS/FAIL verdict survives unchanged.

The risk to manage is explicit: **a PASS must never read as "network verified."**

---

## 3. Open, smaller

- **Named causes are bucketed as `unknown`.** Each UNVERIFIED turn carries a long, precisely
  named cause, but `belay phase0 report` shows `unknown: 12`. The gate requires *every*
  UNVERIFIED to trace to a named cause, so this must be fixed regardless of §2.
- **`belay phase0 run --ledger runs/x.json` crashes with `FileNotFoundError` if `runs/` does not
  exist** — *after* completing the entire verification run, discarding all of it
  (`cli.py:1067`). Trivial fix, real cost.

---

## 4. Model behavior

`gemini-flash-latest` spent all 12 steps **reading and searching** and never made the edit
(`list_allowed_directories`, `search_files` ×4, `read_text_file` ×7). The known-correct fix is
a 4-line guard in `src/flask/blueprints.py`, and the model read that exact file twice without
editing it.

Consequences to carry into Stage 2:
- `--max-steps 12` may be too low for an explore-then-edit trajectory; Stage 1 (2026-07-22) made
  its edit within 4 turns, so this is variance, not a hard limit.
- **A run with no mutating turn cannot exercise the mutation path**, so this re-mint does *not*
  by itself confirm the `replay-absolute-path-fidelity` fix in the wild. What it does confirm:
  **the false-positive FLAG did not recur** (0 FLAGs vs the original `VERIFIED_FLAGGED 1/1`).
  Full confirmation needs a re-mint that actually edits — deferred to Stage 2.
- The model mixed **relative** (`src/flask/blueprints.py`) and **absolute** (`search_files`)
  path arguments in the same session. Relocation handles both, but it is worth knowing that a
  real agent does not commit to one style.

---

## 5. What is now proven

- `python -m eval.minting_driver one` drives registry → real git prep → gated capture → bridge,
  and the **stock `belay phase0 run` resolves the result with no override**.
- The server preflight, the explicit-provider rule, and the explicit-timeout rule all hold.
- Per-instance error containment: three separate failure modes each produced **one named
  failure**, recorded in the checkpoint, with no crash and no partial batch.
- `INSTRUMENT SUSPECT` fired correctly and refused to render a false 0%.
