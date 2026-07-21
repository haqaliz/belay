"""Mechanical task-string derivation from a SWE-bench `problem_statement`.

One pure function, `derive_task_string`: whitespace-normalize the statement, truncate it
at the latest paragraph/sentence boundary that fits the budget, and prefix a fixed
imperative framing (`TASK_PREFIX`). No LLM, no network, no clock, no randomness — the
same statement always yields the identical string, so the mint set is reproducible from
the committed registry alone and no per-instance hand-tuning can creep in.

**Coverage caveat — read before quoting any number derived from these tasks.**
Truncation can drop part of the problem statement. When it does, the agent is driven by
the *truncated* statement, so it attempts what that truncation says rather than the
benchmark's full requirement. The agent's actions are still real actions, and the
verification of those actions is unaffected — but the *task* is not guaranteed to be the
benchmark's task. This is a stated limitation to report alongside the results, not a
defect to work around: what Belay measures here is whether the agent's own turns hold up
under replay, not whether the SWE-bench issue was resolved. The default budget
(`max_chars = 1500`) is a judgment call balancing fidelity against prompt size, not a
measured value; statements at or under it are passed through whole and untouched.
"""

from __future__ import annotations

import re

TASK_PREFIX = "Fix the following issue in this repository:\n\n"
"""The fixed imperative framing prepended to every derived task string.

A module-level constant, not an inline literal, so tests and the registry generator can
reason about the framing's length (it is charged against `max_chars`) without restating it.
"""

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_WHITESPACE_RUN = re.compile(r"\s+")
_PARAGRAPH_BREAK = "\n\n"

# A sentence terminator, optionally followed by a closing quote/bracket, that is actually
# at the end of a sentence — i.e. followed by whitespace or the end of the window. The
# lookahead is what keeps "e.g." or "version 2.7.1" from being read as a boundary when
# they are mid-word; it does not make this a real sentence tokenizer, and it does not
# need to be one: a slightly early cut costs a little context, never correctness.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?(?=\s|$)")


def _normalize(text: str) -> str:
    """Collapse whitespace, keeping paragraph breaks as a single blank line.

    Runs of whitespace inside a paragraph become one space; runs of blank lines between
    paragraphs become exactly one `"\\n\\n"`. Empty paragraphs are dropped. The result is
    stripped, so a statement that is only whitespace normalizes to `""`.
    """
    paragraphs = (
        _WHITESPACE_RUN.sub(" ", para).strip() for para in _PARAGRAPH_SPLIT.split(text)
    )
    return _PARAGRAPH_BREAK.join(para for para in paragraphs if para)


def _cut_index(text: str, budget: int) -> int:
    """The index to truncate `text` at: the latest boundary at or under `budget`.

    Candidates, in order of how much text they retain rather than how "strong" they are:
    the last paragraph break and the last sentence terminator inside `text[:budget]`, then
    — only if neither exists — the last whitespace, so the cut is never mid-word.
    Taking the *latest* candidate (rather than always preferring a paragraph break) keeps
    a one-line opening paragraph from throwing away the rest of a statement that fits.
    Returns `0` when not even one whole word fits, which the caller turns into an error.
    """
    window = text[:budget]

    paragraph_cut = window.rfind(_PARAGRAPH_BREAK)

    sentence_matches = list(_SENTENCE_END.finditer(window))
    sentence_cut = sentence_matches[-1].end() if sentence_matches else -1

    cut = max(paragraph_cut, sentence_cut)
    if cut > 0:
        return cut

    # No boundary in range: fall back to the last word break. `text[budget]` is safe —
    # this function is only called when `len(text) > budget`.
    if text[budget].isspace():
        return budget
    word_cut = max(window.rfind(" "), window.rfind("\n"))
    return word_cut if word_cut > 0 else 0


def derive_task_string(problem_statement: str, *, max_chars: int = 1500) -> str:
    """The task string for `problem_statement`: framing + normalized, bounded statement.

    Pure and deterministic. The returned string is never longer than `max_chars` (the
    framing is charged against the budget), never empty, and — when truncated — always
    ends at a paragraph break, a sentence terminator, or a word break, never mid-word.
    A statement that already fits is returned whole, with no padding.

    Raises `ValueError` if `problem_statement` is empty or whitespace-only (a silently
    empty task would drive an agent to do nothing and quietly become a mint instance that
    proves nothing), or if `max_chars` cannot hold the framing plus at least one word.
    """
    normalized = _normalize(problem_statement)
    if not normalized:
        raise ValueError(
            "derive_task_string: problem_statement is empty or whitespace-only; "
            "a task string is never derived from nothing"
        )

    budget = max_chars - len(TASK_PREFIX)
    if budget <= 0:
        raise ValueError(
            f"derive_task_string: max_chars={max_chars} leaves no room for the "
            f"statement after the {len(TASK_PREFIX)}-character framing"
        )

    if len(normalized) <= budget:
        return TASK_PREFIX + normalized

    body = normalized[: _cut_index(normalized, budget)].rstrip()
    if not body:
        raise ValueError(
            f"derive_task_string: max_chars={max_chars} is too small to hold the framing "
            f"plus one word of the statement"
        )
    return TASK_PREFIX + body


__all__ = ["TASK_PREFIX", "derive_task_string"]
