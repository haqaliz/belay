# Invariant Authoring Experiment — understanding (Phase 2 dig)

> Produced by the Phase 2 dig (agents team), 2026-09-15, in the
> `feat/invariant-authoring-experiment` worktree. Source of truth: the unit card
> (`docs/planning/_card/issue.md`), ROADMAP, the invariant-library and A3 planning
> docs, and the code paths in `src/belay/verify/` + `eval/`.

## What the work is really asking

R3 ("nobody authors the invariant", High/High, `docs/ROADMAP.md:372`) has two of its
three mitigations shipped: annotation-inferred invariants inside C5, and the common
invariant library (`invariant-library`, v0.31.0, 2026-09-12). The third — **the
Phase-2 authoring experiment** — is explicitly deferred: "inferred-from-task-spec,
per-repo libraries, an authoring UI" (`docs/planning/invariant-library/prd.md:151-152`).
ROADMAP:308 says it "gets a real experiment, not an assumption" and names the candidate
answer this unit tests: **an invariant inferred from the task spec** (the other three
candidates — annotations, a library, user authoring — already ship).

The slice: a path where **a model writes an A1 invariant from a task spec, and
execution decides** — the A3 split ("a model writes a check; execution decides",
`claim-re-derivation-a3`) applied to A1 authoring. Deliverables per the card:
(1) an authored invariant FAILs the corrupt-success fixture and PASS/abstains the clean
control; (2) a mis-broad authored invariant degrades to UNVERIFIED, never FAIL;
(3) banked per-entry corrupt-success corpus cases recomputing MATCH (the
invariant-library pattern); (4) one real authored-invariant run against the launch
capture (manual, not CI).

## The precedent that exists in code (A3, shipped)

- `src/belay/verify/author.py` — "A3's model-backed author, behind the `CheckAuthor`
  seam … shelling out to a user-supplied command — BYOK by construction.
  `BELAY_CLAIM_AUTHOR` names a command line." JSON-in/JSON-out, fail-closed `None` on
  any failure. The closest existing seam for "an out-of-process command produces a
  machine-checkable artifact."
- `src/belay/verify/claims.py` — A3 evaluator: exit code decides; **A3 never emits
  PASS**; exit 0 → silence; no author → axis absent on the coverage line (never
  UNVERIFIED, never PASS).
- The BYOK subprocess pattern (env scrub by absence never `""`, `--tools ""` +
  `--strict-mcp-config`) is proven in `eval/minting_driver/clients/claude_cli_client.py`
  and pinned by tests.

## The constraints that bind the design (each is a shipped guard)

1. **The provenance boundary, not negotiable.** "the agent must never be able to
   author its own policy"
   (`phase0-corpus-audit/understanding.md:194-195`). A model-authored invariant is
   still operator-declared policy once the operator runs the authoring command — but
   the invariant must arrive by an **operator-run** path, never from the trace, and
   the structural guard `test_no_invariant_is_ever_sourced_from_a_trace`
   (`tests/test_invariants.py:55-114`) enumerates every invariant producer and will
   break until the new producer is admitted **deliberately**.
2. **No bare LLM judge.** "A model may *write a check*; only execution may *decide*"
   (CAPABILITY_ROADMAP.md:916-917). The authored artifact is enforced by
   `evaluate_invariant`, same as file-loaded policy.
3. **Zero-LLM AST guard** (`test_verify_zero_llm.py`) covers `src/belay/verify/`.
   A model-backed author that imports into the engine would trip it — the author must
   stay behind a subprocess seam (A3's pattern) or be excluded by name, never the
   engine calling a model.
4. **Precision history.** A1's naive rule fired 0/7 (shapes A/B/C,
   `phase0-corpus-audit/understanding.md:41-45`); the repair shipped "judged against
   the **task pre-state** and the **resulting content**"
   (CAPABILITY_ROADMAP.md:584-588). The experiment's abstain-by-default is the
   same lesson: a mis-broad authored invariant must never manufacture a FAIL.
   Nuance (from the dig): the repo already decided abstain-everything is an
   acceptance failure **on human-adjudicated negatives** ("PASS, not merely
   not-FAIL", `invariant-test-mutation-shape/prd.md:63,72-85`) — both constraints are
   live and bind different fixtures.
5. **Operator files never accept unimplemented rules.** Unknown rule names exit 2,
   fail-closed (`invariants.py:247-253`); library selection is exit 2 on unknown name
   (`resolve_library_entry`). An authored invariant must meet the same contract.
6. **Flag-parity guard** (`tests/test_cli_flag_parity.py`): a new flag on verify that
   also lands on corpus add / phase0 run / gate baseline must be declared in the fact
   table.

## The real code paths (from the dig)

- Rules: `src/belay/verify/invariants.py` — `Invariant(scope: bytes, rule: str)`;
  admission = constant + `_KNOWN_RULES` + exactly one grounding set
  (CONTENT_GROUNDED / INSTANCE_LEVEL / _DELTA_GROUNDED) + a branch in
  `evaluate_invariant`. Abstain causes are closed-vocabulary str constants stamped
  into `Verdict.expected["cause"]`.
- Loader: `load_invariants(path)` (operator file: JSON list of `{"scope","rule"}`);
  library resolver `resolve_library_entry(name)` is the shipped precedent for a
  "third producer" admitted into the provenance guard by name.
- CLI: `invariant-library` subcommand group at `cli.py:3858` — natural home for a
  sibling `invariant` group; `--invariant-library` wiring on four surfaces.
- Corpus: `CASE_SCHEMA_VERSION = 5`; banked fixtures via real `add_case` + `corpus
  run` MATCH/REGRESSION, house pattern in `tests/test_invariant_library_e2e.py`
  (fixture guards, per-entry CLI fixtures via `TraceWriter` over real snapshots,
  banked round trips). Recompute uses the **stored** invariants, never re-resolves
  the name.
- BYOK: `eval/minting_driver/clients/claude_cli_client.py` `ClaudeCliModel`
  (injectable `runner=` seam; offline tests; env scrub absent-never-`""`).
- Tests: `tests/test_verify_author.py` (A3 fake-author tests) is the analog home for
  `tests/test_invariant_author*.py`; darwin-gated only where replay re-invokes
  seatbelt. Suite 2428/2439 collected (2403 passing).

## Open questions (for the interview — context cannot resolve these)

1. **Where the authored artifact lands**: Fork A — a reviewable **file** produced by
   an `belay invariant infer`-style subcommand, consumed later by the existing
   `--invariants` (human-in-the-loop; provenance boundary intact). Fork B — inline
   at verify time via `--invariant-author` (A3-style). Fork A keeps policy reviewable
   and the operator-file contract unchanged.
2. **The mis-broad guardrail's mechanism**: how the engine knows an authored invariant
   is mis-broad. Leading candidate: a **calibration/control step** — the authored
   invariant is first evaluated against the task's clean baseline (the control); an
   over-fire there degrades the invariant to UNVERIFIED with a named cause instead of
   FAILing the target run.
3. **Which surfaces carry the flag** (verify-only vs the four replay-bearing surfaces)
   — the flag-parity guard requires the decision up front.
4. **Reference author**: `src/belay/`-adjacent JSON-in/JSON-out author wrapping
   `claude -p` with the proven env-scrub, or the unit ships only the seam with a
   `scripts/` reference author and the live run stays manual (A3 precedent: live smoke
   is `manual`-marked, never CI).
5. **The launch-capture deliverable** is a manual run, not a CI test (the capture is a
   clean negative control; no corrupt-success case can be banked from it).

## Axes

- **A1** — the authored artifact is enforced by the existing A1 machinery; no new
  verdict axis, no new status.
- **A3** — untouched. The experiment borrows its "model writes, execution decides"
  split and its out-of-process BYOK author seam; A3's own follow-ons (WARN vocabulary,
  caller-supplied-workspace short-circuit) are separate units.