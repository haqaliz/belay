# PRD: Invariant Authoring — the Phase-2 authoring experiment

**Status:** draft, pending review gate
**Unit:** `feat/invariant-authoring-experiment/aliz`
**Date:** 2026-09-15
**Source:** unit card `docs/planning/_card/issue.md`; `docs/ROADMAP.md:308`;
`docs/planning/invariant-library/prd.md:151-152`
**Axes:** **A1 only.** A3 is untouched and can never emit PASS. No new verdict
axis, no new status, no invariant default change.

---

## Problem Statement

R3 — "nobody authors the invariant: A1 works but only if someone declares the
policy" — is **High/High** (`docs/ROADMAP.md:372`). Its mitigation has three parts:
annotation-inferred invariants (shipped inside C5), a library of common invariants
(shipped, `invariant-library`, v0.31.0, 2026-09-12), and an explicit Phase-2
authoring experiment, deferred by name: *"The Phase-2 authoring experiment
(inferred-from-task-spec, per-repo libraries, an authoring UI) — R3's third
mitigation, later unit"* (`docs/planning/invariant-library/prd.md:151-152`).

ROADMAP:308 states the problem and the candidate answers this unit tests:
*"who writes the invariant for a stranger's agent? Candidate answers to test —
inferred from MCP annotations (free), inferred from the task spec, a library of
common invariants, or authored by the user. This is a real adoption risk and gets
a real experiment, not an assumption."* Three of the four candidates have shipped.
**This unit tests the fourth: an invariant inferred from the task spec.**

The hard part is not generation — it is **trust**. A1's history is a precision
failure: the naive default fired 7 times on real mint data and was right zero times
(`precision 0.00`, `CAPABILITY_ROADMAP.md:388`; shapes A/B/C,
`phase0-corpus-audit/understanding.md:41-45`), and the repair's acceptance refused
the abstention loophole on adjudicated negatives ("PASS, not merely not-FAIL",
`invariant-test-mutation-shape/prd.md:63`). A model-authored invariant that
manufactures violations is worse than no invariant, because it teaches operators to
distrust authored policy. So the experiment must answer two questions, not one:
**(1) can a model propose a task-specific invariant that catches the real
violation? and (2) can the engine admit it to A1 only after execution proves it
does not over-fire on a known-clean run — and can the artifact carry that proof so
that a later edit cannot silently launder an uncalibrated rule into a FAIL?**

## Goals & Success Metrics

- **Goal 1 — Authored invariants fire where they should.** An invariant inferred
  from a task spec, enforced through the shipped A1 machinery, FAILs the
  corrupt-success fixture **at the exact turn**, naming the invariant and the diff —
  the C5 contract (`CAPABILITY_ROADMAP.md:367-375`) applied to an authored rule.
- **Goal 2 — Authored invariants never manufacture a violation.** A mis-broad
  authored invariant degrades to **UNVERIFIED with a named cause** — never FAIL,
  never a silent PASS, never a silent skip. Calibration against a known-clean
  control is the mechanism, and the artifact's integrity is what keeps the proof
  attached to the exact policy that was calibrated.
- **Goal 3 — The artifact is reviewable and tamper-evident.** The authored policy
  is a human-reviewable file with provenance (task hash, control hash, author
  identity, calibration digest). Editing the policy after calibration invalidates
  the calibration, and an invalidated authored invariant cannot FAIL.
- **Goal 4 — Honest boundaries and no movement.** No published number moves
  (`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00` stand
  unedited); A3 untouched; defaults unchanged; zero new runtime dependencies; the
  live model run is `manual`-marked and never in CI.

**Measured by:** RED/GREEN fixture pairs (corrupt fixture FAILs at the exact turn;
clean control PASSes or abstains); a rejected-over-broad-candidate test; a
tamper-degradation test (UNVERIFIED with the named cause); per-authored-invariant
banked corpus cases recomputing MATCH; the provenance guard amended and green; the
flag-parity table green; the suite green.

## User Personas & Scenarios

- **The self-hoster with a stranger's agent** (R3's actual victim). They have a
  task spec and a repo, and no idea which invariant to declare. They run
  `belay invariant infer --task task.md --repo . --author '<cmd>' --control <clean-trace> --out .belay/invariants.json`,
  review the emitted file (each candidate carries a rationale), commit it, and add
  it to their verify/CI invocation via the existing `--invariants` flag. The
  authoring path never enters the verdict path: it produces policy, execution
  decides.
- **The operator who edits the artifact.** They change a scope by hand after
  authoring. The calibration digest no longer matches, so the affected invariants
  evaluate **UNVERIFIED** with the named cause `AUTHORED_INVARIANT_ALTERED` — the
  run does not silently enforce a policy nobody calibrated, and it does not
  fabricate a FAIL. The remedy is re-running `infer`.
- **The CI reviewer.** A banked corrupt-success case per authored invariant
  recomputes MATCH on every PR; drift in the calibration or the artifact schema
  flips the set and turns CI red.

## Requirements

### Must-have

**M1 — `belay invariant infer` (new subcommand).**
`belay invariant infer --task <spec-file> --author <cmd> [--repo <dir>]
--control <trace> [--manifest-dir <dir>] --server -- <CMD...> [--timeout N]
[--replays N] --out <file> [--json]`. It (a) builds the author protocol input,
(b) runs the author command out-of-process, (c) validates and calibrates the
candidates, (d) emits the authored artifact. It replays **only the control**, and
reuses the shipped verify path — no second evaluator (the repo's reuse rule, cf.
`verify-tool-not-offered`'s probe reusing `client.replay_turn`). The control's
manifest dir defaults to the trace's `<stem>.manifests` sibling only when it
exists; absent either the fail-closed error stands, never a guessed context.

**M2 — The author protocol is a subprocess seam, BYOK by construction.**
The author is an operator-supplied command (A3's `BELAY_CLAIM_AUTHOR` /
`SubprocessAuthor` precedent, `src/belay/verify/author.py`), JSON-in/JSON-out on
stdin/stdout. Input: the task spec text, an optional bounded repo inventory, the
known rule vocabulary with grounding semantics, and the library entries. Output:
`{"candidates": [{"scope": str, "rule": str, "rationale": str}, ...]}`. Any
failure — non-zero exit, timeout, unparseable output, missing key — is
**fail-closed**: exit 2 with a named cause, no artifact written, never a silent
empty policy.

**M3 — Calibration is execution, not opinion.**
Each candidate is evaluated against the supplied **clean control** by replaying the
control once with the candidate set, through the same composition `belay verify`
uses. A candidate that yields **FAIL on any control turn is rejected** with a named
cause (`CALIBRATION_FAILED`); PASS and UNVERIFIED on the control are both
acceptable (the card's "PASS or abstain the clean control"). If no candidate
survives, exit 2 — never emit an empty artifact. **If the control cannot be
replayed to a decision** (unrestorable pre-state, a boundary that does not offer
the tool, every turn UNVERIFIED), calibration is vacuous: infer exits 2 with
`CONTROL_UNREPLAYABLE` and emits nothing — a vacuous calibration must never be
recorded as `"calibrated"`. The control is operator-chosen evidence; its trace hash
is recorded, and the honest limit is stated: calibration proves *this invariant
does not fire on this control*, nothing more. The task spec is untrusted input to
the author; a hostile spec that induces an over-broad candidate is rejected by the
same calibration, and that path is tested.

**M4 — The authored artifact.**
A new JSON schema, `"belay-authored-invariants/1"`, carrying: schema version;
author identity (command display string, model id — **no secrets**); task path +
sha256; control trace path + sha256 + turn count + calibration verdict; a
`calibration.digest` over the **canonical policy set** (the normalized
`{"scope","rule"}` pairs only — rationale text is not policy); and the invariants
with rationales. Written atomically; deterministic for a fixed fake author and
fixed control (byte-identical re-runs). Emitting an artifact is the *only* write
this unit performs.

**M5 — Verify-side trust: an uncalibrated authored invariant can never FAIL.**
`--invariants` reaches **four surfaces** (`verify`, `corpus add`, `phase0 run`,
`gate baseline`; `cli.py:2949,3090,3345,3636`;
`tests/test_cli_flag_parity.py:97`) and the trust rules hold identically on all
four, enforced by one shared loader — not four copies. The flag accepts the
authored schema additively: a JSON **list** is operator policy, byte-unchanged; a
JSON **object** with the authored schema is loaded through the new trust path;
anything else is exit 2, fail-closed (same contract as a malformed operator file),
including a **future schema version** this engine does not know. Trust rules:
- calibration block absent/malformed/`verdict != "calibrated"` → every invariant
  from the artifact evaluates **UNVERIFIED** with the named cause
  `AUTHORED_INVARIANT_UNCALIBRATED`;
- digest mismatch (the policy set was edited after calibration) → **UNVERIFIED**
  with the named cause `AUTHORED_INVARIANT_ALTERED`;
- a well-formed calibrated artifact → enforced exactly like operator policy.
In all three cases: never FAIL from an untrusted authored invariant, never a
silent PASS, never a silent skip.

**M6 — The provenance boundary is amended deliberately, never weakened.**
The new producer is admitted by name into
`test_no_invariant_is_ever_sourced_from_a_trace` (`tests/test_invariants.py:55-114`),
exactly as `resolve_library_entry` was, plus a new pin: **authored policy comes
from the author command's output, never from a trace** — the control trace is
calibration evidence only. The zero-LLM AST guard over `src/belay/verify/`
(`test_verify_zero_llm.py`) stays green: the author is a subprocess seam; the
engine never calls a model.

**M7 — A reference `claude -p` author ships, and the live proof is manual.**
`python -m belay.authoring.reference_author --model <full-id>` implements the
protocol by shelling out to `claude -p` with the proven BYOK shape: `--tools ""`
**and** `--strict-mcp-config` (R6/R7 by construction), `ANTHROPIC_API_KEY` /
`ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` scrubbed **by absence, never `""`**,
no SDK import, stdlib only, full model id never an alias. All tests are offline
through the injectable runner seam. The live run — infer with the reference author
on the launch demo's task spec, calibrated against the committed launch capture,
then verifying the capture with the emitted artifact (expect no FAIL) — is
`manual`-marked, recorded verbatim, and read as **"the path works at n=1"**, never
as a quality claim.

**M8 — Corpus compounding: per-authored-invariant fixture cases.**
Each authored invariant that survives calibration is proven to fire: a
corrupt-success fixture (house pattern: hand-built traces via `TraceWriter` over
real snapshots, cheat servers in `tests/fixtures/`, cf.
`tests/test_invariant_library_e2e.py`) banks via real `add_case` and recomputes
**MATCH** through `corpus run`. A deliberately broken rule flips **REGRESSION**.
Recompute uses the case's **stored** invariants and never re-runs the author (the
`invariant-library` staleness rule, `docs/STATUS.md:165-166`).

### Should-have

- `--json` on `infer` reporting candidates, rejections and their named causes, and
  the artifact path.
- Dropped-candidate reporting on the text surface: every rejected candidate and why
  (unknown rule, calibration failure), so the operator can fix the task spec or the
  control.

### Nice-to-have

- A re-calibration command for a hand-edited artifact (so editing is not a dead
  end). Deferred unless cheap; the documented remedy is re-running `infer`.
- Per-invariant calibration digests instead of one digest over the policy set.

## Technical Considerations

- **The seam exists and is proven.** A3's `SubprocessAuthor`
  (`src/belay/verify/author.py`: "shelling out to a user-supplied command — BYOK by
  construction") and `ClaudeCliModel`
  (`eval/minting_driver/clients/claude_cli_client.py`; injectable `runner=` seam,
  offline tests, env scrub absent-never-`""`) are the two patterns this unit
  composes. The reference author is a product-surface sibling of the eval client,
  not an import of it (`eval/` is explicitly "NOT a product surface").
- **A1 is evaluated on the replayed delta and workspace**
  (`src/belay/verify/turn.py:494-498`: `content_roots(records, manifest_dir,
  reply.workspace)` then `evaluate_invariant(inv, reply.delta, n, roots=roots)`),
  which is why calibration must replay the control rather than read recorded facts,
  and why `infer` is a **replay-bearing surface** — the flag-parity fact table
  (`tests/test_cli_flag_parity.py:57-134`) gains the declared rows for the flags it
  shares with `verify`.
- **Rules are admitted through three sets, not one.** A new authored rule type is
  not needed for the first slice: the existing vocabulary (`read-only`,
  `no-assertion-weakening`, `no-create`, `no-delete`) is what the author proposes.
  If a future slice adds an authored-only rule, it joins `_KNOWN_RULES` plus
  exactly one grounding set (`invariants.py:102-128`) with a dispatch branch in
  `evaluate_invariant` — out of scope here.
- **New named causes are closed-vocabulary string constants**
  (`invariants.py:130-147`): `AUTHORED_INVARIANT_UNCALIBRATED` and
  `AUTHORED_INVARIANT_ALTERED` are verdict causes (stamped into
  `Verdict.expected["cause"]`, bucketed by `phase0 report`); `CALIBRATION_FAILED`,
  `AUTHOR_FAILED`, `AUTHOR_OUTPUT_UNPARSEABLE`, `UNKNOWN_RULE` are infer-side
  rejection causes, not verdicts.
- **`Invariant` gains one additive field** (e.g. `untrusted_cause: str | None =
  None`); when set, evaluation short-circuits to UNVERIFIED with that cause. All
  existing producers leave it unset — operator files, defaults, and library
  entries are byte-unchanged.
- **Placement.** Artifact schema + loader + trust check live in the verify package
  (so the provenance guard sees the new producer); the author protocol, the infer
  orchestration, and the reference author live in a new `src/belay/authoring/`
  package. Dependency direction: `authoring → verify`, never the reverse.
- **Zero new runtime dependencies.** stdlib only (`subprocess`, `json`,
  `hashlib`); the reference author requires the operator's `claude` binary at
  runtime, never in CI.

## Risks & Open Questions

- **R-a — the control launders a bad invariant.** Calibration is only as good as
  the control; a control that itself violates the policy would reject a correct
  invariant, and a control that is too small would accept a broad one. Mitigation:
  the control's hash and turn count are recorded in the artifact, the honest limit
  is stated on every surface, and Goal 1's corrupt-fixture proof is the other half
  (an invariant that never fires is caught by the fixture requirement, not by
  calibration). **Not solved by this unit: choosing the control.** Named, not
  papered over.
- **R-b — dead teeth.** An authored invariant that abstains everywhere passes
  calibration trivially. Mitigation: M8 requires every authored invariant to fire
  on its corrupt fixture; the suite fails otherwise. (This is the
  `invariant-library` "no dead entries" rule, applied to authored invariants.)
- **R-c — the artifact is a second policy format.** Mitigated by shape dispatch on
  the existing `--invariants` (no new flag, no new surface), fail-closed
  unknown-schema handling, and a test that operator files are byte-unchanged.
- **R-d — the authoring path drifts into a judge.** The author writes policy;
  execution decides. The verdict contract is untouched (no new status, A1's
  PASS/FAIL/UNVERIFIED semantics unchanged), and the tamper/trust rules only ever
  *lower* an authored verdict to UNVERIFIED — never raise it.
- **R-e — model dependence.** The live path needs the operator's model. The engine
  and all tests are dark without an author; `infer` without `--author` exits 2 with
  a named cause, never a fallback.
- **R-f — the task spec is untrusted input to a policy-writing model.** Prompt
  injection in a task spec could try to induce an over-broad invariant. The author
  has no tools and no network beyond the model call, the output is validated and
  calibrated, and the artifact is reviewed — but the residual is real and is
  **review, not proof**: calibration bounds over-firing on one control, it does not
  prove intent. Tested path: a hostile task spec inducing a broad candidate is
  rejected by calibration (M3); the artifact's provenance makes the author's
  identity and the control visible to the reviewer.
- **R-g — this is roadmap-push, not demand-pull.** No external user has asked for
  the authoring path; the Phase-2 PRDs record the demand-pull criterion as not met
  (`approval-gate/prd.md:38-39`). It is built because R3 is High/High and
  ROADMAP:308 commits to *"a real experiment, not an assumption"* — and the honest
  cost is bounded: one subcommand, one artifact format, dark by default, no public
  claim changes. If the experiment's live run shows the model cannot produce
  calibratable invariants, that is a **result**, recorded as one, not a failure to
  hide.
- **Open —** should `--control` accept a banked corpus case (clean, expected PASS)
  in addition to a raw trace? Should the digest be per-invariant? Does the
  reference author belong in the wheel or under `scripts/`? Resolve in the plan,
  not silently.

## Adoption & Docs

The unit is dark by default and changes no public claim. What a self-hoster sees:
a `belay invariant infer` quickstart in the README/docs (task spec + author command
+ control → review → `--invariants`), and the `AUTHORED_INVARIANT_*` causes
documented beside the other UNVERIFIED causes. The Phase-2 success metric this
serves — *"median invariants hand-authored per repo trending toward zero"*
(`docs/ROADMAP.md:315`) — is **not measurable from this unit alone**; this unit
makes the capability exist and records one live run. Adoption evidence accrues at
the Phase-2 gate (external self-hosters), and no number moves here.

## Out of Scope

- **The authoring UI and per-repo library management** — the other nouns of the
  deferral (`invariant-library/prd.md:151-152`). This unit tests the
  inferred-from-task-spec path only.
- **A3 follow-ons** — the WARN vocabulary and the caller-supplied-workspace
  short-circuit (`CAPABILITY_ROADMAP.md:853-854`) are separate units. A3 is
  untouched.
- **Any live-model CI test.** The live run is `manual`-marked (the
  `subscription-model-client` precedent).
- **Annotation inference** (shipped in C5), **the library** (shipped), and
  **hand-authoring** (`--invariants file`, shipped) — this unit adds the fourth
  candidate answer, it does not replace the others.
- **Any new verdict axis, status, or invariant default; any change to
  `read-only` / `no-assertion-weakening` scope semantics.**
- **No published number moves.** `11/60 = 18.3%`, `precision 0.00`, `1/15`,
  `4/16`, `recall 0.00` stand unedited.

## Aspect Decomposition

1. **`authoring-protocol`** — the infer subcommand, the author subprocess seam,
   candidate validation, calibration against the control, artifact emission.
2. **`artifact-trust`** — the artifact schema, the verify-side loader, the
   trust/degradation rules, the named causes, the provenance guard amendment.
3. **`reference-author`** — the `claude -p` reference author (argv/env guarantees,
   offline tests) and the manual live smoke against the launch capture.
4. **`corpus-fixtures`** — per-authored-invariant corrupt-success fixtures, banked
   `add_case` round trips, MATCH recompute, the regression simulation.

Sequencing: `artifact-trust` and `authoring-protocol` are the spine and can land in
either order (the loader's schema is the interface both need); `reference-author`
depends on the protocol; `corpus-fixtures` depends on the protocol + trust.