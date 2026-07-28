"""RED-first tests for the minting-driver's quota circuit breaker (`resilience.py`).

Two things are under test here, and they are deliberately different in kind.

**Phase 1 — `classify_error`.** A pure function mapping a provider exception to
`quota` / `transient` / `terminal`. The load-bearing fixture is `STAGE3_QUOTA_ERROR`
below: the **verbatim** `reason` string recorded by the 2026-07-24 Stage-3 mint, copied
out of `eval/mint/s3/checkpoint.json`, which is the error that destroyed 56 instances of
denominator in 3m48s. A paraphrased fixture would produce a classifier that passes its
tests and still fails live, so this one is exact, character for character (all 56 recorded
reasons normalize to the same signature — only the countdown digits differ).

**Phase 2 — `RetryingModel`.** A `Model`-shaped wrapper. Every backoff assertion is on the
**recorded sequence of requested delays** via `RecordingSleep`, never on elapsed wall time:
no test in this file may call the real `time.sleep`. A test that measures elapsed time would
be slow, flaky, and would not actually pin the schedule.

Everything here is deterministic and offline: no network, no SDK import, no model, no clock.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest

from eval.minting_driver.clients.local_client import LocalOpenAICompatModel
from eval.minting_driver.fakes import FlakyModel, ScriptedModel
from eval.minting_driver.model import Done, Message, Model, ToolCall
from eval.minting_driver.resilience import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    QUOTA_RETRY_THRESHOLD_SECONDS,
    QuotaExhausted,
    RetryingModel,
    TransientExhausted,
    classify_error,
    retry_after_seconds,
)

# ---------------------------------------------------------------------------
# The real Stage-3 quota error, verbatim
# ---------------------------------------------------------------------------

#: The exact `reason` string recorded for `control__flask-read-only` (and, modulo the
#: countdown digits, for all 56 instances the 2026-07-24 Stage-3 run burned) in
#: `.claude/worktrees/feat-verdict-coverage-status/eval/mint/s3/checkpoint.json`.
#:
#: Split across adjacent string literals purely for readability — the concatenation is
#: byte-identical to the recorded text and was generated mechanically from the checkpoint,
#: not retyped. Three independent quota signals are present in it and each one is exercised
#: separately below, because a provider may hand us only one of the three:
#:   - the HTTP status token `429` (there is no `status_code` attribute on a bare string),
#:   - `'status': 'RESOURCE_EXHAUSTED'` and `quotaId: GenerateRequestsPerDayPerProjectPerModel`,
#:   - `'retryDelay': '39043s'` — 10h50m43s, which no bounded backoff can ever wait out.
STAGE3_QUOTA_ERROR = (
    "Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current q"
    'uota, please check your plan and billing details. For more information on this err'
    'or, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your cu'
    'rrent usage, head to: https://ai.dev/rate-limit. \\n* Quota exceeded for metric: ge'
    'nerativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 250, m'
    "odel: gemini-3.1-pro\\nPlease retry in 10h50m43.651927829s.', 'status': 'RESOURCE_E"
    "XHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.Help', 'links': ["
    "{'description': 'Learn more about Gemini API quotas', 'url': 'https://ai.google.de"
    "v/gemini-api/docs/rate-limits'}]}, {'@type': 'type.googleapis.com/google.rpc.Quota"
    "Failure', 'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/genera"
    "te_requests_per_model_per_day', 'quotaId': 'GenerateRequestsPerDayPerProjectPerMod"
    "el', 'quotaDimensions': {'location': 'global', 'model': 'gemini-3.1-pro'}, 'quotaV"
    "alue': '250'}]}, {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay"
    "': '39043s'}]}}]"
)


class FakeApiError(Exception):
    """An SDK-shaped exception: carries `status_code`, like `openai.APIStatusError`.

    Duck-typed on purpose. `classify_error` must never `import openai`/`import anthropic`
    (`tests/test_minting_driver_clients_import.py` pins that the driver core stays
    importable with both SDKs absent), so the classifier reads `status_code` off whatever
    it is handed — and this fake is exactly what it will see in the field, minus the SDK.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        response: Optional[object] = None,
    ) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if response is not None:
            self.response = response


# ---------------------------------------------------------------------------
# Phase 1.1 — the real Stage-3 error classifies `quota`
# ---------------------------------------------------------------------------


def test_real_stage3_error_with_status_code_classifies_quota() -> None:
    """The shape the live mint actually saw: an SDK error carrying BOTH `status_code=429`
    and the full quota body. This is the case that must never regress."""
    assert classify_error(FakeApiError(STAGE3_QUOTA_ERROR, status_code=429)) == "quota"


def test_real_stage3_error_as_bare_exception_classifies_quota() -> None:
    """The same text with NO `status_code` attribute at all — the shape a recorded
    checkpoint `reason` has once it has been through `str(exc)`. The 429 has to be
    recovered from the message, or the legacy re-arm tool could never classify the 56
    stranded entries."""
    assert classify_error(Exception(STAGE3_QUOTA_ERROR)) == "quota"


# ---------------------------------------------------------------------------
# Phase 1.2 — `retry_after_seconds` reads the provider's hint
# ---------------------------------------------------------------------------


def test_retry_after_seconds_parses_the_real_retry_delay() -> None:
    assert retry_after_seconds(Exception(STAGE3_QUOTA_ERROR)) == 39043.0


def test_retry_after_seconds_prefers_a_numeric_attribute_over_the_message() -> None:
    """A provider that hands us a parsed hint is more trustworthy than a regex over prose."""
    exc = FakeApiError(STAGE3_QUOTA_ERROR, status_code=429)
    exc.retry_after = 12.5
    assert retry_after_seconds(exc) == 12.5


def test_retry_after_seconds_reads_a_retry_after_response_header() -> None:
    exc = FakeApiError(
        "429 slow down",
        status_code=429,
        response=SimpleNamespace(headers={"Retry-After": "30"}),
    )
    assert retry_after_seconds(exc) == 30.0


def test_retry_after_seconds_is_none_when_absent() -> None:
    assert retry_after_seconds(Exception("Error code: 429 - too many requests")) is None


def test_retry_after_seconds_on_a_malformed_hint_returns_none_and_does_not_raise() -> None:
    """A classifier that throws while classifying an error would replace a recoverable
    stop with a crash — the opposite of this aspect's whole purpose. Parse failure is
    `None`, never an exception."""
    assert retry_after_seconds(Exception("{'retryDelay': 'banana'}")) is None


def test_retry_after_seconds_never_raises_on_a_hostile_attribute() -> None:
    """`getattr` on a real SDK object can return anything. A non-numeric `retry_after`
    must degrade to the next source, not blow up."""

    class Hostile(Exception):
        retry_after = object()

    assert retry_after_seconds(Hostile("nothing parseable here")) is None


# ---------------------------------------------------------------------------
# Phase 1.3 — a 429 is `quota` only when the evidence says a period cap
# ---------------------------------------------------------------------------


def test_429_with_a_short_hint_classifies_transient() -> None:
    """Two seconds is a rate-limit blip, not a daily cap: bounded backoff can wait it out."""
    exc = FakeApiError("Error code: 429 - rate limited", status_code=429)
    exc.retry_after = 2.0
    assert classify_error(exc) == "transient"


def test_429_with_no_hint_at_all_classifies_transient() -> None:
    assert classify_error(FakeApiError("Error code: 429 - rate limited", status_code=429)) == (
        "transient"
    )


def test_429_with_a_hint_above_the_threshold_classifies_quota() -> None:
    """The threshold is explicit and encoded, not inferred from the word 'quota'."""
    exc = FakeApiError("Error code: 429 - slow down", status_code=429)
    exc.retry_after = QUOTA_RETRY_THRESHOLD_SECONDS + 1
    assert classify_error(exc) == "quota"


def test_429_with_a_hint_exactly_at_the_threshold_classifies_transient() -> None:
    """Boundary pinned deliberately: the rule is *strictly greater than*, so a provider
    sitting exactly on the threshold is retried rather than stopping the whole mint."""
    exc = FakeApiError("Error code: 429 - slow down", status_code=429)
    exc.retry_after = QUOTA_RETRY_THRESHOLD_SECONDS
    assert classify_error(exc) == "transient"


def test_429_naming_a_period_cap_without_any_hint_classifies_quota() -> None:
    """Belt and braces: the real errors carried both signals, but a provider may give only
    the `RESOURCE_EXHAUSTED` status and no `RetryInfo` at all."""
    exc = FakeApiError(
        "Error code: 429 - {'status': 'RESOURCE_EXHAUSTED'}", status_code=429
    )
    assert classify_error(exc) == "quota"


def test_429_naming_the_daily_quota_id_without_any_hint_classifies_quota() -> None:
    exc = FakeApiError(
        "Error code: 429 - {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel'}",
        status_code=429,
    )
    assert classify_error(exc) == "quota"


# ---------------------------------------------------------------------------
# Phase 1.4 — transport-class errors are transient
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [408, 409, 425, 500, 502, 503, 504])
def test_retryable_status_codes_classify_transient(status: int) -> None:
    assert classify_error(FakeApiError(f"boom {status}", status_code=status)) == "transient"


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("read timed out"),
        ConnectionError("connection reset by peer"),
        OSError("network is unreachable"),
    ],
    ids=["timeout", "connection", "oserror"],
)
def test_transport_exceptions_classify_transient(exc: BaseException) -> None:
    assert classify_error(exc) == "transient"


# ---------------------------------------------------------------------------
# Phase 1.5 — everything else is TERMINAL (the conservative default)
# ---------------------------------------------------------------------------


def test_a_parse_error_classifies_terminal() -> None:
    assert classify_error(ValueError("bad json")) == "terminal"


def test_an_unrecognised_exception_classifies_terminal_not_transient() -> None:
    """PRD Gap 2, asserted explicitly. An unknown error MUST NOT be optimistically
    `transient`: retrying an unrecognised failure into a wall is the exact failure mode
    this aspect exists to prevent, and a subscription-plan cap we have never seen will
    arrive wearing a shape we do not recognise. Conservative in the safe direction —
    `terminal` records `failed` and the batch continues, which is today's behavior."""
    assert classify_error(Exception()) == "terminal"


@pytest.mark.parametrize(
    "status",
    [400, 401, 403, 404, 422],
    ids=["bad-request", "unauthorized", "forbidden", "not-found", "unprocessable"],
)
def test_client_error_statuses_classify_terminal(status: int) -> None:
    """A 401 will never succeed on retry, and retrying it burns the queue just as surely
    as a quota error does."""
    assert classify_error(FakeApiError(f"boom {status}", status_code=status)) == "terminal"


def test_a_non_integer_status_code_does_not_crash_the_classifier() -> None:
    """Duck typing means `status_code` can be anything. Garbage in, `terminal` out."""
    assert classify_error(FakeApiError("weird", status_code="not-a-number")) == "terminal"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Phase 1.6 — `QuotaExhausted` is itself already classified
# ---------------------------------------------------------------------------


def test_quota_exhausted_round_trips_its_retry_hint() -> None:
    exc = QuotaExhausted("daily cap reached", retry_after_seconds=39043.0)

    assert str(exc) == "daily cap reached"
    assert exc.retry_after_seconds == 39043.0
    assert retry_after_seconds(exc) == 39043.0


def test_quota_exhausted_defaults_its_retry_hint_to_none() -> None:
    assert QuotaExhausted("daily cap reached").retry_after_seconds is None


def test_classifying_a_quota_exhausted_is_idempotent() -> None:
    """Re-classification must be a fixed point: `QuotaExhausted` is the classifier's own
    output shape, so feeding it back in can never downgrade it to `terminal` and quietly
    turn a batch stop into a per-instance failure."""
    assert classify_error(QuotaExhausted("daily cap reached")) == "quota"


def test_transient_exhausted_is_a_runtime_error() -> None:
    assert isinstance(TransientExhausted("gave up"), RuntimeError)


# ===========================================================================
# Phase 2 — `RetryingModel` and the sleep seam
# ===========================================================================


class RecordingSleep:
    """A `sleep` double: records each requested delay and returns immediately.

    **The only sleep any test in this file may use.** Asserting on `delays` pins the exact
    backoff *schedule*, which is the thing worth pinning; asserting on elapsed wall time
    would pin nothing useful, take seconds per test, and be flaky on a loaded machine.
    """

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _transient(message: str = "service unavailable") -> FakeApiError:
    """A 503 — unambiguously `transient` under rule 5, with no 429/quota ambiguity."""
    return FakeApiError(message, status_code=503)


def _quota() -> FakeApiError:
    """The real Stage-3 quota shape, in the form the SDK actually raised it."""
    return FakeApiError(STAGE3_QUOTA_ERROR, status_code=429)


def _drive_as_model(model: Model) -> ToolCall | Done:
    """Call `model` through the `Model` protocol's own signature.

    Typed as `Model` deliberately: `Model` is a plain (not `runtime_checkable`) `Protocol`,
    so `isinstance` is not available and would not prove anything anyway. Structural
    conformance is what matters, and this call site is where it is checked — by mypy
    statically, and by the return-type assertion at runtime.
    """
    return model.propose_next([Message(role="user", content="go")])


# ---------------------------------------------------------------------------
# Phase 2.1 — a transient is retried, with an exact backoff schedule
# ---------------------------------------------------------------------------


def test_transient_twice_then_success_returns_the_tool_call() -> None:
    inner = FlakyModel(
        faults=[_transient(), _transient()],
        inner=ScriptedModel([ToolCall(name="read_file", arguments={"path": "a.py"})]),
    )
    sleep = RecordingSleep()
    model = RetryingModel(inner, sleep=sleep)

    result = model.propose_next([Message(role="user", content="go")])

    assert result == ToolCall(name="read_file", arguments={"path": "a.py"})
    assert inner.calls == 3
    assert model.retry_count == 2


def test_backoff_delay_sequence_is_exactly_one_then_two_seconds() -> None:
    """Exponential from `base_delay`, asserted on the recorded SEQUENCE — never on elapsed
    wall time. If someone changes the schedule, this is the test that says so."""
    sleep = RecordingSleep()
    model = RetryingModel(
        FlakyModel(
            faults=[_transient(), _transient()],
            inner=ScriptedModel([Done(reason="ok")]),
        ),
        sleep=sleep,
    )

    model.propose_next([])

    assert sleep.delays == [1.0, 2.0]
    assert DEFAULT_BASE_DELAY_SECONDS == 1.0


def test_backoff_scales_with_an_injected_base_delay() -> None:
    sleep = RecordingSleep()
    model = RetryingModel(
        FlakyModel(
            faults=[_transient(), _transient(), _transient()],
            inner=ScriptedModel([Done(reason="ok")]),
        ),
        max_attempts=4,
        base_delay=0.5,
        sleep=sleep,
    )

    model.propose_next([])

    assert sleep.delays == [0.5, 1.0, 2.0]


# ---------------------------------------------------------------------------
# Phase 2.2 — a transient that never clears is exhausted, not retried forever
# ---------------------------------------------------------------------------


def test_transient_on_every_attempt_raises_transient_exhausted() -> None:
    last = _transient("still down")
    inner = FlakyModel(
        faults=[_transient(), _transient(), last],
        # No `inner`: reaching it would mean a fourth attempt was made, which is the bug
        # this bound exists to prevent.
        inner=None,
    )
    sleep = RecordingSleep()
    model = RetryingModel(inner, sleep=sleep)

    with pytest.raises(TransientExhausted) as exc_info:
        model.propose_next([])

    assert inner.calls == DEFAULT_MAX_ATTEMPTS
    # One sleep BETWEEN each pair of attempts, and none after the last: sleeping after the
    # final failure would burn wall-clock for nothing.
    assert len(sleep.delays) == DEFAULT_MAX_ATTEMPTS - 1
    # The underlying error survives as `__cause__`, so `run_mint`'s recorded reason can
    # still name what actually went wrong rather than just "gave up".
    assert exc_info.value.__cause__ is last


def test_max_attempts_of_one_disables_retrying_entirely() -> None:
    inner = FlakyModel(faults=[_transient()], inner=None)
    sleep = RecordingSleep()
    model = RetryingModel(inner, max_attempts=1, sleep=sleep)

    with pytest.raises(TransientExhausted):
        model.propose_next([])

    assert inner.calls == 1
    assert sleep.delays == []


# ---------------------------------------------------------------------------
# Phase 2.3 — quota raises IMMEDIATELY; the wrapper never waits out a day
# ---------------------------------------------------------------------------


def test_quota_raises_immediately_without_sleeping() -> None:
    """The observed `retryDelay` was 39043s. Retrying is not merely useless, it is how the
    2026-07-24 run fed 56 instances into the wall — so not one attempt, and not one second
    of sleep, is spent on it."""
    inner = FlakyModel(faults=[_quota()], inner=ScriptedModel([Done(reason="unreachable")]))
    sleep = RecordingSleep()
    model = RetryingModel(inner, sleep=sleep)

    with pytest.raises(QuotaExhausted):
        model.propose_next([])

    assert inner.calls == 1
    assert sleep.delays == []
    assert model.retry_count == 0


def test_quota_preserves_the_providers_retry_hint_and_message() -> None:
    model = RetryingModel(
        FlakyModel(faults=[_quota()], inner=None), sleep=RecordingSleep()
    )

    with pytest.raises(QuotaExhausted) as exc_info:
        model.propose_next([])

    # The hint is the operator's whole plan for the rest of the day; the message is what
    # `run_mint` records as the instance's reason, so both have to survive the wrapping.
    assert exc_info.value.retry_after_seconds == 39043.0
    assert "RESOURCE_EXHAUSTED" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None


def test_a_quota_hit_after_a_transient_stops_the_ladder_where_it_stands() -> None:
    """A mixed sequence: the transient is retried, then the quota ends it. The recorded
    delays show exactly one backoff, and no attempt is made after the quota."""
    inner = FlakyModel(faults=[_transient(), _quota()], inner=None)
    sleep = RecordingSleep()
    model = RetryingModel(inner, sleep=sleep)

    with pytest.raises(QuotaExhausted):
        model.propose_next([])

    assert inner.calls == 2
    assert sleep.delays == [1.0]


# ---------------------------------------------------------------------------
# Phase 2.4 — a terminal error propagates completely unchanged
# ---------------------------------------------------------------------------


def test_terminal_error_propagates_as_the_very_same_object() -> None:
    """Identity, not just type. `run_mint`'s existing bare `except Exception` records
    `str(exc)`; if the wrapper substituted its own exception the recorded reason for every
    ordinary failure would silently change shape, and
    `test_batch_error_containment_is_not_weakened` would be testing a different thing."""
    original = ValueError("bad json")
    inner = FlakyModel(faults=[original], inner=None)
    sleep = RecordingSleep()
    model = RetryingModel(inner, sleep=sleep)

    with pytest.raises(ValueError) as exc_info:
        model.propose_next([])

    assert exc_info.value is original
    assert inner.calls == 1
    assert sleep.delays == []


def test_an_unrecognised_error_is_not_retried() -> None:
    """The classifier's conservative default, seen from the wrapper: an error we do not
    understand gets exactly one attempt, never a retry ladder into a wall."""
    inner = FlakyModel(faults=[Exception("something new")], inner=None)
    sleep = RecordingSleep()
    model = RetryingModel(inner, sleep=sleep)

    with pytest.raises(Exception, match="something new"):
        model.propose_next([])

    assert inner.calls == 1
    assert sleep.delays == []


# ---------------------------------------------------------------------------
# Phase 2.5 — the clean path costs nothing
# ---------------------------------------------------------------------------


def test_a_clean_call_invokes_the_inner_model_once_and_never_sleeps() -> None:
    inner = FlakyModel(faults=[], inner=ScriptedModel([Done(reason="all done")]))
    sleep = RecordingSleep()
    model = RetryingModel(inner, sleep=sleep)

    result = model.propose_next([])

    assert result == Done(reason="all done")
    assert inner.calls == 1
    assert sleep.delays == []
    assert model.retry_count == 0


def test_retry_count_accumulates_across_the_whole_session() -> None:
    """`retry_count` is per-instance, not per-call: `run-accounting` wants the total cost
    of one instance's session, so a second flaky turn adds to the first turn's count."""
    inner = FlakyModel(
        faults=[_transient(), None, _transient()],
        inner=ScriptedModel([ToolCall(name="a", arguments={}), Done(reason="ok")]),
    )
    model = RetryingModel(inner, sleep=RecordingSleep())

    model.propose_next([])
    model.propose_next([])

    assert model.retry_count == 2


# ---------------------------------------------------------------------------
# Phase 2.6 — a retried call sends an IDENTICAL request
# ---------------------------------------------------------------------------


class _RaisingFakeOpenAICompletions:
    """`_FakeOpenAICompletions` (`tests/test_minting_driver_clients_mapping.py:95-108`) with
    one addition: a scripted entry that is an **exception instance** is raised instead of
    returned, which is how a provider failure mid-turn is simulated with zero network.

    Copied rather than imported because `tests/` is not an importable package (no
    `__init__.py`), and kept faithful to the original in the one respect that matters: the
    request is appended to `.calls` **before** the scripted outcome is consumed, so a call
    that raises is still recorded. Without that, this file's headline mapping test below
    could not compare the failed request against its retry.
    """

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> object:
        # Same snapshot reasoning as the original: `kwargs["messages"]` is the client's own
        # live list, mutated again right after this returns, so a shallow copy is taken now.
        snapshot = dict(kwargs)
        if "messages" in snapshot:
            snapshot["messages"] = list(snapshot["messages"])  # type: ignore[arg-type]
        self.calls.append(snapshot)
        if not self._outcomes:
            raise AssertionError("fake completions.create called more times than scripted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class RaisingFakeOpenAIClient:
    """Shaped like `openai.OpenAI()`, but a scripted outcome may be an exception."""

    def __init__(self, outcomes: list[object]) -> None:
        self.chat = SimpleNamespace(completions=_RaisingFakeOpenAICompletions(outcomes))


def _openai_tool_call_response(*, call_id: str, name: str, arguments: str) -> SimpleNamespace:
    """The minimal OpenAI response tree `LocalOpenAICompatModel.propose_next` reads."""
    tool_call = SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])


def test_a_retried_propose_next_sends_an_identical_request() -> None:
    """The `_ingest_new_messages` hazard, pinned.

    `LocalOpenAICompatModel.propose_next` (`clients/local_client.py:122-130`) mutates
    `self._seen` and `self._openai_messages` and only THEN calls the API. That ordering is
    the sole reason a retry is safe: on the second attempt the same `messages` list has
    nothing new past `_seen`, so the conversation is rebuilt identically rather than having
    the system+user turns appended twice.

    Reorder the ingest to after the API call — or make it idempotent-by-accident in some
    other way — and a retried request would carry a duplicated conversation. That is a
    silent corruption of the very capture the mint exists to produce, so it is asserted
    directly on the two recorded requests being **equal**.
    """
    client = RaisingFakeOpenAIClient(
        [
            _transient(),
            _openai_tool_call_response(
                call_id="call_1", name="read_file", arguments='{"path": "a.py"}'
            ),
        ]
    )
    inner = LocalOpenAICompatModel(model="local-x", tools=[], client=client)
    sleep = RecordingSleep()
    model = RetryingModel(inner, sleep=sleep)

    result = model.propose_next(
        [Message(role="system", content="sys"), Message(role="user", content="go")]
    )

    assert result == ToolCall(name="read_file", arguments={"path": "a.py"})
    assert len(client.chat.completions.calls) == 2
    assert client.chat.completions.calls[0] == client.chat.completions.calls[1]
    # And specifically: the conversation was not duplicated by the second ingest pass.
    assert [m["role"] for m in client.chat.completions.calls[1]["messages"]] == [
        "system",
        "user",
    ]
    assert sleep.delays == [1.0]


# ---------------------------------------------------------------------------
# Phase 2.7 — the wrapper is still a `Model`
# ---------------------------------------------------------------------------


def test_retrying_model_satisfies_the_model_protocol() -> None:
    """It is installed at the `ModelFactory` boundary and handed straight to `run_task`,
    which knows only the `Model` protocol — so conformance is the whole contract."""
    model = RetryingModel(ScriptedModel([Done(reason="ok")]), sleep=RecordingSleep())

    step = _drive_as_model(model)

    assert isinstance(step, (ToolCall, Done))


def test_retrying_model_wraps_any_model_including_a_bare_scripted_one() -> None:
    """No `FlakyModel` in sight: the wrapper adds nothing to a model that never fails, so a
    plain `ScriptedModel` passes through step for step."""
    steps: list[ToolCall | Done] = [
        ToolCall(name="read_file", arguments={"path": "a.py"}),
        Done(reason="done"),
    ]
    model = RetryingModel(ScriptedModel(steps), sleep=RecordingSleep())

    assert [model.propose_next([]) for _ in steps] == steps
    assert model.retry_count == 0


# ---------------------------------------------------------------------------
# Phase 2.8 — `run-accounting`: the wrapper counts requests and exposes the client
#
# `retry_count` alone does not say what an instance cost. `request_count` does: it is the
# number of attempts that actually reached the provider, retries included, which is the
# quantity a daily cap is measured in. Token usage lives one layer down on the concrete
# client, so the wrapper exposes the object it wraps rather than growing a second protocol
# method — `Model` stays a ONE-METHOD protocol.
# ---------------------------------------------------------------------------


def test_request_count_counts_every_attempt_that_reached_the_provider() -> None:
    """Two transients then a success is THREE requests, not one.

    That is the entire point of counting here rather than counting turns: retries cost
    quota, and the 250-per-day cap that burned the queue counts attempts, not successes.
    """
    inner = FlakyModel(
        faults=[_transient(), _transient()],
        inner=ScriptedModel([Done(reason="ok")]),
    )
    model = RetryingModel(inner, max_attempts=3, sleep=RecordingSleep())

    model.propose_next([])

    assert model.request_count == 3
    assert model.retry_count == 2
    assert inner.calls == 3


def test_request_count_starts_at_zero_and_accumulates_across_the_session() -> None:
    """Per-instance, like `retry_count`: one wrapper per instance, so this is the total."""
    model = RetryingModel(
        ScriptedModel([ToolCall(name="a", arguments={}), Done(reason="ok")]),
        sleep=RecordingSleep(),
    )

    assert model.request_count == 0
    model.propose_next([])
    model.propose_next([])
    assert model.request_count == 2


def test_a_quota_stop_still_counts_the_request_that_hit_the_wall() -> None:
    """The rejected request was spent. A stop-loss that ignored it would under-count.

    `retry_count` stays 0 — nothing was retried — so the two counters stay honestly
    different quantities rather than one being derivable from the other.
    """
    model = RetryingModel(FlakyModel(faults=[_quota()], inner=None), sleep=RecordingSleep())

    with pytest.raises(QuotaExhausted):
        model.propose_next([])

    assert model.request_count == 1
    assert model.retry_count == 0


def test_the_wrapper_exposes_the_client_it_wraps() -> None:
    """`inner` is how `batch.py` reads token usage without knowing the provider.

    D1: accounting accumulates on the model object and `Model` stays a one-method
    protocol. Token usage originates in the concrete client (only it sees `response.usage`),
    so the wrapper hands the client over rather than proxying a second method for it.
    """
    client = LocalOpenAICompatModel(model="local-x", tools=[], client=object())
    model = RetryingModel(client, sleep=RecordingSleep())

    assert model.inner is client
    assert model.inner.provider == "openai-compat"
    assert model.inner.model == "local-x"


def test_the_wrapper_reports_no_dollar_amount_of_any_kind() -> None:
    """D4, pinned at the source: there is no price field anywhere in the accounting.

    Under a subscription there is no per-token price, so a dollar figure would be
    fabricated precision — the exact thing this project exists not to do. If a metered key
    is ever used, price is applied at REPORT time from a stated rate, never baked into the
    ledger. Asserted so a later change cannot quietly add one.
    """
    model = RetryingModel(ScriptedModel([Done(reason="ok")]), sleep=RecordingSleep())
    model.propose_next([])

    forbidden = ("cost", "price", "usd", "dollar", "spend_usd")
    names = [name for name in dir(model) if not name.startswith("__")]
    assert not [name for name in names if any(word in name.lower() for word in forbidden)]
