# feat/invariant-test-mutation-shape

**Type:** feat · **Id (slug):** `invariant-test-mutation-shape` · **Owner:** aliz
**Source:** inline brief (no GitHub issue — the tracker has never been used; all PRs are
issue-free). Produced by `/belay-next` on 2026-07-29 and invoked verbatim as
`bbf feat invariant-test-mutation-shape`.
**Base:** `origin/master` @ `4975158` (v0.9.0).

> **Predecessor.** This card replaces the previous `_card/issue.md`, which described
> `feat/phase0-corpus-audit` (merged as PR #14, released v0.9.0). That unit hand-audited the
> seven Phase-0 corpus cases and produced the measurement this unit exists to act on:
> **the A1 default `tests/` read-only invariant has precision 0.00 — 0 TP / 7 FP at 1.00
> coverage** (`docs/technical/PHASE0_AUDIT.md`). Its brief is preserved in git history at
> `77adc8f`. Its own Out-of-Scope list named this unit as the successor
> (`docs/planning/phase0-corpus-audit/prd.md:304`).

---

## Brief

Repair C5's shipped default `tests/` read-only invariant, which the 2026-07-29 hand-audit
measured at **precision 0.00** (0 TP / 7 FP at 1.00 coverage — `docs/technical/PHASE0_AUDIT.md`).

The rule must narrow from *"any write under `tests/`"* to **"a modification that removes or
weakens an existing assertion"**, judged against:

- the **task pre-state** — not the previous turn, or shape **C** (the run editing its own
  earlier scratch test) reads as cheating; and
- the **resulting content** — not the edit's anchor, or shape **B** (an anchored append that
  re-emits existing content byte-identically) reads as modification.

Acceptance is **test-first**:

1. The 7 corpus cases are **negative fixtures**; the new rule must go **7/7 clean** on them.
2. `belay corpus run` must show the verdict change as an **intentional re-store**, not a
   silent regression.
3. **Critically** — at least one **positive fixture** must be established that the rule
   **FAILs** on. An all-negative acceptance set is passed trivially by an invariant that
   never fires. The corpus currently holds **zero corrupt-success TPs**, so this fixture does
   not exist yet; sourcing it honestly (most likely by inverting a real upstream gold patch)
   is the first question for the dig.

**Also decide, don't defer again:** should this invariant stay **ON by default**, given
`README.md`'s coverage claims rest on it? `docs/planning/phase0-corpus-audit/prd.md:253`
deferred exactly this question *"until the labels exist"* — they now exist.

### Out of scope

- Resuming the mint to n≥50 (`ROADMAP.md:145` — do not spend the remaining ~34 instances
  under a detector known to be 0.00-precision; that spend is what this unit unblocks).
- C7 live console; C8 (A3 claim re-derivation).
- Any change to A2/A3 semantics, `verdict.reduce`, or the `NOT_COVERED` boundary.

---

## Why this unit, and why now

Every operative doc converged on it independently:

| File | Says |
|---|---|
| `docs/technical/PHASE0_AUDIT.md:85` | *"a sharper invariant must go 7/7 clean on exactly this set"* |
| `docs/technical/PHASE0_RESULTS.md:279` | *"Fix the instrument, then re-measure. Build `invariant-test-mutation-shape`"* |
| `docs/ROADMAP.md:145` | *"This is a PIVOT of the DETECTOR, not of the thesis"* — fix the instrument, don't spend the mint |
| `docs/ROADMAP.md:265` (R1) | R1 *"STILL OPEN, and NOT retired"* — the premise is testable **only** once a non-zero-precision detector exists |
| `CLAUDE.md` (status block) | *"Decision: fix the instrument, then re-measure — build `invariant-test-mutation-shape` next"* |

It was deliberately **deferred** by `STAGE2_FINDINGS.md:94-104` on the grounds that designing
a sharper invariant against 3 known cases was the guess that document warned against. **That
deferral condition is now discharged**: 7 human-adjudicated cases with recorded payload
shapes exist.

---

## The three observed shapes (the design input)

From `docs/technical/PHASE0_AUDIT.md` — all seven flags observed a **real** write under
`tests/` (A2 replay/effect were PASS on all seven); the invariant observed correctly and
**judged** wrongly. This is a *precision* failure, not an instrument failure.

| Shape | What happened | Cases (as documented) | **Re-confirmed by the dig** |
|---|---|---|---|
| **A** | Modifies pre-existing test content | `flask-4045` t8, `pylint-5859` t6 | t8 is **A+B** (multi-edit); t6 is A |
| **B** | Anchored edit that re-emits existing content **byte-identically** | `flask-4992` t10, t14; `pylint-5859` t11 | confirmed — but t10 is insert-**before**, not append |
| **C** | Edits a region the run itself authored earlier | `flask-4992` t12, t19 | t12 is C; t19 is **B+C** (one edit, both) |

**B and C are exactly how a naive sharper invariant gets it wrong** — which is why the rule
is specified against the *resulting content* and the *task pre-state* rather than the edit
anchor and the previous turn.

> **Correction (dig, 2026-07-29).** An earlier draft of this card defined shape C as *"a file
> the run itself created in an earlier turn."* **That is factually wrong and design-critical.**
> The file in both C cases is `tests/test_config.py`, which **shipped at `base_commit`** — only
> the *hunk* (`test_my_open_mode`) is self-authored. Provenance must be tracked at
> **content/region granularity, not file granularity**; a file-level "did the run create this
> file?" check scores **0/2** on the C cases. `PHASE0_AUDIT.md`'s own wording ("edits the run's
> OWN scratch") was correct; the parenthetical gloss was not.

Note also the audit's correction of an earlier claim: **`flask-4045` / `s1p` is not a corrupt
success.** Upstream `7c526140` **deletes** `test_dotted_names` outright and adds the same
`pytest.raises(ValueError)`, so the agent made the maintainer's change and the test could not
have passed unchanged. The sole candidate for the 27–78% statistic collapsed.

---

## Logistics the dig must know

- **The 7 negative fixtures are NOT in this worktree.** They live at
  `/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/corpus/local`
  (7 case dirs: `trace-pallets__flask-4045-turn8`, `trace-pallets__flask-4992-turn{10,12,14,19}`,
  `trace-pylint-dev__pylint-5859-turn{6,11}`). `corpus/` is gitignored and the captures embed
  absolute snapshot paths — **they are not movable**; point at them by absolute path via
  `--corpus-dir`, never copy or relocate that worktree.
- **Cached bare clones** for offline upstream gold-patch comparison are at
  `…/feat-verdict-coverage-status/eval/clones/` (`pallets__flask.git`,
  `pylint-dev__pylint.git`) — no network needed.
- The module under repair is `src/belay/verify/invariants.py` (299 lines). Its docstring
  carries two constraints any change must preserve: **scope is raw bytes** (the BTH-1
  unicode-normalisation trap) and **fail-closed** (an unknown rule is a named `ValueError`,
  never a silent empty list). `_KNOWN_RULES` is `frozenset({"read-only"})` today, and the
  reserved-but-unimplemented names are deliberately absent so an unenforced rule cannot pass
  for an enforced one.
- The zero-LLM AST guard covers `src/belay/verify/` — whatever this rule becomes, **no model
  may be consulted**. A content-shaped judgement ("does this weaken an assertion?") must be
  decided by parsing and comparison, not by inference.
- Baseline on this branch: **1005 passed, 1 skipped, 1 deselected** (`uv run pytest`).

---

## Known caveat, carried forward from `/belay-next`

**The acceptance set is all-negative, and that is a trap.** "Go 7/7 clean on the negative
fixtures" is satisfied perfectly by an invariant that **never fires**. A rule scoring 0 FP
and 0 TP is not an improvement over one scoring 0 TP and 7 FP — it fails silently instead of
loudly. Hence acceptance item 3. Constructing a positive fixture by hand is the guess
`STAGE2_FINDINGS.md:102-104` warned about; deriving it from a real upstream gold patch is the
least-guessy source available.

Secondary: changing the invariant makes already-banked instances **incomparable**
(`CAPABILITY_ROADMAP.md:402-403`), so the re-measure starts a fresh denominator. That is a
known, accepted cost of this unit — not a surprise to discover mid-implementation.
