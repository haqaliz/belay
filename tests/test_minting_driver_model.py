"""RED-first tests for the minting-driver's model seam (Task 1).

`eval/minting_driver/` is an eval-only tool, NOT part of the shipped `belay` package —
these tests import from `eval.minting_driver`, never from `belay`. They exercise pure data
+ the `ScriptedModel` fake: no I/O, no network, no LLM. `ScriptedModel` is the determinism
anchor the driver loop (Task 3) will be tested against, so what matters here is exact
call-count behaviour: steps come back in order, a `Done` is just another step (the loop
decides to stop on it, the model doesn't), and calling past the script is loud, not silent.
"""

from __future__ import annotations

import pytest

from eval.minting_driver.fakes import ScriptExhausted, ScriptedModel
from eval.minting_driver.model import Done, Message, ToolCall


def test_scripted_model_returns_steps_in_order() -> None:
    steps = [
        ToolCall(name="read_file", arguments={"path": "a.py"}),
        ToolCall(name="run_tests", arguments={}),
        Done(reason="task complete"),
    ]
    model = ScriptedModel(steps)
    history: list[Message] = []

    observed = [model.propose_next(history) for _ in steps]

    assert observed == steps


def test_done_terminates_a_sequence() -> None:
    steps = [ToolCall(name="read_file", arguments={"path": "a.py"}), Done(reason="done")]
    model = ScriptedModel(steps)

    first = model.propose_next([])
    second = model.propose_next([])

    assert first == ToolCall(name="read_file", arguments={"path": "a.py"})
    assert isinstance(second, Done)
    assert second.reason == "done"


def test_calling_past_the_script_raises() -> None:
    model = ScriptedModel([Done(reason="only step")])

    model.propose_next([])

    with pytest.raises(ScriptExhausted):
        model.propose_next([])


def test_calling_past_the_script_raises_with_exact_call_count() -> None:
    """A test can assert an EXACT call count off the raised exception's message."""
    model = ScriptedModel([ToolCall(name="noop", arguments={})])
    model.propose_next([])

    with pytest.raises(ScriptExhausted, match=r"2.*only 1"):
        model.propose_next([])


def test_scripted_model_ignores_message_history_it_is_passed() -> None:
    """The script is the sole source of truth — messages passed in do not steer it."""
    model = ScriptedModel([Done(reason="done")])

    result = model.propose_next([Message(role="user", content="anything")])

    assert result == Done(reason="done")
