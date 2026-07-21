"""Deterministic fakes for `Model` — no LLM, no network, no I/O.

`ScriptedModel` is the determinism anchor for the driver loop (Task 3): it turns "does the
loop behave correctly" from a live-LLM problem into a pure-function problem by replaying a
fixed, ordered list of `ToolCall | Done` steps and nothing else.
"""

from __future__ import annotations

from eval.minting_driver.model import Done, Message, ToolCall


class ScriptExhausted(RuntimeError):
    """Raised when `ScriptedModel.propose_next` is called past its scripted steps.

    A driver bug (looping past a `Done`, or invoking the model one turn too many) must be
    loud, not silently return something plausible — the whole point of a scripted fake is
    that a test can assert an EXACT call count against it.
    """


class ScriptedModel:
    """A `Model` that replays a fixed, ordered script of steps — one per call.

    Holds no state beyond a cursor into `steps`. `messages` is accepted (to satisfy the
    `Model` protocol) but ignored: the script is the sole source of truth, which is what
    makes this fake deterministic regardless of what the loop appends to the history.
    """

    def __init__(self, steps: list[ToolCall | Done]) -> None:
        self._steps = list(steps)
        self._calls = 0

    def propose_next(self, messages: list[Message]) -> ToolCall | Done:
        self._calls += 1
        if self._calls > len(self._steps):
            raise ScriptExhausted(
                f"ScriptedModel.propose_next called {self._calls} time(s) but only "
                f"{len(self._steps)} step(s) were scripted"
            )
        return self._steps[self._calls - 1]
