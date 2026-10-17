# PRD: Authored Invariant Scope Shape

**Status:** draft, pending review gate
**Unit:** `feat/authored-invariant-scope-shape/aliz` (belay-next pick 2026-10-17)
**Date:** 2026-10-17
**Source:** `docs/planning/_card/issue.md` (inline brief) · `docs/planning/invariant-authoring/reference-author/live-run.md:53-74` (the finding) · `docs/ROADMAP.md:308,372` (R3) · `CLAUDE.md` (A1 is the load-bearing mechanism)
**Capability:** C5 follow-on — the A1 **policy-authoring** path (R3's third mitigation). Not a new C-id.
**Axes:** **A1 only, and only its policy-authoring acceptance.** No change to A1 evaluation semantics, no new axis/status/default. A3 untouched.

---

## 1. Problem Statement

### 1.1 The defect, measured

`belay invariant infer` writes a model-authored A1 policy artifact. The shipped reference
author emits **glob** scopes — `tests/**` — but A1 matches scopes as **raw byte-prefixes**
(delta rules; `src/belay/verify/invariants.py:619-624`) or **path-segment runs** (the
content rule; `_scope_segments`/`_under_segment_scope`, `invariants.py:910-940`). A glob
therefore **never matches a real path**: `fd.path.startswith(b"tests/**")` is false for
`tests/test_x.py`, and `_scope_segments(b"tests/**")` is `(b"tests", b"**")`, which no real
directory run equals.

The result is **dead teeth**: every authored invariant silently PASSes, comparing zero
files, and the operator sees a green run that enforced nothing.

The full chain, three links, none of which checks the shape:

1. **The prompt asks for a glob.** `src/belay/authoring/reference_author.py:99` —
   `'{"candidates": [{"scope": "<path glob>", ...`.
2. **Nothing validates the shape on the way in.** The author protocol only checks
   `isinstance(scope, str)` (`src/belay/authoring/protocol.py:272-279`); the artifact
   loader only checks `isinstance(scope, str)` then `os.fsencode` (`invariants.py:274-293`).
   `*` survives untouched.
3. **Calibration cannot see it.** `_calibrate` records a candidate as failed only when an
   A1 sub-verdict is `FAIL` (`src/belay/authoring/infer.py:366-371`); a dead scope PASSes
   trivially on the clean control, so it is a survivor.

This is a **measured** finding, not a hypothesis: the committed live-run artifact
(`docs/planning/invariant-authoring/reference-author/live-run/invariants.json`) carries
four invariants all scoped `"tests/**"`, and the frozen verify output shows their
sub-verdicts PASS with `files_compared: 0`
(`docs/planning/invariant-authoring/reference-author/live-run.md:53-74`).

### 1.2 Why it matters now

CLAUDE.md makes the stake explicit: *"User-declared invariants remain the load-bearing A1
mechanism; annotations are a free supplement."* The authored-policy path is R3's
zero-friction answer to *"who writes the invariant for a stranger's agent?"* — and it is
**High/High** (`docs/ROADMAP.md:372`; `docs/planning/invariant-authoring/prd.md:16`). A
silent no-op in that path is worse than no policy at all, because it **looks like
coverage** and the run reports success against nothing.

### 1.3 What this unit is NOT

It is not a verdict change and not a detector change. It does not touch how A1 matches a
scope, does not add an axis/status/default, does not move any published number, and is not
a gate run. It makes the authored path **honest about a scope it cannot interpret**.

---

## 2. Goals & Success Metrics

### 2.1 Goals

1. **No silently-dead authored invariant.** An authored invariant whose scope can never
   match a real path is surfaced as UNVERIFIED with a named cause — never a silent PASS.
2. **Make the author emit interpretable shapes.** The shipped reference author and the
   author payload state the scope contract (a path prefix, e.g. `tests/`), so the
   zero-friction path produces live policy.
3. **Change nothing else.** A1 evaluation semantics, the operator `--invariants` path, the
   digest/trust machinery, and every published number are untouched.

### 2.2 Decisions (owner, 2026-10-17)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Reject with a named cause** (do not normalize) | Matches the repo's fail-closed/named-cause discipline; normalization would *guess* which glob the author meant and could over-scope (a fabricated FAIL) or under-scope (dead teeth). Rejecting never guesses. |
| D2 | **Authored artifacts only** | Operator `--invariants` JSON lists are hand-written, trusted policy and stay byte-unchanged. |
| D3 | **Fix the author prompt** | The prompt is the root cause (`reference_author.py:99`); the guard is the backstop for any author, any model. |

### 2.3 Success metrics (deterministic, test-first, CI)

| # | Criterion |
|---|---|
| S1 | A calibrated authored artifact carrying a glob-shaped scope parses (schema/digest unchanged) but that invariant carries `untrusted_cause == AUTHORED_INVARIANT_SCOPE_UNINTERPRETABLE` and `evaluate_invariant` returns **UNVERIFIED** with that cause on every turn — never PASS, never FAIL. |
| S2 | Per-invariant, not all-or-nothing: a valid (prefix/segment) invariant in the **same** artifact stays trusted and enforces; artifact-level `UNCALIBRATED`/`ALTERED` still take precedence and are byte-unchanged. |
| S3 | The author protocol rejects a glob-shaped scope as `SCOPE_UNINTERPRETABLE` (rule/scope recovered for the operator); a valid scope is unaffected. |
| S4 | `belay invariant infer` with only glob candidates writes **no artifact** — the existing `NO_SURVIVING_CANDIDATES` outcome (`infer.py:210-215`), with the rejection cause visible in `--json`. |
| S5 | The operator path is byte-unchanged: `load_invariants` on a JSON **list** containing a glob scope still loads and evaluates exactly as today. |
| S6 | The reference author asks for a **path prefix** and does **not** ask for a "glob"; the author payload states the scope contract. |

### 2.4 Non-metrics

- **No published number moves.** `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
  `recall 0.00`, `3/93` stand unedited.
- **No precision/recall claim** about authored policy. The live path is model-driven and
  `manual`-marked; the CI proof is offline.

---

## 3. User Personas & Scenarios

- **The operator authoring policy.** Runs `belay invariant infer --author <cmd> …`. Today,
  if their author emits glob scopes, they get a green artifact that enforces nothing. After:
  glob candidates are rejected with a cause they can act on, and the shipped reference
  author emits a prefix that actually fires.
- **The operator reading a run.** Enforces an authored artifact via `belay verify
  --invariants <artifact>`. Today a glob-scoped invariant reads PASS. After: it reads
  UNVERIFIED with `authored-invariant-scope-uninterpretable`, so the coverage gap is
  legible rather than hidden.

---

## 4. Requirements

### Must-have

| # | Requirement |
|---|---|
| MH-1 | A shared predicate decides whether a scope string is interpretable — **glob metacharacters (`*`, `?`, `[`, `]`) are not**. Empty scope (whole tree) and plain prefixes remain interpretable. Lives in `verify/invariants.py` (the module `authoring/protocol.py` already imports from). |
| MH-2 | `parse_authored_invariants` tags each **glob-scoped** invariant with the new named cause `AUTHORED_INVARIANT_SCOPE_UNINTERPRETABLE = "authored-invariant-scope-uninterpretable"`, reusing the existing `untrusted_cause` field and `evaluate_invariant`'s short-circuit (`invariants.py:559-570`) — UNVERIFIED on every turn, never PASS/FAIL. **Per-invariant**; artifact-level causes take precedence; the scope **bytes are never mutated** (so the digest path is untouched). |
| MH-3 | `_validate_candidate` (`authoring/protocol.py:249-279`) returns a `Rejection(cause=SCOPE_UNINTERPRETABLE)` for a glob-shaped scope, recovering the attempted rule/scope for the operator. New constant `SCOPE_UNINTERPRETABLE` in the protocol's named-cause namespace (`protocol.py:50-54`). |
| MH-4 | The reference author's protocol text (`reference_author.py:99,102-103`) asks for a **path prefix** and does not say "glob". It must describe the shape **per rule class**, because it is rule-dependent: delta rules (`read-only`/`no-create`/`no-delete`) match a raw byte-prefix (a directory prefix ends with `/`, e.g. `tests/`, `src/`); the content rule (`no-assertion-weakening`) matches a path **segment** (a bare `tests` also works, and a trailing slash is normalised — `invariants.py:910-940`). Avoid giving one example that is wrong for half the vocabulary. |
| MH-5 | The author payload (`build_author_input`) states the same rule-dependent scope contract, so **any** BYOK author — not just the shipped reference — is told a scope is a path prefix, not a glob. |
| MH-6 | The operator path is unchanged: `load_invariants` on a JSON list is byte-unchanged, including a glob scope (accepted as today). Pinned by test. |

### Should-have

| # | Requirement |
|---|---|
| SH-1 | The `--json` surface of `invariant infer` renders rejected candidates (already does) so a glob rejection is operator-visible without extra work. |
| SH-2 | A `manual`-marked live proof that the reference author now emits an interpretable scope (mirroring `tests/test_reference_author_live.py`), never in CI. |

### Nice-to-have

| # | Requirement |
|---|---|
| NH-1 | The rejection message names the offending token (which metacharacter) — operator legibility. |

---

## 5. Technical Considerations

- **The chokepoint that must NOT change:** `_parse_invariant` (`invariants.py:267-293`) is
  shared by operator files and authored artifacts. The guard is applied in
  `parse_authored_invariants` (authored entry point) so operator loading is untouched (D2).
- **The digest is a landmine the chosen design avoids.** `canonical_policy_digest`
  (`invariants.py:296-323`) hashes `(rule, os.fsdecode(scope))`. Any **scope normalization**
  would make a stored digest mismatch → mass `AUTHORED_INVARIANT_ALTERED`. Choosing *reject*
  (D1) means the scope bytes are unchanged, so the digest path is provably unaffected — and
  that is an acceptance criterion, not a hope.
- **Emit/load symmetry.** `infer.py:217-219,264-267` constructs `Invariant(scope=os.fsencode(c.scope))`
  from survivors. With the protocol guard (MH-3), a glob never reaches a survivor, so no
  emit-side change is required and the artifact schema (`belay-authored-invariants/1`) is
  unchanged.
- **No new dependency; stdlib only.** No change to the provenance guard
  (`test_no_invariant_is_ever_sourced_from_a_trace`) — the four producers are unchanged.
- **Reuse for the RED tests:** `tests/test_authored_invariants.py:_artifact` (:48) +
  `_touch` (:89) for a unit-level fire; `tests/test_invariant_authoring_e2e.py`
  (`_infer_artifact` :204, `_weakening_fixture` :185) and `tests/test_invariant_weakening_rule.py`
  (`_pair`/`_weakening` :82,90) for the firing proof; `tests/test_invariant_authoring_protocol.py:281-389`
  for the protocol rejection shape.
- **Baseline:** `master @ 86d726a`; the suite is large and slow locally (the full run
  exceeds 15 min here). Phase 6 runs targeted modules + a full run before the PR.

---

## 6. Risks & Open Questions

| id | Risk | Prob | Impact | Mitigation |
|---|---|---|---|---|
| **R-A** | The reference author is model-driven; a live proof is stochastic. | High | Low | CI proof is the offline fake author + text/payload pins; the live proof is `manual`-marked, exactly as the prior reference-author units. |
| **R-B** | Over-broad rejection: a legitimate scope containing a literal `*`/`?`/`[` (a real filename with that character) is refused. | Low | Low | Accepted residual, documented; consistent with the repo's abstain-on-doubt direction. `?`/`[`/`]` chosen as metacharacters deliberately; a bare `*` as a real path component is vanishingly rare. |
| **R-C** | Behavior change on a **frozen** artifact: the committed live-run artifact (`tests/**`) now reads UNVERIFIED instead of PASS. | High | Low | The frozen artifact is **not rewritten**; its PASS was the defect symptom (`files_compared: 0`), and the new UNVERIFIED is the honest reading. Recorded in docs. No CI test asserts the live-run artifact's verdict (it is `manual`). |
| **R-D** | The digest/emit-consistency hazard (mass `AUTHORED_INVARIANT_ALTERED` if scopes were normalized). | — | High | Avoided by D1 (reject, never normalize); scope bytes untouched; pinned by a digest-stability test. |
| **R-E** | **The guard is narrow by design.** It rejects only glob metacharacters. A non-glob but non-matching scope — an absolute path, a path rooted elsewhere, a typo, a scope that names a file not a directory — is **still silently dead**. | High | Med | Accepted residual, named not hidden: this unit fixes the *measured* defect (the shipped author's glob) and stops silent no-ops for the glob class; it does **not** make every authored scope live. Stated in §7 and in the docs aspect so no reader over-reads the fix. |
| **R-F** | A committed test or ledger may pin the frozen live-run artifact's old all-PASS verdict, which the fix changes to UNVERIFIED. | Low | Med | Verify in aspect 1: grep the suite for any pin on the live-run artifact's verdict; the artifact is `manual`-marked, and the design expects none — if one is found it must be updated, not the artifact. |
| **R3** (roadmap) | Nobody authors the invariant (High/High). | — | — | This unit advances the authoring mitigation: the zero-friction path stops producing silent no-ops. |

### Open questions

- **OQ-1 — metacharacter set.** MH-1 uses `*`, `?`, `[`, `]`. Is a bare `**` (doublestar)
  worth a distinct message (`NH-1`)? Deferred to tech-plan.
- **OQ-2 — should the payload contract (MH-5) be a separate aspect from the prompt fix
  (MH-4)?** Proposed split below.

---

## 7. Out of Scope

- **Normalizing glob scopes** (rejected by D1).
- **Any change to A1 scope-matching semantics** (`invariants.py:619-624`, `:910-940`).
- **Guarding the operator `--invariants` path** (D2).
- **Catching a non-glob dead scope** (R-E) — an absolute path, a wrong root, a typo, or a
  file-vs-directory mismatch is not detected here.
- **Rewriting the frozen live-run artifacts** or the prior unit's finding.
- **The A3 WARN vocabulary** and the evaluator's caller-supplied-workspace short-circuit
  (named C8 follow-ons, unchanged).
- **The authoring UI / per-repo library management, live-model CI, per-invariant digests,
  artifact re-calibration** (named deferrals of `invariant-authoring`).
- **Any published number, axis, status, default, or the `--no-claim-axis` refutation.**

---

## 8. Proposed aspect decomposition

Sequenced; each buildable and testable by one agent, strict TDD.

| # | Aspect | Boundary | Grade | Depends on |
|---|---|---|---|---|
| 1 | `scope-guard` | The shared interpretability predicate (MH-1); the authored-artifact loader guard with the named cause and per-invariant semantics (MH-2); the author-protocol rejection (MH-3); the digest-stability and operator-path-unchanged pins (MH-6, R-D). | deterministic | — |
| 2 | `author-guidance` | The reference author prompt fix (MH-4) and the author-payload scope contract (MH-5), with text/payload pins. | deterministic | — |
| 3 | `firing-and-docs` | The no-regression **firing** proof: an authored prefix-scoped invariant still FIRES on a corrupt fixture whose delta touches the scoped path (and a clean control PASSes); plus the honest docs (README/CLAUDE/STATUS lines, the R-C note). | deterministic (+ `manual` live proof SH-2) | 1 |

---

## 9. Self-critique (prd-generator Workflow 1)

Scored across the dimensions; three gaps were folded back into the PRD above rather than
left as notes.

| Dimension | Rating | Note |
|---|---|---|
| Problem Definition | 🟢 | Measured and cited; three-link chain; two named code sites; a frozen artifact as evidence. |
| User Understanding | 🟡 | Personas are **inferred from the code path**, not from user research — a single-maintainer engine unit, so no customer discovery applies. Stated, not hidden. |
| Success Metrics | 🟢 | S1–S6 are deterministic and test-first; the stochastic live proof is explicitly non-CI. |
| Scope Clarity | 🟢 | D1–D3 are owner decisions with rationale; the out-of-scope list is explicit. |
| Edge Cases & Risks | 🟡 → fixed | **Rule-dependent scope shape** (MH-4/MH-5 amended: a delta rule wants `tests/`, the content rule wants a segment) and **non-glob dead scopes** (R-E added) were the two real gaps. |
| Stakeholder Alignment | 🟡 | The approver is the owner (this review gate); no external stakeholders. Fine for the repo, flagged. |
| Feasibility Signal | 🟢 | Phase-2 dig mapped the exact functions and named causes; the change is small and localized. |
| Go-to-Market | — | N/A: an internal engine/policy-path unit; no rollout surface. |

### Top gaps (ranked)

1. **Rule-dependent scope shape (🟡 → fixed).** The original MH-4 said "a path prefix,
   e.g. `tests/`", which is wrong for `no-assertion-weakening` (segment semantics).
   Amended to a per-rule-class contract so the author guidance can't teach a wrong shape.
2. **The guard's narrowness (🟡 → named as R-E).** Rejecting glob metacharacters does not
   make every authored scope live; a non-glob dead scope (absolute path, wrong root, typo)
   is out of scope. Named so the fix is not over-read.
3. **Blast radius on frozen artifacts (🟡 → R-F).** R-C notes the live-run artifact's PASS
   becomes UNVERIFIED; R-F adds the verification step (no committed test may pin the old
   verdict) so the change is proven inert to CI rather than assumed.

### The hard question I'd want answered before greenlighting

**After this unit, does a fresh `invariant infer` actually produce a *live* invariant — or
have we only converted a silent no-op into a *visible* UNVERIFIED with the same zero live
policy?** The guard makes the defect legible; the shipped reference author is fixed; but
the *outcome* (authored policy that fires) is only demonstrated for the reference author
under a `manual` live proof. That is the honest ceiling of this unit, and it is why the
`firing-and-docs` aspect pins that an authored prefix scope **FIRES** — the proof that the
authoring path can at last do the thing it claims.

