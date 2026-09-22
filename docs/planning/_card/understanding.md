# Understanding — C10 triage seam (shadow mode)

## What this work is really asking

A BYOK, off-by-default triage/router seam that orders and samples which recorded turns get
the expensive replay verification, using a cheap external decision model. Execution alone
decides every verdict. Slice 1 is **shadow mode**: the seam exists, triage runs and logs
alongside, the replay budget is untouched, nothing is skipped, and triage on/off produce
identical verdicts on the turns replayed.

## Key findings from the dig

1. **The seam mirrors the A3 `SubprocessAuthor` pattern exactly** — and that pattern is
   already model-agnostic:
   - `BELAY_CLAIM_AUTHOR` env / `--claim-author` flag, unset/blank/un-lexable => `None`
     (axis absent, never a crash): `src/belay/verify/author.py:45,56-74`.
   - `SubprocessAuthor` (BYOK, stdlib-only, JSON-in/JSON-out, fail-closed parse):
     `author.py:77-143`; protocols `CheckAuthor`/`CheckRunner`: `verify/claims.py:120-145`.
   - Engine never reads or forwards any key; the operator's command handles its own
     credentials. Reference author scrubs `ANTHROPIC_*` by absence, never `""`:
     `verify/reference_claim_author.py:72-76,209-224`.
   - **This satisfies the owner's PS (laya / any model) by construction**: any triage model
     = any subprocess command. Jev and Laya are reference authors, not engine providers.
     The engine must NOT grow vendor adapters or an HTTP client (would break the
     zero-LLM guard `tests/test_verify_zero_llm.py`).

2. **The per-turn loop lives above `verify_turn`** — the only place ordering/sampling can
   happen: `phase0/runner.py:303-319` (mint loop), `cli.py:1034-1040` (verify CLI),
   `corpus/run.py:870-878` (per-turn cases). Replay itself is inside `verify_turn` at
   `turn.py:369-373`. Slice 1 scopes to the **verify CLI** (mirroring the pinned
   `--claim-author`-on-verify-only decision: `tests/test_verify_claim_surfaces.py:202-219`).

3. **Flag-parity guard** (`tests/test_cli_flag_parity.py:45-57,62-148,173-198`): any new
   flag must be declared in `EXPECTED` or the discovery test fails.

4. **UNVERIFIED-by-budget needs a named cause** in the closed vocabulary
   (`replay/report.py:69-138,152-172` + the guard pattern of
   `test_interop_attach.py:476-494`). In shadow mode the cause exists but is never emitted
   (nothing is skipped); the honest rule: a skipped turn is UNVERIFIED-by-budget, never PASS.

5. **The identity test mirrors `tests/test_refutation_no_claim_axis.py`** — same input,
   axis on vs off, byte-identical PASS/FAIL, named SKIP (never REGRESSION), plus an
   anti-vacuity spy proving triage really engaged.

6. **Manual live test conventions**: `@pytest.mark.manual`, excluded via
   `addopts = "-m 'not manual and not install'"` (pyproject.toml:86-94); owner-run env
   (e.g. `BELAY_REFERENCE_AUTHOR_MODEL`); FAIL-with-instructions when unset
   (`test_reference_claim_author_live.py:118-125`). The owner's PS: API key for local test
   only — provided by the owner, never for users, never committed.

7. **Derived-feature whitelist** (no raw state/trace bytes): tool name, annotation tri-state
   per hint, annotations_object presence, toolset offered, reply size, hashes
   (`hash_raw`/`hash_canonical`), turn index/seq, ordering, truncated flag, state_handle
   status, trace context (traceId/spanId), protocol version, run_process command_line —
   from `trace.py:391-437,546-565`, `turn.py:119-140`, `annotations.py:60-81,103-257`,
   `index.py:113-229`.

## Contradictions / ambiguities flagged

- **The proposed PRD is Jev-named throughout** (`JevTriage`, `BELAY_JEV_KEY`). The owner's
  PS demands a **model-agnostic seam** (jev, laya, ...). Resolution: the seam is
  provider-neutral (subprocess command + protocol); Jev is the *first reference author*;
  `BELAY_JEV_KEY` is read only by that reference author, never by the engine. The PRD must
  be rewritten to this shape before planning.
- The A3 precedent scrubs `ANTHROPIC_*` from the child env; a triage reference author
  instead *needs* its key — the honest line: the engine neither reads nor passes any key;
  the operator's command owns its credentials. Must be stated, not assumed.
- Shadow mode "logs triage alongside" — where? Precedent: the approval-gate additive
  `approval` section in verify output (absent-never-zero). Proposal: additive `triage`
  section in `--json` + text line, absent-never-zero.

## Open questions for the owner (Phase 3)

1. Jev API surface for the reference author: REST endpoint + key header? OpenAI-compatible?
   A CLI? (Determines the reference author shape + the manual live test.)
2. Slice-1 reference author: Jev only (seam proven model-agnostic by a stub), or also a
   Laya reference author now?
3. Budget knob: confidence threshold, top-N-least-confident, or both?