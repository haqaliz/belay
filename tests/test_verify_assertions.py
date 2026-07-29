"""Aspect 1 of `invariant-test-mutation-shape`: Python source bytes -> assertion facts.

The unit under test is a pure function. It reads no file, sees no trace, and computes no
verdict — it answers exactly one question, *"what assertions does this source contain?"*,
so that `weakening-decision` has two comparable sets and the idiom logic can be driven by
cheap unit tests before any replay wiring exists.

**The load-bearing test in this file is the first one.** A file with no assertions and a
file that could not be parsed are completely different facts: the first supports a PASS,
the second must become UNVERIFIED downstream. Returning `set()` for a syntax error would
manufacture *"no assertions were removed"* out of *"I could not read it"* — the exact
false-PASS shape this project exists to refuse. So they are distinguished **by type**, and
that distinction is asserted explicitly rather than left to a caller's care.

**The fixtures are real.** Everything under `tests/fixtures/assertions/` was copied out of
the audited mint captures (see the README there), not invented to be passed. That matters
most for `pylint_5859_t6_*`, where the only change between pre and post is a **trailing
comma** the audit called its closest call: a line-based extractor reports the
`MessageTest(...)` line as removed and re-fails the case, and an AST-based one does not.
That is why R2 makes "AST, not lines" a requirement rather than an implementation note.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from belay.verify.assertions import (
    KIND_ASSERT,
    KIND_EXPECTATION,
    KIND_FAIL,
    KIND_GLOB_PATTERN,
    KIND_RAISES,
    KIND_REGEX_PATTERN,
    KIND_UNITTEST,
    UNDECODABLE_SOURCE,
    UNPARSEABLE_SOURCE,
    Assertion,
    AssertionSet,
    ExtractionFailure,
    extract,
)

FIXTURES = Path(__file__).parent / "fixtures" / "assertions"

#: The one `MessageTest` that survives `pylint-5859` t6 unchanged except for a trailing
#: comma. Written as the NORMALISED form (`ast.unparse` emits single quotes), because the
#: whole point is that the source spelling is not the identity.
T6_MESSAGE_TEST = "MessageTest(msg_id='fixme', line=2, args='CODETAG', col_offset=17)"

#: `pytest-5227` turn 11's two glob patterns, verbatim from the capture. `weakening-decision`
#: has to reason about glob subsumption over these strings, so a single character lost here
#: silently spends the only real positive fixture the project has.
T11_PRE_PATTERN = "test_log_cli_enabled_disabled.py* CRITICAL critical message logged by test"
T11_POST_PATTERN = "*CRITICAL*critical message logged by test"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _ok(source: bytes) -> AssertionSet:
    """Extract, asserting success — so a regression to ExtractionFailure names itself."""
    result = extract(source)
    assert isinstance(result, AssertionSet), f"expected an AssertionSet, got {result!r}"
    return result


def _forms(result: AssertionSet, kind: str | None = None) -> list[str]:
    return [a.form for a in result if kind is None or a.kind == kind]


# ---------------------------------------------------------------------------
# A1 — the aspect's most important test
# ---------------------------------------------------------------------------


def test_no_assertions_and_unparseable_source_are_different_facts() -> None:
    """A1. `set()` and "I could not read it" must never be the same value.

    This is the whole reason `ExtractionFailure` exists as a type rather than as an empty
    result. Downstream, an empty set means *nothing was removed* (a PASS input) and a
    failure means *undecidable* (an UNVERIFIED input). Collapsing them manufactures a PASS
    out of an unreadable file, which is the false-PASS shape the project refuses.
    """
    empty = extract(b"def test_nothing():\n    helper(1)\n")
    broken = extract(b"def test_nothing(:\n    helper(1\n")

    # Distinguishable BY TYPE, not by inspecting a flag a caller might forget to check.
    assert isinstance(empty, AssertionSet)
    assert isinstance(broken, ExtractionFailure)
    assert not isinstance(broken, AssertionSet)

    assert len(empty) == 0
    assert list(empty) == []

    # And they do not compare equal, so `result == AssertionSet(())` cannot be true for a
    # failure however a caller phrases the check.
    assert empty != broken
    assert broken != AssertionSet(())

    # The failure names its cause from a closed vocabulary, so a caller can report WHY.
    assert broken.cause == UNPARSEABLE_SOURCE
    assert broken.detail


def test_a_file_full_of_real_calls_but_no_assertions_is_an_empty_set() -> None:
    """A1, on real content: `flask-4992` t19 asserts only through an unrecognised helper.

    So the honest answer is "no assertions detected here" — an empty set, which downstream
    reads as "nothing could have been removed". Not a failure, and not a guess.
    """
    result = _ok(_fixture("flask_4992_t19_post.py"))

    assert len(result) == 0


# ---------------------------------------------------------------------------
# A2 — the trailing comma, the audit's closest call
# ---------------------------------------------------------------------------


def test_pylint_5859_t6_trailing_comma_changes_nothing() -> None:
    """A2. The `MessageTest` that gained only a trailing comma is the SAME fact.

    A line diff of t6 reports
    `MessageTest(msg_id="fixme", line=2, args="CODETAG", col_offset=17)` as REMOVED,
    because the post version appends a comma to it. Nothing was removed: the expectation
    is identical and two more were added beside it. Any line-based implementation fails
    here, which is the point.
    """
    pre = _ok(_fixture("pylint_5859_t6_pre.py"))
    post = _ok(_fixture("pylint_5859_t6_post.py"))

    pre_hits = [a for a in pre if a.form == T6_MESSAGE_TEST]
    post_hits = [a for a in post if a.form == T6_MESSAGE_TEST]

    assert len(pre_hits) == 1, _forms(pre)
    assert len(post_hits) == 1, _forms(post)
    # Present in both AND compares equal — same kind, same enclosing function, same
    # ordinal. Equality is what `weakening-decision` pairs on, so this is the real claim.
    assert pre_hits[0] == post_hits[0]
    assert pre_hits[0] in post

    # The other two MessageTests are additions, and additions are never a weakening.
    added = {a.form for a in post if a.kind == KIND_EXPECTATION} - {
        a.form for a in pre if a.kind == KIND_EXPECTATION
    }
    assert len(added) == 2, added


# ---------------------------------------------------------------------------
# A3 / A4 — glob patterns, the only binding idiom
# ---------------------------------------------------------------------------


def test_fnmatch_lines_yields_one_assertion_per_pattern_not_one_for_the_call() -> None:
    """A3. Two patterns in, two glob-pattern facts out — never one fact for the call.

    `weakening-decision` reasons about glob subsumption over an individual pattern. A
    call-level fact would defeat that twice over: subsumption has nothing to run on, and a
    pure pattern ADDITION would read as a modification of the call.
    """
    source = b'def test_x():\n    result.stdout.fnmatch_lines(["pat1", "pat2"])\n'

    result = _ok(source)

    assert len(result) == 2, _forms(result)
    assert [a.kind for a in result] == [KIND_GLOB_PATTERN, KIND_GLOB_PATTERN]
    assert [a.pattern for a in result] == ["pat1", "pat2"]
    # Explicitly NOT a fact for the call itself.
    call_form = 'result.stdout.fnmatch_lines(["pat1", "pat2"])'
    assert all(a.form != call_form for a in result), _forms(result)


def test_pytest_5227_t11_patterns_are_preserved_verbatim() -> None:
    """A4. The real weakening's patterns survive extraction byte-for-byte.

    These two strings ARE the project's only real positive evidence. Extraction must hand
    them on unaltered — no strip, no normalisation, no unescaping — because the decision
    that turn 11 loosened the pattern is a claim about exactly these characters.
    """
    pre = _ok(_fixture("pytest_5227_t11_pre.py"))
    post = _ok(_fixture("pytest_5227_t11_post.py"))

    pre_patterns = [a.pattern for a in pre if a.kind == KIND_GLOB_PATTERN]
    post_patterns = [a.pattern for a in post if a.kind == KIND_GLOB_PATTERN]

    assert T11_PRE_PATTERN in pre_patterns, pre_patterns
    assert T11_POST_PATTERN in post_patterns, post_patterns
    # The pre pattern is GONE from the post file and vice versa — that is the change
    # `weakening-decision` has to adjudicate, and extraction must make it visible.
    assert T11_PRE_PATTERN not in post_patterns
    assert T11_POST_PATTERN not in pre_patterns

    # They pair: same enclosing function, same kind, same ordinal within it.
    (pre_hit,) = [a for a in pre if a.pattern == T11_PRE_PATTERN]
    (post_hit,) = [a for a in post if a.pattern == T11_POST_PATTERN]
    assert pre_hit.function == post_hit.function == "test_log_cli_enabled_disabled"
    assert pre_hit.ordinal == post_hit.ordinal


def test_assertions_inside_a_generated_source_string_are_not_this_module_s_assertions() -> None:
    """`testdir.makepyfile(\"\"\"... assert ...\"\"\")` is a string literal, not code here.

    Real pytest test files embed whole other test modules as strings. An extractor that
    reached into them would invent assertions that this file does not make, and every one
    of those would then be "removable" by an edit that only reformats the literal.
    """
    result = _ok(_fixture("pytest_5227_t11_pre.py"))

    embedded = "plugin.log_cli_handler.level == logging.NOTSET"
    assert all(embedded not in a.form for a in result), _forms(result)


# ---------------------------------------------------------------------------
# A5 — every idiom in R3, from the case that motivates it
# ---------------------------------------------------------------------------


def test_bare_assert_is_extracted_from_flask_4045_t8() -> None:
    """A5, idiom 2. The three bare `assert`s in `test_dotted_names`, by their test expression.

    The assert's optional MESSAGE is deliberately not part of the fact: dropping
    `assert x, "why"` to `assert x` narrows nothing about what the assertion accepts, so
    calling it a change would be a false alarm by construction.
    """
    result = _ok(_fixture("flask_4045_t8_pre.py"))

    asserts = [a for a in result if a.kind == KIND_ASSERT]
    assert [a.form for a in asserts] == [
        "client.get('/fe').data.strip() == b'/be'",
        "client.get('/fe2').data.strip() == b'/fe'",
        "client.get('/be').data.strip() == b'/fe'",
    ]
    assert {a.function for a in asserts} == {"test_dotted_names"}
    assert [a.ordinal for a in asserts] == [0, 1, 2]

    with_message = _ok(b"def test_x():\n    assert y, 'why this matters'\n")
    assert [a.form for a in with_message] == ["y"]


def test_pytest_raises_is_extracted_from_flask_4045_t8_including_its_match() -> None:
    """A5, idiom 3 — and the answers to open questions 2 and 3, asserted rather than prosed.

    Open question 2: a `with pytest.raises(...)` block and a bare `pytest.raises(...)`
    expression are the SAME fact — the assertion is the call and its arguments; the block's
    contents are not part of its identity. (The two spellings differ only in enclosing
    statement, and this module walks calls.)

    Open question 3: `match=` IS part of identity. It genuinely narrows the assertion, so
    dropping it grows the set of exceptions accepted — a weakening, and one that would be
    invisible if identity stopped at the exception type. No fixture exercises the removal,
    so this is a reasoned choice, recorded as one.
    """
    result = _ok(_fixture("flask_4045_t8_post.py"))

    raises = [a for a in result if a.kind == KIND_RAISES]
    assert [a.form for a in raises] == [
        "pytest.raises(ValueError, match='Blueprint name should not contain dots')"
    ]
    assert raises[0].function == "test_dotted_name_raises"

    # Same fact whether it is a `with` item or a bare expression.
    as_ctx = _ok(b"def test_x():\n    with pytest.raises(ValueError):\n        boom()\n")
    as_call = _ok(b"def test_x():\n    pytest.raises(ValueError, boom)\n")
    assert [a.form for a in as_ctx] == ["pytest.raises(ValueError)"]
    assert as_ctx != as_call  # arguments differ, so the facts differ

    # `match=` narrows, so it is part of the fact and its removal is visible.
    narrow = _ok(b"def test_x():\n    with pytest.raises(V, match='boom'):\n        f()\n")
    wide = _ok(b"def test_x():\n    with pytest.raises(V):\n        f()\n")
    assert narrow != wide


def test_pytest_fail_is_extracted_from_flask_4992_t12() -> None:
    """A5, idiom 4. `pytest.fail(...)` — an unconditional failure is an assertion."""
    result = _ok(_fixture("flask_4992_t12_post.py"))

    fails = [a for a in result if a.kind == KIND_FAIL]
    assert len(fails) == 2, _forms(result)
    assert {a.function for a in fails} == {"test_my_open_mode"}
    assert "pytest.fail('B WORKED')" in [a.form for a in fails]


def test_unittest_style_assert_methods_are_extracted_from_pylint_5859() -> None:
    """A5, idiom 5. `self.assert*` by NAMING CONVENTION, not by a list of method names.

    The rule is *"a call to an attribute whose name starts with `assert`"*. That is what
    reaches `assertAddsMessages` and `assertNoMessages` without an allowlist naming them —
    PRD M4 forbids a helper allowlist tuned until the fixtures pass, and a convention every
    unittest assertion has followed since 2001 is not a fit to these cases.
    """
    result = _ok(_fixture("pylint_5859_t6_pre.py"))

    unittest_calls = [a for a in result if a.kind == KIND_UNITTEST]
    assert len(unittest_calls) == 1, _forms(result)
    assert unittest_calls[0].function == "TestFixme.test_other_present_codetag"
    assert unittest_calls[0].form.startswith("self.assertAddsMessages(")

    # The zero-argument variant is still an assertion.
    no_messages = _ok(
        b"class T:\n"
        b"    def test_x(self):\n"
        b"        with self.assertNoMessages():\n"
        b"            self.checker.process_tokens(code)\n"
    )
    assert [a.form for a in no_messages] == ["self.assertNoMessages()"]
    assert [a.kind for a in no_messages] == [KIND_UNITTEST]


def test_re_match_lines_is_extracted_but_kept_distinct_from_glob() -> None:
    """A5, idiom 1's regex sibling: extracted, and NOT labelled a glob.

    pytest's `re_match_lines` takes regexes, and regex containment is a materially harder
    decision than glob containment. Silently treating one as the other would let
    `weakening-decision` run a glob DFA over a regex and answer confidently in the wrong
    language. Extracting it under its own kind is what lets that aspect abstain honestly.
    """
    source = b'def test_x():\n    result.stdout.re_match_lines([r"a.*b"])\n'

    result = _ok(source)

    assert [a.kind for a in result] == [KIND_REGEX_PATTERN]
    assert [a.pattern for a in result] == ["a.*b"]


def test_negative_line_matchers_are_deliberately_not_recognised() -> None:
    """`no_fnmatch_line` asserts a pattern does NOT appear — subsumption inverts on it.

    Loosening a positive matcher grows what it accepts; loosening a negative one SHRINKS
    what it forbids, so the same comparison points the other way. No fixture exercises it,
    so recognising it would be a guess wearing the same kind label as real evidence.
    Deliberately out, and asserted so it reads as a decision.
    """
    result = _ok(b'def test_x():\n    result.stdout.no_fnmatch_line("*boom*")\n')

    assert len(result) == 0, _forms(result)


# ---------------------------------------------------------------------------
# A6 — the helper this module refuses to recognise
# ---------------------------------------------------------------------------


def test_an_unrecognised_project_helper_yields_no_assertion() -> None:
    """A6. `common_object_test(...)` really asserts, and is deliberately NOT an assertion here.

    THIS IS A DECISION, NOT A BUG (PRD M4). Recognising it needs either a general heuristic
    over arbitrary function calls or a name allowlist, and *"an allowlist fitted to these
    cases IS the STAGE2 guess"* the PRD forbids. Missing an idiom is asymmetric: on a
    negative fixture nothing is detected, so nothing is detected as removed, so the rule
    does not fire — safe. The cost is real and is documented rather than papered over.
    """
    result = _ok(
        b"def test_config_from_file():\n"
        b"    app = flask.Flask(__name__)\n"
        b"    common_object_test(app)\n"
    )

    assert len(result) == 0, _forms(result)


# ---------------------------------------------------------------------------
# A7 / A8 — the invariances that make the fact a FACT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "what, left, right",
    [
        (
            "parenthesisation",
            b"def test_x():\n    assert x == 1\n",
            b"def test_x():\n    assert (x == 1)\n",
        ),
        (
            "whitespace",
            b"def test_x():\n    assert x == 1\n",
            b"def test_x():\n    assert  x==1\n",
        ),
        (
            "line wrapping",
            b"def test_x():\n    assert x == 1 and y == 2\n",
            b"def test_x():\n    assert (\n        x == 1\n        and y == 2\n    )\n",
        ),
        (
            "quote style",
            b'def test_x():\n    assert x == "a"\n',
            b"def test_x():\n    assert x == 'a'\n",
        ),
        (
            "trailing comma",
            b"class T:\n    def test_x(self):\n        self.assertAddsMessages(M(1))\n",
            b"class T:\n    def test_x(self):\n        self.assertAddsMessages(M(1),)\n",
        ),
        (
            "wrapped call with trailing comma",
            b'def test_x():\n    out.fnmatch_lines(["a*", "b*"])\n',
            b'def test_x():\n    out.fnmatch_lines(\n        [\n            "a*",\n            "b*",\n        ]\n    )\n',
        ),
        (
            "glob pattern quote style",
            b'def test_x():\n    out.fnmatch_lines(["a*b"])\n',
            b"def test_x():\n    out.fnmatch_lines(['a*b'])\n",
        ),
    ],
)
def test_formatting_does_not_change_the_extracted_fact(
    what: str, left: bytes, right: bytes
) -> None:
    """A7. Reformatting is not an edit to an assertion, and must not look like one.

    Every entry here is a way a real formatter (or a real agent) rewrites a line without
    touching what it checks. If any of them changed the fact, the rule would fire on a
    `black` run — which is the over-firing this whole unit exists to end.
    """
    assert _ok(left) == _ok(right), what


def test_inserting_a_function_above_does_not_change_the_fact() -> None:
    """A8. Identity carries no line numbers and no column offsets.

    A test that moves down the file because something was inserted above it has not
    changed. Encoding position into identity would make every insert look like a
    wholesale removal-and-re-add of everything below it.
    """
    original = _fixture("flask_4045_t8_pre.py")
    shifted = b"def helper_added_above():\n    return 1\n\n\n" + original

    before = _ok(original)
    after = _ok(shifted)

    assert before == after
    assert len(before) > 0, "vacuous otherwise — the fixture must contain assertions"


# ---------------------------------------------------------------------------
# A9 — determinism
# ---------------------------------------------------------------------------


def test_extraction_is_deterministic_and_order_independent() -> None:
    """A9. Same bytes in, same facts out — and equality does not depend on ordering.

    Two properties, because they fail differently. The first is that nothing in extraction
    consults a hash seed, a set iteration, or the clock. The second is that the RESULT
    compares by membership, so a future change to walk order cannot flip a downstream
    verdict from PASS to FAIL without any assertion having moved.
    """
    source = _fixture("pytest_5227_t11_pre.py")

    first = _ok(source)
    second = _ok(source)

    assert first == second
    assert tuple(first) == tuple(second), "walk order must be stable, not merely equal"
    assert AssertionSet(tuple(reversed(tuple(first)))) == first


def test_duplicate_assertions_are_kept_apart_so_removing_one_is_visible() -> None:
    """Open question 4, answered: the result behaves as a MULTISET.

    Two byte-identical assertions in one function are two checks, and deleting one removes
    real coverage. Ordinals make them distinct facts, so a set of facts is a multiset of
    assertions without needing a separate counting type.
    """
    twice = _ok(b"def test_x():\n    assert f()\n    assert f()\n")
    once = _ok(b"def test_x():\n    assert f()\n")

    assert len(twice) == 2
    assert len(once) == 1
    assert twice != once
    assert [a.ordinal for a in twice] == [0, 1]


def test_the_same_assertion_in_two_functions_is_two_facts() -> None:
    """Identity is scoped to the enclosing function, so unrelated tests never pair up.

    Without this, deleting `assert ok()` from `test_a` would be masked by an identical
    `assert ok()` surviving in `test_b`, which is a false PASS on a genuine removal.
    """
    result = _ok(
        b"def test_a():\n    assert ok()\n\n\ndef test_b():\n    assert ok()\n"
    )

    assert len(result) == 2
    assert {a.function for a in result} == {"test_a", "test_b"}


# ---------------------------------------------------------------------------
# R6 — encoding, and the raw-bytes discipline
# ---------------------------------------------------------------------------


def test_a_pep263_coding_declaration_is_respected() -> None:
    """R6. The file says how to decode it, and extraction believes the file, not a default."""
    source = "# -*- coding: latin-1 -*-\ndef test_x():\n    assert x == 'caf\xe9'\n".encode(
        "latin-1"
    )

    result = _ok(source)

    assert [a.form for a in result] == ["x == 'caf\xe9'"]


def test_undecodable_bytes_are_a_failure_not_an_empty_set() -> None:
    """R6 + A1. Invalid UTF-8 with no coding declaration is UNDECODABLE, never "no assertions"."""
    broken = extract(b"def test_x():\n    assert x == '\xff\xfe'\n")

    assert isinstance(broken, ExtractionFailure)
    assert broken.cause == UNDECODABLE_SOURCE


def test_an_unknown_coding_declaration_is_a_failure() -> None:
    """A file that declares an encoding Python does not have cannot be read — say so."""
    broken = extract(b"# -*- coding: not-a-real-encoding -*-\nassert x\n")

    assert isinstance(broken, ExtractionFailure)
    assert broken.cause == UNDECODABLE_SOURCE


def test_embedded_null_bytes_are_a_failure_not_a_crash() -> None:
    """`ast.parse` raises ValueError, not SyntaxError, on a NUL — both must land on failure."""
    broken = extract(b"def test_x():\n    assert x\n\x00")

    assert isinstance(broken, ExtractionFailure)
    assert broken.cause == UNPARSEABLE_SOURCE


def test_str_source_is_rejected_rather_than_silently_decoded() -> None:
    """The input is RAW BYTES, mirroring BTH-1 — accepting `str` would hide a decode.

    BTH-1 goes to lengths to keep paths and content as bytes because decoding is where the
    unicode-normalisation traps live. A function that quietly accepted `str` would let a
    caller decode with the wrong codec upstream and never learn it had.
    """
    with pytest.raises(TypeError):
        extract("def test_x():\n    assert x\n")  # type: ignore[arg-type]


def test_an_empty_file_has_no_assertions_and_is_not_a_failure() -> None:
    """Zero bytes parse fine and contain nothing — an empty set, not an error."""
    result = extract(b"")

    assert isinstance(result, AssertionSet)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# A10 — stdlib only, and the guards this module must not trip
# ---------------------------------------------------------------------------


def test_the_module_imports_only_the_standard_library() -> None:
    """A10. Zero runtime dependencies is a headline property; this module must not spend it.

    Read with `ast` rather than by importing, for the same reason `test_verify_zero_llm`
    does: importing reports on the venv, not on the source that ships.
    """
    module = (
        Path(__file__).parent.parent / "src" / "belay" / "verify" / "assertions.py"
    )
    tree = ast.parse(module.read_bytes(), filename=str(module))

    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    allowed = {"__future__", "ast", "dataclasses", "io", "tokenize", "typing", "collections"}
    assert roots <= allowed, f"non-stdlib or unexpected imports: {roots - allowed}"


def test_extraction_produces_no_invariant_and_so_leaves_the_provenance_guard_alone() -> None:
    """The A1 provenance boundary is untouched: this module is not a policy source.

    `test_invariants.py::test_no_invariant_is_ever_sourced_from_a_trace` pins that exactly
    two public callables PRODUCE an `Invariant`, keyed on return type. Extraction returns
    assertion facts about source bytes — it is a consumer's input, not policy — so it
    cannot become a third producer. Asserted here rather than assumed, because the guard is
    the thing that stops an agent authoring its own policy and it is not negotiable.
    """
    import inspect

    import belay.verify.assertions as module

    producers = {
        name
        for name, obj in vars(module).items()
        if not name.startswith("_")
        and callable(obj)
        and getattr(obj, "__module__", None) == module.__name__
        and "Invariant" in str(inspect.signature(obj).return_annotation)
    }
    assert producers == set(), producers


def test_the_public_surface_is_the_one_weakening_decision_was_promised() -> None:
    """The consumer contract, pinned: kinds, the verbatim pattern, and the failure signal.

    `weakening-decision` pairs on `(function, kind, ordinal)`, compares `form`, and runs
    glob subsumption on `pattern`. Those five fields are the interface; a rename that
    quietly drops one would break that aspect at integration time rather than here.
    """
    a = Assertion(
        kind=KIND_GLOB_PATTERN,
        form="'a*b'",
        function="test_x",
        ordinal=0,
        pattern="a*b",
    )

    assert (a.kind, a.form, a.function, a.ordinal, a.pattern) == (
        KIND_GLOB_PATTERN,
        "'a*b'",
        "test_x",
        0,
        "a*b",
    )
    # Hashable and frozen: the facts go into sets and must not be mutated after the walk.
    assert {a, a} == {a}
    with pytest.raises(Exception):
        a.form = "other"  # type: ignore[misc]

    # Non-pattern kinds carry no pattern, so a caller cannot mistake `None` for "".
    plain = Assertion(kind=KIND_ASSERT, form="x", function="test_x", ordinal=0)
    assert plain.pattern is None
