# Aspect spec — `assertion-extraction`

**Parent PRD:** [`../prd.md`](../prd.md) · **Aspect 1 of 5** · **Depends on:** nothing (pure function)
**Blocks:** `weakening-decision`, `invariant-rule-wiring`

---

## Problem slice

To decide whether a test edit *removed or weakened an assertion*, Belay must first be able to say
**what assertions a file contains**. Nothing in the codebase can do this today — A1 matches path
prefixes on a delta whose content field is a sha256 digest (`invariants.py:204`,
`bth1.py:374`).

This aspect builds exactly one thing: a **pure, deterministic function from Python source bytes
to a set of assertion facts**. No filesystem, no trace, no verdict, no plumbing. It is the piece
where the hard idiom logic lives, and it is fully unit-testable in isolation against fixtures
copied verbatim from the audited cases.

**User outcome:** none directly — this aspect ships no behaviour change. It exists so that
`weakening-decision` has something to compare and so the idiom work can be driven by tests
before any wiring risk is taken on.

---

## In scope

### R1 · The extraction function

A function taking **source bytes** and returning either an **assertion set** or an explicit
**failure**, never silently conflating the two:

```
extract(source: bytes) -> AssertionSet | ExtractionFailure
```

**`ExtractionFailure` is load-bearing and must not be collapsed into an empty set.** A file with
no assertions and a file that could not be parsed are *completely different facts*: the first
supports a PASS, the second must become UNVERIFIED downstream (PRD M7/D4). Returning `set()` for
a syntax error would manufacture "no assertions were removed" out of "I could not read it" —
the exact false-PASS shape this project refuses.

### R2 · AST-based, not line-based

Extraction parses with the stdlib `ast` module. **This is the requirement, not an implementation
note** — it is what makes PRD requirement M3 satisfiable.

The `pylint-5859` t6 case is the proof: line-diffing reports

```
MessageTest(msg_id="fixme", line=2, args="CODETAG", col_offset=17)
```

as *removed* when the only change was **appending a trailing comma**. An AST node compared
structurally (or by `ast.unparse` normalisation) is identical across that edit. A line-based
extractor re-fails the exact case the audit called its closest call.

Formatting that must **not** affect the extracted fact: trailing commas, line wrapping,
whitespace, string quote style, and parenthesisation.

### R3 · Idioms recognised

Per PRD M4, recognition is **asymmetric** — a missed idiom is safe on a negative fixture and
fatal only on a positive. Recognise, in priority order:

| # | Idiom | Why | Fixture |
|---|---|---|---|
| **1** | **`fnmatch_lines` / `re_match_lines` glob patterns** — extract the **string literals inside the call**, not the call itself | **BINDING.** The only positive fixture in existence uses this. Without it the unit has no positive evidence at all | `pytest-5227` t11, t13 |
| 2 | bare `assert <expr>` | commonest form; the launch demo depends on it | t8, t14, launch demo |
| 3 | `pytest.raises(...)` (as call or context manager) | present in the corpus | t8 |
| 4 | `pytest.fail(...)` | present in the corpus | t12, t19 |
| 5 | unittest-style `self.assert*(...)` incl. `assertAddsMessages` / `assertNoMessages` | t6 and t11 must reach PASS | t6, t11 |

**Explicitly NOT recognised, and this is a decision not an omission:** arbitrary project helpers
such as `common_object_test`. PRD M4 forbids a hardcoded allowlist of helper names tuned until
the fixtures pass — *"an allowlist fitted to these cases IS the STAGE2 guess"*. If no principled
rule covers a helper, it is **not** an assertion. That is safe on every negative in the set
(nothing detected → nothing detected as removed), and the limit gets documented rather than
papered over.

### R4 · Assertion identity

Each extracted assertion carries enough to be compared across two versions of a file:

- a **normalised structural form** (the basis for set membership — R2's formatting-invariance
  lives here);
- its **kind** (which idiom produced it);
- for glob-pattern assertions, the **pattern string itself**, preserved verbatim, because
  `weakening-decision` needs to reason about subsumption over it rather than equality.

Identity must **not** include line numbers or column offsets — a test that moves down the file
because something was inserted above it has not changed.

### R5 · Determinism and zero dependencies

Same bytes in, same set out, always. Stdlib only (`ast`, and `tokenize`/`re` if needed);
`test_verify_zero_llm.py:41` guards `src/belay/verify/`, and the zero-runtime-dependency
guarantee is a headline property of the project.

**Naming hazard (PRD, Technical Considerations):** the zero-LLM guard bans first-party imports
whose dotted parts intersect `{llm, judge, model, models, inference, completion, prompt,
prompts}` (`test_verify_zero_llm.py:84-86, 114-121`). **Do not name this module
`verify/model*.py`, `inference.py`, or `judge.py`** — it would trip the ban with zero model
involvement.

### R6 · Encoding

Source arrives as **raw bytes** (consistent with the BTH-1 raw-bytes discipline the invariant
module already enforces — `invariants.py` docstring). A file that is not decodable as Python
source is an `ExtractionFailure`, never an empty set. Respect a PEP-263 coding declaration if
present; otherwise UTF-8, and failure on invalid UTF-8.

---

## Out of scope

- **Comparing two assertion sets** — that is `weakening-decision` (aspect 2).
- **Glob subsumption** — the *pattern string* is extracted here; deciding whether one pattern is
  looser than another is aspect 2.
- **Reading files, resolving snapshots, or touching the verdict** — aspect 3.
- **Non-Python test files.** Every fixture is Python. Other languages are a documented limit.
- **Semantic understanding of what an assertion checks.** This extracts *facts about assertions
  present*, not *what they mean*.

---

## Acceptance criteria

Test-first: each becomes a failing test before any implementation.

**Fixtures come from the audited cases verbatim.** Copy the real pre/post content out of the
bundled traces at
`/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/corpus/local/<case>/trace.jsonl`
into checked-in test fixtures. These are small source snippets, not run data — they are safe and
appropriate to commit, unlike the captures themselves.

| # | Criterion |
|---|---|
| **A1** | A file with **no assertions** returns an **empty set**; a file with a **syntax error** returns `ExtractionFailure`. The two are distinguishable by type, asserted explicitly. *(This is the aspect's most important test.)* |
| **A2** | **The t6 trailing-comma case.** Extracting `pylint-5859` t6's pre- and post-content yields sets where the `MessageTest(msg_id="fixme", line=2, args="CODETAG", col_offset=17)` assertion is **present in both and compares equal** — i.e. the trailing comma changed nothing. Fails on any line-based implementation. |
| **A3** | `fnmatch_lines(["pat1", "pat2"])` yields **two** glob-pattern assertions carrying `pat1` and `pat2` verbatim — not one assertion for the call. |
| **A4** | The `pytest-5227` t11 pre-content yields a glob-pattern assertion whose pattern is exactly `"test_log_cli_enabled_disabled.py* CRITICAL critical message logged by test"`, and the post-content one whose pattern is exactly `"*CRITICAL*critical message logged by test"`. |
| **A5** | Each of the five idioms in R3 is extracted from a fixture drawn from the case that motivates it. |
| **A6** | A call to an **unrecognised helper** (`common_object_test(...)`) yields **no** assertion, and this is asserted deliberately with a comment naming PRD M4 — so a later reader sees it as a decision, not a bug. |
| **A7** | **Formatting invariance:** the same assertion written with different line wrapping, quote style, trailing comma, and parenthesisation extracts to an equal fact. Table-driven. |
| **A8** | **Position invariance:** inserting an unrelated function *above* an assertion does not change the extracted fact for that assertion (no line numbers in identity). |
| **A9** | **Determinism:** extracting the same bytes twice yields equal sets; extraction has no dependence on dict/set iteration order in its output comparison. |
| **A10** | The module imports nothing outside the stdlib, and `test_verify_zero_llm.py` stays green with it in the guarded tree. |

---

## Dependencies and sequencing

**Depends on:** nothing. This is deliberately the first aspect — it carries the densest logic and
the least integration risk, so it can be driven entirely by unit tests before anything is wired.

**Blocks:** `weakening-decision` (needs the assertion type and the preserved pattern strings) and
transitively `invariant-rule-wiring`.

**Build it first.** If the idiom work turns out harder than expected, that is discovered here
against cheap unit tests rather than inside a replay integration.

---

## Open questions and risks

1. **Where does this module live?** `src/belay/verify/` is guarded by the zero-LLM AST test,
   which is *desirable* here (it should be guarded). Proposed: `src/belay/verify/assertions.py`.
   Confirm it does not collide with the public-API guard in
   `test_invariants.py::test_no_invariant_is_ever_sourced_from_a_trace` (`:55-123`) — that guard
   constrains `invariants.py`'s **`Invariant`-producing** callables, and this module produces no
   `Invariant`, so it should be unaffected. **Verify rather than assume.**
2. **`pytest.raises` as a context manager vs. a call.** `with pytest.raises(ValueError):` wraps a
   block; `pytest.raises(...)` as an expression does not. Are these the same fact? Proposed: the
   assertion is the `raises(...)` call with its arguments, and the block contents are not part of
   its identity. Unvalidated — t8 is the only fixture.
3. **Should a `match=` argument to `pytest.raises` be part of identity?** It genuinely narrows the
   assertion, so removing it *is* a weakening. Proposed: yes, include it. No fixture exercises
   this, so it is a reasoned guess and must be marked as one.
4. **Multiset or set?** Two byte-identical assertions in one file — does removing one count?
   Proposed: **multiset**, since deleting one of two duplicate checks removes real coverage. No
   fixture exercises it.
5. **`ast.unparse` requires Python 3.9+.** The project targets 3.10+ (`.python-version`,
   `pyproject.toml`), so this is fine — but confirm rather than assume, since it would be an
   unpleasant surprise late.
