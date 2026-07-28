"""Deterministic fakes for `Model` — no LLM, no network, no I/O.

`ScriptedModel` is the determinism anchor for the driver loop (Task 3): it turns "does the
loop behave correctly" from a live-LLM problem into a pure-function problem by replaying a
fixed, ordered list of `ToolCall | Done` steps and nothing else.

`FlakyModel` is its fault-injecting counterpart, added for the quota circuit breaker
(`resilience.py`): `ScriptedModel` has exactly one exception path — `ScriptExhausted` on
over-call — so it structurally cannot simulate a provider failure, which is the only thing
`RetryingModel` reacts to. `FlakyModel` scripts the failures and delegates everything else,
so the two compose rather than duplicate.
"""

from __future__ import annotations

from typing import Optional

from eval.minting_driver.model import Done, Message, Model, ToolCall


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


class FlakyModel:
    """A `Model` that raises scripted faults, then delegates to another `Model`.

    `faults` is one entry per call, in order: an exception instance is RAISED on that call,
    and `None` means "this call is clean" — so a mixed script like
    `[err, None, err]` reproduces a session that fails, recovers, and fails again, which is
    what makes a per-instance retry counter testable. Once the fault script is exhausted,
    every subsequent call delegates too.

    Delegation (rather than a second result script) is deliberate: `ScriptedModel` already
    is the result script, and composing the two keeps exactly one place that decides what a
    successful step returns. `inner` may be `None` when the test asserts that no call ever
    gets past the faults — reaching the delegate then raises `ScriptExhausted`, so an
    off-by-one in the retry bound is loud rather than silently returning something plausible.

    `calls` counts every `propose_next` invocation, faults included — that is the number a
    test asserts against to pin an exact attempt count.
    """

    def __init__(
        self,
        faults: list[Optional[BaseException]],
        inner: Optional[Model] = None,
    ) -> None:
        self._faults = list(faults)
        self._inner = inner
        self.calls = 0

    def propose_next(self, messages: list[Message]) -> ToolCall | Done:
        self.calls += 1
        if self.calls <= len(self._faults):
            fault = self._faults[self.calls - 1]
            if fault is not None:
                raise fault
        if self._inner is None:
            raise ScriptExhausted(
                f"FlakyModel.propose_next call {self.calls} got past its "
                f"{len(self._faults)} scripted fault(s) but no `inner` model was given"
            )
        # `messages` is forwarded untouched: a fault-injecting fake that rewrote the history
        # would break the one thing `RetryingModel`'s retry depends on — that the wrapper
        # hands the SAME list to every attempt.
        return self._inner.propose_next(messages)
