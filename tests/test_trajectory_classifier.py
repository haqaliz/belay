"""A1 / trajectory: the claim classifier — verification vs named abstentions.

`classify_claim_text` is the only prose-touching component of the trajectory rule, so the
fixtures here are written BOTH ways (spec §2): claims that must classify as verification,
and claims that must abstain — completion-shaped, ambiguous, and empty. The classifier
must never manufacture a claim: an unsupported text abstains with a named classification,
and the two catastrophic failure modes are each pinned by a near-miss — too narrow
("tests all pass" must still fire) and too wide ("tests written" must not).

The precedence rule is pinned here too: verification is checked first and wins outright,
so "all done and all tests pass" is a VERIFICATION claim, never an abstention.

Deterministic, no network: the classifier is pure `re` over the text, and the
double-invocation test pins that two calls on one text return identical classifications.
"""

from __future__ import annotations

import pytest

from belay.verify.trajectory import ClaimClassification, classify_claim_text

# --- 1. Verification claims fire (must classify) -----------------------------

VERIFICATION_TEXTS = [
    "all tests pass",
    "the fix works",
    "it's fixed now",
    "done — the tests are green",
    "verified: the suite runs green",
    "the failing test now passes",
    "all done and all tests pass",
    "All tests pass!",
    "tests all pass",
    "passes the tests",
    "the tests are green",
]


@pytest.mark.parametrize("text", VERIFICATION_TEXTS)
def test_verification_claim_classifies(text: str) -> None:
    """A task-correctness assertion is a verification claim, never an abstention."""
    assert classify_claim_text(text) is ClaimClassification.VERIFICATION


# --- 2. Completion shapes abstain (control/completion shapes) ----------------

COMPLETION_TEXTS = [
    "file written",
    "task done",
    "wrote BELAY_CONTROL.txt",
    "finished",
    "I have completed the task",
    "tests written",
    "the fix is written",
]


@pytest.mark.parametrize("text", COMPLETION_TEXTS)
def test_completion_claim_abstains(text: str) -> None:
    """Work-done prose is NOT a verification claim — it abstains as COMPLETION.

    "tests written" and "the fix is written" are the too-wide near-misses: they carry
    the words "tests"/"fix" a naive vocabulary would hang a success claim on, but the
    sentence asserts the work was WRITTEN, never that it is correct.
    """
    assert classify_claim_text(text) is ClaimClassification.COMPLETION


# --- 3. Ambiguous text abstains -----------------------------------------------

AMBIGUOUS_TEXTS = [
    "done",
    "all done",
    "see the summary below",
    "the fix still does not work",
]


@pytest.mark.parametrize("text", AMBIGUOUS_TEXTS)
def test_ambiguous_claim_abstains(text: str) -> None:
    """Text with no verification signal and no completion-vocabulary signal abstains.

    Bare "done" is the plan's own ambiguous example: it is BOTH the completion word and
    the success-claim word, so neither vocabulary may claim it. A negative statement
    ("does not work") is a failure report, not a success claim, and must not fire either.
    """
    assert classify_claim_text(text) is ClaimClassification.AMBIGUOUS


# --- 4. No text abstains -------------------------------------------------------

NO_TEXT_TEXTS = ["", "   ", "\t\n "]


@pytest.mark.parametrize("text", NO_TEXT_TEXTS)
def test_empty_text_abstains(text: str) -> None:
    """Empty/whitespace text is its own named cause, never a fabricated claim."""
    assert classify_claim_text(text) is ClaimClassification.NO_TEXT


# --- 5. Precedence: verification wins over completion -------------------------

def test_verification_wins_over_completion() -> None:
    """A text that asserts correctness AND completion is a verification claim.

    The precedence is pinned: "all done and all tests pass" must classify VERIFICATION,
    never AMBIGUOUS and never COMPLETION — a verification claim is judged as the
    strongest thing it says, and a surrounding completion phrase cannot downgrade it.
    """
    assert (
        classify_claim_text("all done and all tests pass")
        is ClaimClassification.VERIFICATION
    )
    assert (
        classify_claim_text("task done and the suite runs green")
        is ClaimClassification.VERIFICATION
    )


# --- 6. Deterministic -----------------------------------------------------------

def test_classifier_is_deterministic() -> None:
    """Two calls on one text return the same classification, always."""
    text = "the failing test now passes"
    assert (
        classify_claim_text(text)
        is classify_claim_text(text)
        is ClaimClassification.VERIFICATION
    )
