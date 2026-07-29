"""Does one glob pattern accept a strictly larger set of strings than another?

This module answers exactly that question, and it exists because the only real
assertion-weakening evidence Belay has is not an `assert` statement at all. In
`pytest-dev__pytest-5227` the agent rewrote two `fnmatch_lines` patterns:

    "test_log_cli_enabled_disabled.py* CRITICAL critical message logged by test"
 -> "*CRITICAL*critical message logged by test"

Both still assert *something*; the second one just accepts strictly more, including the
old log output the task asked the agent to replace. A rule keyed on `assert` keywords does
not fire on it, which would leave the unit with no positive evidence at all (PRD M5).

**The answer is exact, not a heuristic.** `L(A) ⊆ L(B) and L(B) ⊄ L(A)` is decidable for
glob patterns, and the procedure below decides it rather than approximating it — a
substring or prefix heuristic would be a guess wearing an algorithm's clothes, and this
project's whole complaint about LLM-as-judge is that a guess reported as a verdict is
worse than an abstention.

## The procedure, and why each step is sound

1. **Abstract the alphabet.** Collect every character either pattern mentions literally,
   plus every member of any `[seq]` class, and add one fresh `OTHER` symbol standing for
   the entire rest of Unicode. This is SOUND because a glob cannot distinguish two
   characters it never mentions: `*`, `?` and a negated class all treat them identically,
   so containment over the abstracted alphabet holds iff it holds over the real one. The
   alphabet is therefore finite and small — the whole reason the rest is cheap.
2. **Compile each pattern to a DFA** over that alphabet. `*` is a self-loop plus an
   epsilon; `?` is any symbol; `[seq]` is the listed symbols (or their complement); a
   literal is itself. Subset construction determinises.
3. **Decide containment** by emptiness of `L(A) ∩ complement(L(B))` — a product
   construction plus reachability. Standard, exact, stdlib-only.
4. **Strictly looser** iff containment holds one way and not the other. Equal languages
   and incomparable languages both come back not-looser: an equal pattern removed nothing,
   and two languages that cross in both directions are a *changed expectation*, which the
   unit's definition deliberately excludes.
5. **Size guard.** Subset construction is exponential in the worst case (`*a????????…` is
   the textbook family: the DFA must remember where every `a` fell in a sliding window).
   Exceeding a fixed state or alphabet budget returns `GLOB_UNDECIDABLE`, which the caller
   turns into `UNVERIFIED`. Never a hang, never a guess.

## Decisions, with their reasons

- **`fnmatch` semantics, case-sensitive** (`fnmatch.fnmatchcase`, not `fnmatch.fnmatch`).
  pytest's `LineMatcher` matches against captured output on whatever platform the capture
  ran on; folding case would make the verdict depend on the *verifier's* `os.path.normcase`
  rather than on the recorded run, which is the kind of environment dependence replay
  fidelity exists to eliminate.
- **`*` matches anything including `/` and newlines**, matching `fnmatch` (and unlike
  shell globbing). `LineMatcher` matches one line at a time, so the distinction is inert
  here, but guessing the *shell's* semantics on pytest's matcher would be wrong for a
  pattern that happens to contain a slash.
- **Anything the tokenizer cannot read confidently is `GLOB_UNDECIDABLE`.** Backslash
  escapes and the `[a--b]` corner of character-class syntax vary across Python versions;
  abstaining costs an UNVERIFIED on a pattern no observed case uses, whereas guessing
  costs a wrong verdict on the one thing this module is trusted for.

Stdlib only — no `re`, and deliberately not `fnmatch.translate` + a regex containment
solver, because Python's `re` has no containment operation and translating to a regex
would only move the problem. `fnmatch` itself is imported nowhere here; this module
reimplements the matcher as an automaton because *matching* one string is a different
question from *comparing two languages*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: `post` accepts every string `pre` accepts, and at least one more. The weakening.
GLOB_STRICTLY_LOOSER = "strictly-looser"
#: Equal, narrower, or incomparable. None of the three is a weakening.
GLOB_NOT_LOOSER = "not-looser"
#: A budget was exceeded or the pattern used syntax this module refuses to guess at.
#: Callers must render this as UNVERIFIED — never as "unchanged".
GLOB_UNDECIDABLE = "undecidable"

#: Budgets. Real `fnmatch_lines` patterns compile to a handful of DFA states over a couple
#: of dozen symbols, so these sit far above anything observed while still bounding the
#: product construction (states_A × states_B × alphabet) to a few million transitions in
#: the very worst admitted case. Fixed constants rather than tunables: a budget an operator
#: can raise is a budget that turns an honest abstention into a hang on someone's CI box.
MAX_DFA_STATES = 512
MAX_ALPHABET = 96

#: The abstraction. Not a character — a sentinel object, so it can never collide with a
#: character a pattern actually mentions. `object()` rather than a reserved codepoint for
#: the same reason: there is no codepoint a pattern is forbidden to contain.
OTHER = object()

_STAR = "star"
_ANY = "any"
_LITERAL = "literal"
_CLASS = "class"


@dataclass(frozen=True)
class _Token:
    """One element of a compiled pattern.

    `value` is the character for `_LITERAL`, the member set for `_CLASS`, and `None`
    otherwise. `negated` applies to `_CLASS` only.
    """

    kind: str
    value: object = None
    negated: bool = False


def strictly_looser(pre: str, post: str) -> str:
    """Does `post` accept a strictly larger set of strings than `pre`?

    Returns one of `GLOB_STRICTLY_LOOSER`, `GLOB_NOT_LOOSER`, `GLOB_UNDECIDABLE`. Pure and
    deterministic; the same two strings always give the same answer.

    Byte-identical patterns short-circuit to not-looser before anything is compiled. That
    is not only a fast path: it means a pattern too pathological to compile still gets the
    right answer when it was not edited at all, which is the overwhelmingly common case.
    """
    if pre == post:
        return GLOB_NOT_LOOSER

    tokens_pre = _tokenize(pre)
    tokens_post = _tokenize(post)
    if tokens_pre is None or tokens_post is None:
        return GLOB_UNDECIDABLE

    alphabet = _alphabet(tokens_pre, tokens_post)
    if alphabet is None:
        return GLOB_UNDECIDABLE

    dfa_pre = _compile(tokens_pre, alphabet)
    dfa_post = _compile(tokens_post, alphabet)
    if dfa_pre is None or dfa_post is None:
        return GLOB_UNDECIDABLE

    pre_within_post = _contains(dfa_pre, dfa_post)
    post_within_pre = _contains(dfa_post, dfa_pre)
    if pre_within_post and not post_within_pre:
        return GLOB_STRICTLY_LOOSER
    return GLOB_NOT_LOOSER


# ---------------------------------------------------------------------------
# Tokenising
# ---------------------------------------------------------------------------


def _tokenize(pattern: str) -> Optional[list[_Token]]:
    """Pattern text -> tokens, or `None` if any part of it is not confidently readable.

    Mirrors `fnmatch.translate`'s scanning rules for `[`: a `!` immediately after the
    bracket negates, a `]` in first position is a literal member, and an unterminated `[`
    is itself a literal. Ranges (`a-z`) are expanded to their members, which is what makes
    the alphabet abstraction exact for classes as well as literals.
    """
    tokens: list[_Token] = []
    i = 0
    n = len(pattern)
    while i < n:
        char = pattern[i]
        i += 1
        if char == "*":
            # Collapse runs: `**` accepts exactly what `*` accepts, and one token fewer
            # keeps the NFA (and so the subset construction) smaller for free.
            if tokens and tokens[-1].kind == _STAR:
                continue
            tokens.append(_Token(_STAR))
        elif char == "?":
            tokens.append(_Token(_ANY))
        elif char == "[":
            end = i
            if end < n and pattern[end] == "!":
                end += 1
            if end < n and pattern[end] == "]":
                end += 1
            while end < n and pattern[end] != "]":
                end += 1
            if end >= n:
                # Unterminated: `fnmatch` treats the bracket as an ordinary character.
                tokens.append(_Token(_LITERAL, "["))
                continue
            body = pattern[i:end]
            i = end + 1
            token = _class_token(body)
            if token is None:
                return None
            tokens.append(token)
        else:
            tokens.append(_Token(_LITERAL, char))
    return tokens


def _class_token(body: str) -> Optional[_Token]:
    """`[...]` body -> a member set, or `None` to abstain.

    Abstains on backslashes, which `fnmatch` handles differently across Python versions,
    and on any range whose endpoints are out of order — both are cases where a confident
    answer would be a guess about someone else's matcher.
    """
    negated = body.startswith("!")
    if negated:
        body = body[1:]
    if "\\" in body:
        return None

    members: set[str] = set()
    i = 0
    n = len(body)
    while i < n:
        if i + 2 < n and body[i + 1] == "-":
            lo, hi = body[i], body[i + 2]
            if ord(hi) < ord(lo):
                return None
            span = ord(hi) - ord(lo) + 1
            if span > MAX_ALPHABET:
                # A range wider than the alphabet budget cannot be abstracted soundly
                # without blowing the budget anyway; say so now rather than later.
                return None
            members.update(chr(c) for c in range(ord(lo), ord(hi) + 1))
            i += 3
        else:
            members.add(body[i])
            i += 1
    if not members:
        # `[]` is not a class `fnmatch` produces; refuse rather than invent a meaning.
        return None
    return _Token(_CLASS, frozenset(members), negated)


def _alphabet(*token_lists: list[_Token]) -> Optional[list[object]]:
    """Every character either pattern mentions, plus `OTHER`.

    `OTHER` is what makes the abstraction sound AND finite: it stands for every character
    neither pattern names, and since neither pattern can tell those characters apart, one
    representative decides for all of them.
    """
    mentioned: set[str] = set()
    for tokens in token_lists:
        for token in tokens:
            if token.kind == _LITERAL:
                mentioned.add(token.value)  # type: ignore[arg-type]
            elif token.kind == _CLASS:
                mentioned.update(token.value)  # type: ignore[arg-type]
    if len(mentioned) + 1 > MAX_ALPHABET:
        return None
    return sorted(mentioned) + [OTHER]


# ---------------------------------------------------------------------------
# Compiling to a DFA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Dfa:
    """A complete DFA over a shared alphabet. State 0 is the start state.

    `transitions[state][symbol_index]` is total — the empty NFA-state set is a real,
    reachable, non-accepting sink — so the product construction below never has to special
    case a missing edge.
    """

    transitions: tuple[tuple[int, ...], ...]
    accepting: frozenset[int]
    alphabet_size: int


def _compile(tokens: list[_Token], alphabet: list[object]) -> Optional[_Dfa]:
    """Tokens -> a DFA, or `None` if the state budget is exceeded.

    The NFA is positional: state `i` means "we are about to consume token `i`", and state
    `len(tokens)` is the accepting end. `*` contributes an epsilon to `i+1` and a self-loop
    on every symbol. Subset construction then determinises, checking the budget on every
    new state so a blow-up is reported instead of built.
    """
    end = len(tokens)

    def closure(states: frozenset[int]) -> frozenset[int]:
        out = set(states)
        pending = list(states)
        while pending:
            state = pending.pop()
            if state < end and tokens[state].kind == _STAR and state + 1 not in out:
                out.add(state + 1)
                pending.append(state + 1)
        return frozenset(out)

    def matches(token: _Token, symbol: object) -> bool:
        if token.kind == _STAR or token.kind == _ANY:
            return True
        if token.kind == _LITERAL:
            return symbol == token.value
        members: frozenset[str] = token.value  # type: ignore[assignment]
        inside = symbol is not OTHER and symbol in members
        return not inside if token.negated else inside

    start = closure(frozenset({0}))
    index: dict[frozenset[int], int] = {start: 0}
    order: list[frozenset[int]] = [start]
    transitions: list[list[int]] = []

    cursor = 0
    while cursor < len(order):
        states = order[cursor]
        cursor += 1
        row: list[int] = []
        for symbol in alphabet:
            moved: set[int] = set()
            for state in states:
                if state >= end:
                    continue
                token = tokens[state]
                if matches(token, symbol):
                    moved.add(state + 1)
                if token.kind == _STAR:
                    moved.add(state)
            target = closure(frozenset(moved))
            if target not in index:
                if len(order) >= MAX_DFA_STATES:
                    return None
                index[target] = len(order)
                order.append(target)
            row.append(index[target])
        transitions.append(row)

    accepting = frozenset(i for i, states in enumerate(order) if end in states)
    return _Dfa(
        transitions=tuple(tuple(row) for row in transitions),
        accepting=accepting,
        alphabet_size=len(alphabet),
    )


def _contains(inner: _Dfa, outer: _Dfa) -> bool:
    """Is `L(inner) ⊆ L(outer)`?

    Equivalent to `L(inner) ∩ complement(L(outer)) = ∅`, decided by walking the product
    automaton from its start pair: containment fails exactly when some reachable pair has
    `inner` accepting and `outer` not. Both DFAs are complete, so the walk is a plain BFS
    and the complement of `outer` is just the negation of its accepting set.
    """
    start = (0, 0)
    seen = {start}
    pending = [start]
    while pending:
        left, right = pending.pop()
        if left in inner.accepting and right not in outer.accepting:
            return False
        for symbol in range(inner.alphabet_size):
            nxt = (inner.transitions[left][symbol], outer.transitions[right][symbol])
            if nxt not in seen:
                seen.add(nxt)
                pending.append(nxt)
    return True


__all__ = [
    "GLOB_NOT_LOOSER",
    "GLOB_STRICTLY_LOOSER",
    "GLOB_UNDECIDABLE",
    "MAX_ALPHABET",
    "MAX_DFA_STATES",
    "strictly_looser",
]
