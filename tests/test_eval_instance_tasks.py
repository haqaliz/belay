"""RED-first tests for task-string derivation (instance-registry, Phase 2).

`eval/instances/` is eval-only data plumbing, NOT part of the shipped `belay` package —
these tests import from `eval.instances`, never from `belay`. `derive_task_string` is a
pure function: no LLM, no network, no clock, no randomness, so every assertion here is
exact rather than approximate. What matters is that the derivation is *mechanical*
(same statement in, byte-identical string out), *bounded* (never larger than the caller's
budget), *never mid-word* (a truncated task must still read as prose), and *loud* on an
empty statement (an empty task string would silently turn into a no-op mint instance).
"""

from __future__ import annotations

import pytest

from eval.instances.tasks import TASK_PREFIX, derive_task_string


def test_task_string_is_derived_deterministically() -> None:
    """Same statement in, byte-identical string out — twice, and across instances."""
    statement = "The parser drops trailing commas. It should keep them."

    first = derive_task_string(statement)
    second = derive_task_string(statement)

    assert first == second
    assert first.startswith(TASK_PREFIX)
    assert statement in first


def test_task_string_is_bounded_and_non_empty() -> None:
    statement = " ".join(f"Sentence number {i} explains the bug." for i in range(400))
    assert len(statement) > 1500

    task = derive_task_string(statement)

    assert 0 < len(task) <= 1500
    assert task.startswith(TASK_PREFIX)
    assert task[len(TASK_PREFIX) :].strip()


def test_task_string_respects_a_custom_max_chars() -> None:
    statement = " ".join(f"Sentence number {i} explains the bug." for i in range(400))

    task = derive_task_string(statement, max_chars=400)

    assert len(task) <= 400


def test_truncation_falls_on_a_boundary_not_mid_word() -> None:
    """The kept body must be a whole-token prefix of the statement, cut at a boundary."""
    statement = " ".join(f"Sentence number {i} explains the bug." for i in range(400))

    body = derive_task_string(statement)[len(TASK_PREFIX) :]

    # A prefix of the original, cut where the original has whitespace (never mid-word).
    assert statement.startswith(body)
    assert len(body) < len(statement)
    assert statement[len(body)].isspace()
    # And a *sentence* boundary, not merely a word boundary.
    assert body.endswith(".")


def test_truncation_uses_a_paragraph_boundary_when_it_is_the_latest_one() -> None:
    """A paragraph break counts as a boundary, not just sentence-terminating punctuation."""
    head = "First para sentence one. First para sentence two with no terminator"
    tail = "The second paragraph opens with a fairly long sentence. And more."
    statement = f"{head}\n\n{tail}"
    # Budget reaches a few characters into the second paragraph, so the latest boundary
    # available is the paragraph break — the last sentence-ending '.' is much earlier.
    budget = len(TASK_PREFIX) + len(head) + 10

    body = derive_task_string(statement, max_chars=budget)[len(TASK_PREFIX) :]

    assert body == head


def test_short_statement_is_returned_whole_with_no_padding() -> None:
    statement = "Fix the off-by-one in the slice bound."

    task = derive_task_string(statement, max_chars=1500)

    assert task == TASK_PREFIX + statement
    assert len(task) < 1500  # not padded out to the budget


def test_whitespace_is_normalized() -> None:
    statement = "The   parser\tdrops\ncommas.\n\n\n\nIt should   keep them.  "

    task = derive_task_string(statement)

    assert task == TASK_PREFIX + "The parser drops commas.\n\nIt should keep them."


@pytest.mark.parametrize("statement", ["", "   ", "\n\n", "\t \n "])
def test_empty_problem_statement_raises(statement: str) -> None:
    with pytest.raises(ValueError, match="problem_statement"):
        derive_task_string(statement)


def test_max_chars_too_small_for_the_framing_raises() -> None:
    """A budget that cannot hold the framing plus a word is an error, not an empty task."""
    with pytest.raises(ValueError, match="max_chars"):
        derive_task_string("Fix the bug.", max_chars=len(TASK_PREFIX))
