"""The quota circuit breaker: tell a provider's error kinds apart, and act on the difference.

On 2026-07-24 a Stage-3 mint hit Google's 250-requests-per-day cap and destroyed **56
instances of denominator in 3m48s**. Nothing crashed; that is the point. `batch.py`'s single
bare `except Exception` recorded `str(exc)` as `failed` and moved on to the next instance,
which hit the same wall, and so on down the queue — and because `checkpoint.is_done` counts
`failed` as *done*, a resume would skip all 56 forever. The provider's own `retryDelay` was
**39043s (≈10h50m)**: no bounded backoff could ever have reached it. What was lost was not a
retry, it was the **queue**.

So this module's job is to answer one question about an exception — *"is waiting going to
help, and for how long?"* — and it answers it in three buckets:

| kind | meaning | what the caller does |
|---|---|---|
| `quota` | a daily/period cap; the wait is **hours** | **stop the batch**, leave the rest eligible |
| `transient` | a rate-limit or transport blip; the wait is **seconds** | bounded retry with backoff |
| `terminal` | everything else | record `failed` and continue (today's behavior, unchanged) |

**An unrecognised error classifies `terminal`, never `transient`** (PRD Gap 2). Retrying an
error we do not understand is how the queue got burned in the first place, and the next
unknown shape we meet will be a subscription-plan cap we have never seen. Conservative in
the safe direction: a `terminal` verdict costs one instance and keeps the batch running.

**Duck-typed only.** No `import openai` / `import anthropic` anywhere in this module, not even
lazily: `tests/test_minting_driver_clients_import.py` pins that the driver core stays
importable with both SDKs absent, and that contract is load-bearing for the default CI env.
Classification reads `getattr(exc, "status_code", None)` and inspects the message text, which
is also what makes it usable on a *recorded* `reason` string — the legacy re-arm tool has no
exception object, only the text `str(exc)` left behind in a checkpoint.

Stdlib only (`re`, `time`); no clock is read except through the injected `sleep` seam.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Literal, Optional

from eval.minting_driver.model import Done, Message, Model, ToolCall

#: The three buckets. A `Literal` rather than an enum so a caller can compare against a
#: plain string (`kind == "quota"`) and so a recorded value stays JSON-native.
ErrorKind = Literal["quota", "transient", "terminal"]

#: Above this many seconds, a 429's own retry hint means "come back another day" and no
#: bounded backoff can wait it out — so it is a `quota` stop, not a `transient` retry. The
#: rule is *strictly greater than*, so a provider sitting exactly on the boundary is still
#: retried: stopping the whole mint is the more expensive mistake of the two.
#:
#: 600s (10 min) sits far above any rate-limit blip (the observed short hints are seconds)
#: and far below the observed period cap (39043s), so the two populations are not close to
#: this line. It is encoded explicitly rather than inferred from the word "quota" in the
#: prose, because prose is the provider's to change and a threshold is ours.
QUOTA_RETRY_THRESHOLD_SECONDS = 600.0

#: HTTP statuses worth another attempt: request timeouts, a lock/conflict, "too early", and
#: the 5xx family. NOT 4xx auth/shape errors — a 401 will never succeed on retry, and
#: retrying it burns the queue just as surely as a quota error does.
_RETRYABLE_STATUSES = frozenset({408, 409, 425, 500, 502, 503, 504})

#: A bare `429` token in the message, used ONLY when the exception carries no usable
#: `status_code` attribute — the shape a recorded checkpoint `reason` has, since it is just
#: `str(exc)`. Word-bounded so it cannot match inside a longer number (e.g. a request id).
#: If a `status_code` IS present it wins outright: a 401 whose body happens to mention 429
#: must stay a 401.
_HTTP_429_TOKEN = re.compile(r"\b429\b")

#: Lowercased substrings that name a *period* cap rather than a momentary rate limit. Belt
#: and braces alongside the retry-hint threshold: the real Stage-3 errors carried BOTH
#: signals, but a provider may hand us only one, and a 429 that says `RESOURCE_EXHAUSTED`
#: with no `RetryInfo` at all is still a day-long stop.
_PERIOD_CAP_TOKENS = (
    "resource_exhausted",
    "generaterequestsperdayperprojectpermodel",
    "quotaid",
    "per_day",
    "_per_model_per_day",
)

#: Google's `RetryInfo` shape as it survives into `str(exc)`: `'retryDelay': '39043s'`.
#: Quotes are optional on both sides so a JSON-ish (`"retryDelay": "39043s"`) or bare
#: rendering parses too. The seconds value must be digits — `'retryDelay': 'banana'` simply
#: does not match, which yields `None`, never an exception.
_RETRY_DELAY = re.compile(r"""['"]?retryDelay['"]?\s*:\s*['"]?\s*(\d+(?:\.\d+)?)s\b""")


class QuotaExhausted(RuntimeError):
    """A provider quota / period cap: the wait is hours, so retrying is useless.

    Carries `retry_after_seconds` when the provider gave a hint, so the batch can report
    *when* it stopped being worth trying — that number is the operator's whole plan for the
    rest of the day. `None` means the provider said nothing, not "retry immediately".

    This is a **control-flow signal, not a failure**: `run_mint` catches it ahead of its bare
    `except Exception`, records the instance as having produced no observation, and stops.
    """

    def __init__(self, message: str, *, retry_after_seconds: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TransientExhausted(RuntimeError):
    """A transient error that survived every bounded retry attempt.

    Distinct from the underlying error (which is kept as `__cause__`) because the *caller's*
    response differs: nothing was observed for this instance, so it stays re-armable — but
    unlike `QuotaExhausted` it is no reason to stop the batch, since the next instance may
    well succeed.
    """


def _safe_getattr(obj: object, name: str) -> object:
    """`getattr(obj, name, None)`, but tolerant of a property that raises.

    Real SDK exception objects expose computed attributes; one of them raising while we are
    busy classifying an error would replace a recoverable stop with a crash — precisely the
    outcome this module exists to prevent. Absent and exploding are treated alike: `None`.
    """
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def _message(exc: BaseException) -> str:
    """`str(exc)`, guarded the same way `_safe_getattr` is, and never `None`."""
    try:
        return str(exc)
    except Exception:
        return ""


def _coerce_seconds(value: object) -> Optional[float]:
    """A duck-typed retry hint -> non-negative seconds, or `None` if it is not one.

    `bool` is excluded deliberately even though it is an `int` subclass: a `retry_after` of
    `True` is a flag someone set, not a one-second wait. A negative value is nonsense and is
    rejected rather than silently clamped, so it falls through to the next hint source.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        try:
            seconds = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return None if seconds < 0 else seconds


def retry_after_seconds(exc: BaseException) -> Optional[float]:
    """The provider's own "come back in N seconds" hint, or `None` if it gave none.

    Sources are tried most-trustworthy first: a numeric attribute the SDK already parsed for
    us, then a `Retry-After` response header, then — because this is the shape the real
    Stage-3 failures had, and the only shape a *recorded* `reason` string can carry — a
    `'retryDelay': '39043s'` substring in the message.

    **This function never raises.** Every parse failure, hostile attribute, and unexpected
    type degrades to `None`.
    """
    # `retry_after_seconds` first so a `QuotaExhausted` we produced ourselves round-trips its
    # own hint; `retry_after` is the name the OpenAI/Anthropic SDKs use.
    for attribute in ("retry_after_seconds", "retry_after"):
        seconds = _coerce_seconds(_safe_getattr(exc, attribute))
        if seconds is not None:
            return seconds

    headers = _safe_getattr(_safe_getattr(exc, "response"), "headers")
    if headers is not None:
        # HTTP header names are case-insensitive but a plain `dict` is not, so try both
        # spellings rather than assuming the SDK wrapped them in a case-folding mapping.
        for key in ("retry-after", "Retry-After"):
            try:
                raw = headers.get(key)  # type: ignore[attr-defined]
            except Exception:
                raw = None
            seconds = _coerce_seconds(raw)
            if seconds is not None:
                return seconds

    match = _RETRY_DELAY.search(_message(exc))
    if match is None:
        return None
    return _coerce_seconds(match.group(1))


def _status_code(exc: BaseException) -> Optional[int]:
    """The HTTP status the exception declares, or `None` if it declares none usable.

    Duck-typed on `status_code` — the attribute both `openai.APIStatusError` and
    `anthropic.APIStatusError` expose — with no SDK import. Anything that is not an honest
    integer (a `bool`, an object, an unparseable string) reads as `None` and the caller falls
    back to the message, rather than the classifier crashing on garbage.
    """
    raw = _safe_getattr(exc, "status_code")
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            return None
    return None


def _names_a_period_cap(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in _PERIOD_CAP_TOKENS)


def classify_error(exc: BaseException) -> ErrorKind:
    """Map a provider exception to `"quota"` / `"transient"` / `"terminal"`.

    Rules, in order:

    1. An already-classified `QuotaExhausted` is `quota` — re-classification is a fixed
       point, so feeding our own output back in can never quietly downgrade a batch stop.
    2. A 429 whose retry hint exceeds `QUOTA_RETRY_THRESHOLD_SECONDS` is `quota`.
    3. A 429 whose message names a period cap (`RESOURCE_EXHAUSTED`, a daily `quotaId`, …)
       is `quota`, even with no hint at all.
    4. Any other 429 — short hint, or none — is `transient`.
    5. A retryable status (`_RETRYABLE_STATUSES`) or a transport-level exception
       (`TimeoutError` / `ConnectionError` / `OSError`) is `transient`.
    6. **Everything else is `terminal`.**

    Note what is deliberately absent from rule 5: `TransientExhausted` classifies `terminal`,
    because by construction its retries are already spent — re-entering the retry ladder with
    it would multiply the attempts, not bound them.
    """
    if isinstance(exc, QuotaExhausted):
        return "quota"

    status = _status_code(exc)
    message = _message(exc)

    # A declared status always wins; the message token is a fallback for the no-attribute
    # case only (a `reason` string recovered from a checkpoint), never an override.
    if status == 429 or (status is None and _HTTP_429_TOKEN.search(message)):
        hint = retry_after_seconds(exc)
        if hint is not None and hint > QUOTA_RETRY_THRESHOLD_SECONDS:
            return "quota"
        if _names_a_period_cap(message):
            return "quota"
        return "transient"

    if status is not None and status in _RETRYABLE_STATUSES:
        return "transient"

    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "transient"

    return "terminal"


#: Total attempts per `propose_next`, INCLUDING the first — so the default spends at most
#: two retries. Kept small on purpose: both SDKs already retry internally (`max_retries=2`,
#: honoring `retry-after`, unoverridden at `clients/local_client.py:76` and
#: `clients/anthropic_client.py:75`), so every attempt here stacks on top of an existing
#: invisible layer and the observed 429s were *already* post-retry.
DEFAULT_MAX_ATTEMPTS = 3

#: First backoff, in seconds; each subsequent one doubles it.
DEFAULT_BASE_DELAY_SECONDS = 1.0


class RetryingModel:
    """A `Model` wrapper that retries transients and turns a quota cap into a stop signal.

    Installed at the `ModelFactory` boundary in `entrypoint.make_model_factory`, which is
    the narrowest seam that stays inside `eval/`. Two properties fall out of that placement
    and **must not be given up by moving this logic**:

    - **It structurally cannot retry a `tools/call`.** This wraps `Model.propose_next` and
      nothing else; the tool call is a different object entirely, issued at `loop.py:117`.
      Re-sending a `tools/call` would duplicate a real side effect against the workspace and
      corrupt the very capture the mint exists to produce. Do not lift this into `loop.py`
      or `session.py` — `loop.py:11-12`'s "no retries" claim stays literally true.
    - **It introduces no concurrency.** A blocking `sleep` on the single thread is correct:
      `StdioMcp` is not thread-safe (`transport.py:212-213`), and one-call-in-flight is R7
      by construction.

    `sleep` is injected so tests assert on the recorded *sequence* of requested delays
    rather than on elapsed wall time. It is the only nondeterminism this module has.
    """

    def __init__(
        self,
        inner: Model,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1; got {max_attempts!r}")
        self._inner = inner
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._sleep = sleep
        self._retry_count = 0

    @property
    def retry_count(self) -> int:
        """Retries spent across this instance's WHOLE session, not just the last call.

        One wrapper is built per instance (`entrypoint.make_model_factory` constructs it
        inside the factory, never hoisted), so this is the per-instance total `run-accounting`
        wants. A hoisted wrapper would silently accumulate across instances.
        """
        return self._retry_count

    def propose_next(self, messages: list[Message]) -> ToolCall | Done:
        last_transient: Optional[BaseException] = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._inner.propose_next(messages)
            except Exception as exc:
                # `Exception`, not `BaseException`: a `KeyboardInterrupt` or `SystemExit`
                # must abort the mint immediately, never be classified, retried, or turned
                # into a checkpoint disposition.
                kind = classify_error(exc)

                if kind == "quota":
                    if isinstance(exc, QuotaExhausted):
                        # Already the signal we would construct. Re-wrapping would only
                        # bury the original traceback one layer deeper.
                        raise
                    raise QuotaExhausted(
                        str(exc), retry_after_seconds=retry_after_seconds(exc)
                    ) from exc

                if kind == "terminal":
                    # Re-raised UNCHANGED — the same object, not a copy and not a wrapper —
                    # so `run_mint`'s existing bare `except Exception` records exactly the
                    # `str(exc)` it records today. Anything else would silently change the
                    # recorded reason of every ordinary failure.
                    raise

                last_transient = exc
                if attempt == self._max_attempts:
                    break
                self._retry_count += 1
                # Exponential from `base_delay`: 1s, 2s, 4s, … The sleep happens BETWEEN
                # attempts and never after the last one, which would burn wall-clock for a
                # retry that is not going to happen.
                self._sleep(self._base_delay * 2 ** (attempt - 1))

        raise TransientExhausted(
            f"gave up after {self._max_attempts} attempt(s); last error: {last_transient}"
        ) from last_transient


__all__ = [
    "DEFAULT_BASE_DELAY_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "QUOTA_RETRY_THRESHOLD_SECONDS",
    "ErrorKind",
    "QuotaExhausted",
    "RetryingModel",
    "TransientExhausted",
    "classify_error",
    "retry_after_seconds",
]
