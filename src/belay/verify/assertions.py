"""A1 / C5: what assertions does this Python source contain?

Belay's A1 default fired seven times on real mint data and was right zero times —
`precision 0.00` (`docs/technical/PHASE0_AUDIT.md`). Its rule was *"any write under
`tests/`"*, which is the normal, correct behaviour of an agent asked to fix a bug: it adds
a test. The replacement rule has to say something narrower — *"an assertion that was there
is gone or accepts more"* — and **nothing in this codebase could name an assertion at all**.
A1 matched path prefixes on a delta whose content field is a sha256 digest. This module is
that missing piece, and deliberately only that piece: source bytes in, assertion facts out.
No filesystem, no trace, no verdict. `weakening-decision` compares two of these sets;
`invariant-rule-wiring` finds the bytes to feed it.

**`ExtractionFailure` is a type, not a flag, and that is the module's whole safety story.**
A file with no assertions and a file that could not be parsed are opposite facts: the first
says *nothing was removed* (a PASS input), the second says *undecidable* (an UNVERIFIED
input). Returning an empty set for a syntax error would manufacture "no assertions were
removed" out of "I could not read it" — the false-PASS shape this project exists to refuse.
Distinguishing them by type means a caller cannot forget to check.

**AST, never lines.** `pylint-5859` turn 6 is the audit's closest call: a line diff reports
`MessageTest(msg_id="fixme", line=2, args="CODETAG", col_offset=17)` as REMOVED when the
only edit was appending a **trailing comma**. Comparison runs on `ast.unparse` output, which
normalises away trailing commas, line wrapping, whitespace, quote style, and redundant
parentheses. Identity carries no line number and no column offset either: a test that moved
down the file because something was inserted above it has not changed.

## What counts as an assertion (the rule, stated once, naming no fixture)

A construct is an assertion when the language or a documented testing API says so:

- an `assert` statement — identified by its **test expression only**, because dropping the
  optional message narrows nothing about what the assertion accepts;
- `pytest.raises(...)` and `pytest.fail(...)`, attribute calls on the name `pytest`;
- a call to any attribute whose name starts with `assert` — the unittest naming convention,
  which reaches `assertEqual`, `assertAddsMessages` and `assertNoMessages` alike **without
  an allowlist naming any of them**;
- pytest's positive line matchers `fnmatch_lines` / `re_match_lines` (and their `_random`
  variants), whose *patterns* are the assertions.

**Project helpers are deliberately NOT recognised** (PRD M4). Treating a bare
`common_object_test(...)` as an assertion requires either a general heuristic over arbitrary
calls or a list of names fitted until the fixtures pass — and a fitted list is exactly the
guess this unit exists to replace. Recognition is asymmetric: a missed idiom detects no
assertion, so it detects no removal, so the rule does not fire. Safe on a negative, a miss
on a positive, and the cost is documented rather than papered over.

The **negative** matchers (`no_fnmatch_line`, `no_re_match_line`) are also out, for a
different and sharper reason: loosening a positive matcher grows what it accepts, while
loosening a negative one shrinks what it forbids, so subsumption points the other way. No
observed case exercises them, and giving a guess the same kind label as real evidence is
how an instrument starts lying.

## Two levels, because an expectation list is not one assertion

A recognised assertion yields one fact for the construct itself, plus one fact per element
of the **expectation collection** it is handed: the items of a literal list/tuple/set
argument, or its positional arguments when every one of them is itself a call. That second
level is what makes an individually removed expectation visible as its own removal instead
of as one big changed call — `assertAddsMessages(a)` -> `assertAddsMessages(a, b, c)` is an
addition, and only element-level facts can say so.

Line matchers are the one construct that yields **no** call-level fact. Their entire content
is the pattern collection, so a call-level form would restate it, and a pure pattern
*addition* would then read as a *modification* of the call — a false alarm invented by the
representation. `weakening-decision` also needs each pattern **verbatim** to decide glob
subsumption, so the pattern string is carried unaltered beside the normalised form.

## Decisions on the spec's open questions, with their reasons

- **`pytest.raises` as a context manager vs. as a call: the same fact.** The assertion is
  the `raises(...)` call and its arguments; the guarded block is not part of its identity.
  Falls out of walking calls rather than statements, and matches the spec's proposal.
- **`match=` IS part of identity.** It genuinely narrows which exceptions satisfy the
  assertion, so removing it grows the accepted set — a weakening that would be invisible if
  identity stopped at the exception type. No observed case removes a `match=`, so this is a
  reasoned choice and is marked as one.
- **The result is a MULTISET.** Two byte-identical assertions in one function are two
  checks, and deleting one removes real coverage. An `ordinal` within the enclosing
  function makes them distinct facts, so ordinary set semantics carry multiset meaning.
  The ordinal counts within a `(function, kind)` group, so inserting a bare `assert` cannot
  renumber the glob patterns beside it and make every one of them look re-paired.
- **`ast.unparse` needs Python 3.9+;** the project requires 3.10+ (`pyproject.toml`), so it
  is available. Confirmed, not assumed.

Stdlib only — `ast`, `tokenize`, `io`, `dataclasses`. Zero runtime dependencies is a
headline property of the project, and the zero-LLM AST guard covers `src/belay/verify/`.
Note the naming hazard that guard creates: it bans first-party imports whose dotted parts
intersect `{llm, judge, model, models, inference, completion, prompt, prompts}`, which is
why this module is `assertions.py` and not `verify/models.py`.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass, field
from typing import Optional, Union

#: A bare `assert <expr>` statement. `form` is the test expression, normalised.
KIND_ASSERT = "assert"
#: `pytest.raises(...)`, whether used as a call or as a `with` item.
KIND_RAISES = "pytest.raises"
#: `pytest.fail(...)` — an unconditional failure is an assertion about reachability.
KIND_FAIL = "pytest.fail"
#: A call to an attribute named `assert*` — the unittest convention.
KIND_UNITTEST = "unittest-assert"
#: One glob pattern handed to `fnmatch_lines`. `pattern` carries it VERBATIM.
KIND_GLOB_PATTERN = "glob-pattern"
#: One regex handed to `re_match_lines`. A distinct kind so a glob decision procedure
#: cannot be run over it by accident and answer confidently in the wrong language.
KIND_REGEX_PATTERN = "regex-pattern"
#: One element of an assertion's expectation collection that is not a pattern literal —
#: a `MessageTest(...)`, or a non-literal handed to a line matcher.
KIND_EXPECTATION = "expectation"

#: The source bytes could not be turned into text: invalid bytes for the declared or
#: default encoding, or an encoding declaration Python does not have.
UNDECODABLE_SOURCE = "undecodable-source"
#: The text is not parseable Python — a syntax error, or bytes `ast` refuses such as NUL.
UNPARSEABLE_SOURCE = "unparseable-source"

#: pytest's POSITIVE line matchers, by attribute name. Documented public API of pytest's
#: `LineMatcher`, not project helpers — naming them is reading a spec, not fitting a list
#: to fixtures. Their negative siblings are excluded on purpose (see the module docstring).
_GLOB_MATCHERS = frozenset({"fnmatch_lines", "fnmatch_lines_random"})
_REGEX_MATCHERS = frozenset({"re_match_lines", "re_match_lines_random"})

#: Functions reached as `pytest.<name>(...)`, mapped to the kind they produce.
_PYTEST_CALLS = {"raises": KIND_RAISES, "fail": KIND_FAIL}


@dataclass(frozen=True)
class Assertion:
    """One assertion, identified so that two versions of a file can be compared.

    `form` is the `ast.unparse` normalisation — the basis for equality, and the reason
    reformatting is not an edit. `kind` says which idiom produced it. `function` is the
    enclosing function, qualified by any enclosing classes (`TestFixme.test_x`) and `None`
    at module level, so an identical assertion in an unrelated test never pairs up with
    this one. `ordinal` is the position within that `(function, kind)` group.

    `pattern` is set only for the glob/regex kinds and carries the pattern string
    **verbatim**, because `weakening-decision` reasons about subsumption over exactly those
    characters rather than about equality of the normalised form.

    Deliberately absent: line numbers and column offsets. An assertion that moved has not
    changed, and encoding position into identity would make one insertion look like the
    wholesale removal and re-addition of everything below it.
    """

    kind: str
    form: str
    function: Optional[str]
    ordinal: int
    pattern: Optional[str] = None


@dataclass(frozen=True, eq=False)
class AssertionSet:
    """The assertions found in one file, in document order, compared by membership.

    Order is preserved because it makes failures readable and keeps extraction verifiably
    deterministic, but equality ignores it: a future change to walk order must not be able
    to flip a downstream verdict when no assertion has moved. Duplicates cannot collapse,
    because `Assertion.ordinal` already distinguishes them.
    """

    assertions: tuple[Assertion, ...] = field(default_factory=tuple)

    def __iter__(self):
        return iter(self.assertions)

    def __len__(self) -> int:
        return len(self.assertions)

    def __contains__(self, item: object) -> bool:
        return item in frozenset(self.assertions)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AssertionSet):
            return NotImplemented
        return frozenset(self.assertions) == frozenset(other.assertions)

    def __hash__(self) -> int:
        return hash(frozenset(self.assertions))


@dataclass(frozen=True)
class ExtractionFailure:
    """Extraction could not be performed — NOT "there were no assertions".

    Downstream this must become `UNVERIFIED`. It is a separate type rather than a flag or
    a sentinel value precisely so that a caller writing `if not result:` cannot silently
    read it as an empty set and report a run clean on a file nobody could read.

    `cause` comes from the closed vocabulary above so a verdict can name its grounding;
    `detail` carries the underlying message for a human.
    """

    cause: str
    detail: str


def extract(source: bytes) -> Union[AssertionSet, ExtractionFailure]:
    """Python source **bytes** -> the assertions it contains, or a named failure.

    Bytes, not `str`, mirroring the BTH-1 raw-bytes discipline the rest of the verdict path
    keeps: decoding is where the unicode-normalisation traps live, so the decode happens
    here, once, honouring any PEP-263 declaration the file makes about itself. A `str`
    argument is a `TypeError` rather than a convenience, because accepting one would let a
    caller decode with the wrong codec upstream and never find out.

    Pure and deterministic: the same bytes always yield the same facts, in the same order.
    """
    if not isinstance(source, (bytes, bytearray, memoryview)):
        raise TypeError(
            f"extract() takes raw source bytes, got {type(source).__name__}. Decoding is "
            "the caller's blind spot, not its convenience: the bytes carry their own "
            "encoding declaration and this function honours it."
        )
    raw = bytes(source)

    try:
        text = _decode(raw)
    except (SyntaxError, UnicodeDecodeError, LookupError) as exc:
        return ExtractionFailure(UNDECODABLE_SOURCE, str(exc))

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        # ValueError, not only SyntaxError: `ast` rejects embedded NUL bytes that way.
        return ExtractionFailure(UNPARSEABLE_SOURCE, str(exc))

    try:
        return AssertionSet(tuple(_walk(tree)))
    except RecursionError as exc:  # pragma: no cover - pathological nesting
        return ExtractionFailure(UNPARSEABLE_SOURCE, f"source nests too deeply: {exc}")


def _decode(raw: bytes) -> str:
    """Raw bytes -> text, honouring a PEP-263 coding declaration if the file makes one.

    `tokenize.detect_encoding` is the same reader CPython itself uses, so a file that
    declares `latin-1` is read as `latin-1` and a UTF-8 BOM is consumed rather than left to
    become a stray character at the head of the first token. An undeclared file defaults to
    UTF-8 and invalid bytes raise — never a lossy `errors="replace"`, which would invent
    source that was never written.
    """
    encoding, _lines = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding)


def _walk(tree: ast.Module):
    """Depth-first, in source order, yielding one `Assertion` per fact found.

    Source order (rather than `ast.walk`'s breadth-first sweep) is what makes `ordinal`
    mean "the nth assertion of this kind in this function", which is what
    `weakening-decision` pairs on.
    """
    counters: dict[tuple[Optional[str], str], int] = {}
    scope: list[str] = []

    def emit(kind: str, form: str, pattern: Optional[str] = None) -> Assertion:
        function = ".".join(scope) if scope else None
        key = (function, kind)
        ordinal = counters.get(key, 0)
        counters[key] = ordinal + 1
        return Assertion(
            kind=kind, form=form, function=function, ordinal=ordinal, pattern=pattern
        )

    def visit(node: ast.AST):
        pushed = False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope.append(node.name)
            pushed = True

        if isinstance(node, ast.Assert):
            # The test expression only. `assert x, "why"` and `assert x` assert the same
            # thing about x; the message narrows nothing, so it is not part of the fact.
            yield emit(KIND_ASSERT, ast.unparse(node.test))
        elif isinstance(node, ast.Call):
            yield from _from_call(node, emit)

        for child in ast.iter_child_nodes(node):
            yield from visit(child)

        if pushed:
            scope.pop()

    yield from visit(tree)


def _from_call(node: ast.Call, emit):
    """One `ast.Call` -> the facts it produces, if it is a recognised assertion."""
    kind = _call_kind(node)
    if kind is None:
        return

    if kind in (KIND_GLOB_PATTERN, KIND_REGEX_PATTERN):
        # A line matcher IS its patterns. No call-level fact: it would merely restate the
        # collection, and it would turn a pure pattern addition into a call modification.
        for element in _payload(node, patterns=True):
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                yield emit(kind, ast.unparse(element), element.value)
            else:
                # A non-literal handed to a matcher is still an expectation, and saying so
                # keeps it visible. Its kind differs from a literal's, which downstream
                # reads as "kind changed -> undecidable" rather than as a silent match.
                yield emit(KIND_EXPECTATION, ast.unparse(element))
        return

    yield emit(kind, ast.unparse(node))
    for element in _payload(node, patterns=False):
        yield emit(KIND_EXPECTATION, ast.unparse(element))


def _call_kind(node: ast.Call) -> Optional[str]:
    """Which idiom, if any, this call is — by naming convention and documented API only."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        # A bare `helper(...)` is not an assertion. Recognising one needs a name list
        # fitted to the cases at hand, which PRD M4 forbids; see the module docstring.
        return None

    if func.attr in _GLOB_MATCHERS:
        return KIND_GLOB_PATTERN
    if func.attr in _REGEX_MATCHERS:
        return KIND_REGEX_PATTERN
    if isinstance(func.value, ast.Name) and func.value.id == "pytest":
        pytest_kind = _PYTEST_CALLS.get(func.attr)
        if pytest_kind is not None:
            return pytest_kind
    if func.attr.startswith("assert") and func.attr != "assert":
        return KIND_UNITTEST
    return None


def _payload(node: ast.Call, *, patterns: bool) -> list[ast.expr]:
    """The call's expectation collection — the elements worth their own fact.

    Two shapes, and nothing else. A sole literal list/tuple/set argument is a collection of
    expectations. Otherwise the positional arguments are one, but only when every one of
    them is itself a call (the constructor-style shape) — `assertEqual(a, b)` compares two
    operands and decomposing it would invent two assertions where there is one.

    A line matcher is the exception: its arguments ARE its payload whatever their shape,
    because it produces no call-level fact and an unrecognised argument would otherwise
    make the whole assertion vanish. The known imprecision is `assertEqual(f(x), g(y))`,
    whose operands are both calls and so are decomposed; that yields two extra facts which
    pair by ordinal and compare equal whenever they are unchanged, so it costs noise rather
    than correctness.
    """
    args = list(node.args)
    if len(args) == 1 and isinstance(args[0], (ast.List, ast.Tuple, ast.Set)):
        return list(args[0].elts)
    if patterns:
        return args
    if args and all(isinstance(a, ast.Call) for a in args):
        return args
    return []


__all__ = [
    "Assertion",
    "AssertionSet",
    "ExtractionFailure",
    "extract",
    "KIND_ASSERT",
    "KIND_RAISES",
    "KIND_FAIL",
    "KIND_UNITTEST",
    "KIND_GLOB_PATTERN",
    "KIND_REGEX_PATTERN",
    "KIND_EXPECTATION",
    "UNDECODABLE_SOURCE",
    "UNPARSEABLE_SOURCE",
]
