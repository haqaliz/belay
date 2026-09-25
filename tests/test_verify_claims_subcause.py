"""A3 evaluator: a `NO_CHECK_AUTHOR` verdict carries the author's sub-cause.

`evaluate_claim` reads WHY the author produced no check — by attribute
(`last_abstention`), so the `CheckAuthor` protocol is unchanged — and writes it into the
UNVERIFIED verdict's `expected` dict as `sub_cause` / `sub_cause_detail`, plus a short
suffix in the message. An in-process author that exposes nothing reads as
`AUTHOR_DECLINED` (returned `None`) or `AUTHOR_RAISED` (raised), which is exactly what is
observable about it.

The sub-cause refines the reason, never the status: every case here is still UNVERIFIED
`NO_CHECK_AUTHOR`, and the keys appear on that cause ONLY — every other decision-table
row (other causes, FAIL, silence) is byte-unchanged. The decision-table rows and fakes are
reused from `tests/test_verify_claims.py`, not copied.
"""

from __future__ import annotations

import sys

import pytest

from belay.verify import author as author_mod
from belay.verify import claims
from belay.verify.claims import (
    CAUSE_NO_CHECK_AUTHOR,
    SUB_CAUSE_AUTHOR_DECLINED,
    SUB_CAUSE_AUTHOR_RAISED,
    SUB_CAUSE_AUTHOR_REPORTED_ERROR,
    SUB_CAUSE_AUTHOR_TIMED_OUT,
    Abstention,
    RecordingAuthor,
)
from belay.verify.verdict import Status
from test_verify_claims import ROWS, _assert_unverified, _use_runner  # the rows, reused


class DecliningAuthor:
    """An in-process author that returns None and exposes no reason."""

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        return None


class ReportingAuthor:
    """An author that returns None and says why, the way `SubprocessAuthor` does."""

    def __init__(self, abstention):
        self.last_abstention = abstention

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        return None


class RaisingAuthor:
    """An in-process author that raises."""

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        raise RuntimeError("the model client broke")


def _evaluate(tmp_path, subject):
    kwargs = dict(ROWS["no-check-author"](tmp_path))
    kwargs["author"] = subject
    verdict = claims.evaluate_claim(**kwargs)
    _assert_unverified(verdict, cause=CAUSE_NO_CHECK_AUTHOR)
    return verdict


WRAPS = pytest.mark.parametrize(
    "wrap", [lambda a: a, RecordingAuthor], ids=["bare", "recording"]
)


# --- the three observable shapes, bare and through RecordingAuthor (spec AC 5, 8) ------


@WRAPS
def test_reported_abstention_is_carried_into_the_verdict(tmp_path, wrap):
    subject = wrap(ReportingAuthor(Abstention(SUB_CAUSE_AUTHOR_TIMED_OUT, "60.0s")))
    verdict = _evaluate(tmp_path, subject)
    assert verdict.expected["sub_cause"] == SUB_CAUSE_AUTHOR_TIMED_OUT
    assert verdict.expected["sub_cause_detail"] == "60.0s"
    assert "(AUTHOR_TIMED_OUT: 60.0s)" in verdict.message
    assert verdict.status is Status.UNVERIFIED


@WRAPS
def test_an_author_without_a_reason_declined(tmp_path, wrap):
    verdict = _evaluate(tmp_path, wrap(DecliningAuthor()))
    assert verdict.expected["sub_cause"] == SUB_CAUSE_AUTHOR_DECLINED
    assert verdict.expected["sub_cause_detail"] == ""
    assert "(AUTHOR_DECLINED)" in verdict.message


@WRAPS
def test_a_raising_author_names_the_exception_type(tmp_path, wrap):
    verdict = _evaluate(tmp_path, wrap(RaisingAuthor()))
    assert verdict.expected["sub_cause"] == SUB_CAUSE_AUTHOR_RAISED
    assert verdict.expected["sub_cause_detail"] == "RuntimeError"
    assert "(AUTHOR_RAISED: RuntimeError)" in verdict.message


@WRAPS
def test_a_reason_of_the_wrong_type_is_treated_as_absent(tmp_path, wrap):
    verdict = _evaluate(tmp_path, wrap(ReportingAuthor("timed out")))
    assert verdict.expected["sub_cause"] == SUB_CAUSE_AUTHOR_DECLINED


@WRAPS
def test_a_raising_author_ignores_a_stale_reason(tmp_path, wrap):
    class StaleRaiser(RaisingAuthor):
        last_abstention = Abstention(SUB_CAUSE_AUTHOR_TIMED_OUT, "60s")

    verdict = _evaluate(tmp_path, wrap(StaleRaiser()))
    assert verdict.expected["sub_cause"] == SUB_CAUSE_AUTHOR_RAISED


def test_the_real_subprocess_author_reaches_the_verdict(tmp_path):
    code = 'import sys; sys.stdout.write(\'{"error": "model declined"}\')'
    subject = RecordingAuthor(author_mod.SubprocessAuthor((sys.executable, "-c", code)))
    verdict = _evaluate(tmp_path, subject)
    assert verdict.expected["sub_cause"] == SUB_CAUSE_AUTHOR_REPORTED_ERROR
    assert verdict.expected["sub_cause_detail"] == "model declined"
    assert subject.last_check is None


# --- RecordingAuthor forwards the inner reason, live -----------------------------------


def test_recording_author_reads_the_inner_reason_live():
    inner = ReportingAuthor(None)
    recording = RecordingAuthor(inner)
    assert recording.last_abstention is None
    inner.last_abstention = Abstention(SUB_CAUSE_AUTHOR_TIMED_OUT, "1s")
    assert recording.last_abstention == inner.last_abstention
    assert RecordingAuthor(DecliningAuthor()).last_abstention is None


# --- the keys live on NO_CHECK_AUTHOR only (spec AC 7) ----------------------------------


@pytest.mark.parametrize("row", sorted(ROWS))
def test_sub_cause_appears_only_on_no_check_author(row, tmp_path, monkeypatch):
    kwargs = _use_runner(monkeypatch, dict(ROWS[row](tmp_path)))
    verdict = claims.evaluate_claim(**kwargs)
    if verdict is None:
        return
    expected = verdict.expected if isinstance(verdict.expected, dict) else {}
    is_no_author = expected.get("cause") == CAUSE_NO_CHECK_AUTHOR
    assert ("sub_cause" in expected) is is_no_author
    assert ("sub_cause_detail" in expected) is is_no_author
    if not is_no_author:
        assert "AUTHOR_" not in verdict.message
