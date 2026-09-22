"""Aspect `ledger-command` — the `belay triage-ledger` command contract, RED-first.

The command is a PURE RE-RENDER: it reads ONE stored `belay verify --json`
document (schema 1) and renders the C10 calibration measurement — the reliability
curve (confidence deciles vs the observed violation rate), the ECE, and the
decision-relevant sweep (at each candidate threshold, how many true violations
would have been skipped and how much budget saved). No replay, no re-verification,
no clock read — the same document must re-render byte-identically, and a document
built by the REAL CLI (the demo capture verified with a stub triage author in
shadow mode) must render its honest denominator: 7 turns, 7 decided, 0 excluded,
0 violations.

The honesty contract the tests pin:

- **The violation column is the per-turn reduced FAIL** (WARN folded with PASS,
  the corpus precedent). UNVERIFIED turns are EXCLUDED — there is no verdict to
  calibrate against — and counted; `"skipped": true` rows (the budgeted-mode
  marker) are excluded the same way and counted; abstentions (turns with no score
  row) are absent, and unscored turns are stated when any exist.
- **A document with no `triage` section is fail-closed (exit 2, named)** — a
  ledger over a run that never ran triage would be a fabrication.
- **A zero-denominator column refuses a rate** (exit 0, the INSTRUMENT SUSPECT
  shape): the named `NO_DECIDED_ROWS` refusal renders with NO rates, never a
  fabricated 0%.
- **Byte-identical re-render**: the same document twice renders the same bytes,
  text and `--json`.
- **Parity**: the flag-parity `--json` row must declare `triage-ledger` in the
  same commit as the command — the test below is red until the registry is
  widened.

The synthetic fixture uses binary-exact scores/confidences (x/16 or 1.0) so every
pinned value is exactly representable — the assertions are string-equalities, not
tolerances. The demo half is a real re-execution of the ~44s `run_process` turns
and is darwin-gated exactly like the refutation's (`tests/test_refutation_triage.py:67-73`).
"""

from __future__ import annotations

import contextlib
import io
import json
import shlex
import sys
from pathlib import Path

import pytest

from belay import cli

REQUIRES_CAPTURE = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: the demo capture's re-execution runs inside the "
        "macOS Seatbelt sandbox; the Linux side is measured in tests/test_docker_inimage.py"
    ),
)


def _run_cli(argv: list[str]) -> tuple[int, str]:
    """`belay <argv...>` through the REAL parser, returning (exit code, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


def _stub_triage_author(marker: Path) -> str:
    """One inline triage command: records each invocation on disk and answers a
    FIXED score — deterministic, no model, no network. The marker is the
    anti-vacuity proof that the author really ran (one char per turn)."""
    code = (
        "import sys, json; "
        f"open({str(marker)!r}, 'a').write('1'); "
        'sys.stdout.write(json.dumps({"score": 0.5, "confidence": 0.9})); '
        "sys.exit(0)"
    )
    return f"{sys.executable} -c {shlex.quote(code)}"


# --- (1) REAL-DATA MECHANICS: the demo capture, verified by the real CLI ---------------


@pytest.fixture(scope="module")
def demo_ledger_document(tmp_path_factory) -> dict:
    """The committed demo capture verified ONCE through the REAL CLI with a stub
    triage author (shadow mode, `--json`) — the stored document `belay triage-ledger`
    re-renders. Built by execution, never hand-written: the acceptance is that the
    command's mechanics hold on real data (7 turns, all PASS).
    """
    from test_demo_capture import (
        SERVER,
        _capture_trace,
        _manifest_dir,
        _recorded_source_root,
    )

    workdir = tmp_path_factory.mktemp("triage-ledger-demo")
    marker = workdir / "triage-invoked"

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(
            [
                "verify",
                str(_capture_trace()),
                "--manifest-dir",
                str(_manifest_dir()),
                "--timeout",
                "300",
                "--json",
                "--triage-author",
                _stub_triage_author(marker),
                "--server",
                sys.executable,
                str(SERVER),
                _recorded_source_root(),
            ]
        )
    text = buf.getvalue()
    assert rc == 0, text
    doc = json.loads(text)

    # Anti-vacuity: the stub author really ran, once per turn, observed on disk.
    assert marker.read_text(encoding="utf-8") == "1" * 7, (
        f"the stub triage author must have run once per turn, got {marker.read_text()!r}"
    )
    assert doc["triage"] == {
        "mode": "shadow",
        "skipped": 0,
        "scores": [
            {"ordinal": n, "score": 0.5, "confidence": 0.9}
            for n in range(len(doc["turns"]))
        ],
    }, doc["triage"]
    assert len(doc["turns"]) == 7, doc["turns"]
    assert all(turn["status"] == "PASS" for turn in doc["turns"]), doc["turns"]
    return doc


@REQUIRES_CAPTURE
def test_demo_capture_renders_zero_violations_with_the_denominator(
    demo_ledger_document, tmp_path
) -> None:
    """Real data, honest denominator: `belay triage-ledger <doc>` on the demo
    capture verified with a stub triage author renders 7 turns, 7 decided,
    0 excluded, 0 violations, exit 0."""
    doc_path = tmp_path / "verify.json"
    doc_path.write_text(json.dumps(demo_ledger_document), encoding="utf-8")

    rc, text = _run_cli(["triage-ledger", str(doc_path)])

    assert rc == 0, text
    assert "turns: 7 total, 7 decided, 0 excluded (0 UNVERIFIED, 0 skipped)" in text, text
    assert "violations: 0/7 = 0.0%" in text, text
    assert "NO_DECIDED_ROWS" not in text, text


# --- (2) EXACT OUTPUT: a synthetic document pins every rendered value ----------------


def _synthetic_document() -> dict:
    """A hand-written schema-1 verify document with KNOWN rows, modeled on
    `tests/fixtures/verify_json_snapshot.json`'s structure. Rows 0-7 are the
    calibration-math fixture (binary-exact confidences, x/16 or 1.0); row 8 is an
    UNVERIFIED turn with a score; row 9 is a budgeted-mode SKIPPED row
    (`"skipped": true`, UNVERIFIED-by-budget); turn 10 is an unscored abstention.

        row 0: score 0.1  conf 0.0625  PASS         -> decile 0
        row 1: score 0.2  conf 0.25    FAIL         -> decile 2
        row 2: score 0.4  conf 0.4375  FAIL         -> decile 4
        row 3: score 0.4  conf 0.5625  PASS         -> decile 5  (ties with row 2)
        row 4: score 0.6  conf 0.6875  FAIL         -> decile 6
        row 5: score 0.7  conf 0.875   FAIL         -> decile 8
        row 6: score 0.8  conf 0.875   PASS         -> decile 8
        row 7: score 0.9  conf 1.0     FAIL         -> decile 9
        row 8: score 0.5  conf 0.5     UNVERIFIED   -> EXCLUDED (counted)
        row 9: score 0.3  conf 0.3     skipped:true -> EXCLUDED (counted)
        turn 10: PASS, no score row                  -> absent (unscored)

    Decided = 8 rows (5 FAIL, 3 PASS); violations = 5/8 = 62.5%; deciles 1, 3 and
    7 are empty ("no data"); ECE = 0.375 (the calibration-math pin, rows 0-7
    identical). All asserted values are computed by hand here, never by the code
    under test.
    """
    return {
        "schema": 1,
        "trace": "demo/trace-0.jsonl",
        "turns": [
            {"ordinal": 0, "tool": "read", "status": "PASS", "cause": None, "sub_verdicts": []},
            {"ordinal": 1, "tool": "edit", "status": "FAIL", "cause": "some-cause", "sub_verdicts": []},
            {"ordinal": 2, "tool": "edit", "status": "FAIL", "cause": "some-cause", "sub_verdicts": []},
            {"ordinal": 3, "tool": "read", "status": "PASS", "cause": None, "sub_verdicts": []},
            {"ordinal": 4, "tool": "edit", "status": "FAIL", "cause": "some-cause", "sub_verdicts": []},
            {"ordinal": 5, "tool": "edit", "status": "FAIL", "cause": "some-cause", "sub_verdicts": []},
            {"ordinal": 6, "tool": "read", "status": "PASS", "cause": None, "sub_verdicts": []},
            {"ordinal": 7, "tool": "edit", "status": "FAIL", "cause": "some-cause", "sub_verdicts": []},
            {"ordinal": 8, "tool": "edit", "status": "UNVERIFIED", "cause": "unrestorable-pre-state", "sub_verdicts": []},
            {"ordinal": 9, "tool": "read", "status": "UNVERIFIED", "cause": "skipped by the triage budget", "sub_verdicts": []},
            {"ordinal": 10, "tool": "read", "status": "PASS", "cause": None, "sub_verdicts": []},
        ],
        "aggregate": {"turns_verified": 8, "PASS": 3, "WARN": 0, "FAIL": 5, "UNVERIFIED": 2},
        "coverage": {},
        "exposure": {"recorded": True, "judged_turns": 0, "comparisons": 0},
        "trajectory": {"status": "PASS", "cause": None, "message": "trajectory PASS"},
        "triage": {
            "mode": "budgeted",
            "skipped": 1,
            "threshold": 0.5,
            "scores": [
                {"ordinal": 0, "score": 0.1, "confidence": 0.0625},
                {"ordinal": 1, "score": 0.2, "confidence": 0.25},
                {"ordinal": 2, "score": 0.4, "confidence": 0.4375},
                {"ordinal": 3, "score": 0.4, "confidence": 0.5625},
                {"ordinal": 4, "score": 0.6, "confidence": 0.6875},
                {"ordinal": 5, "score": 0.7, "confidence": 0.875},
                {"ordinal": 6, "score": 0.8, "confidence": 0.875},
                {"ordinal": 7, "score": 0.9, "confidence": 1.0},
                {"ordinal": 8, "score": 0.5, "confidence": 0.5},
                {"ordinal": 9, "score": 0.3, "confidence": 0.3, "skipped": True},
            ],
        },
        "error": None,
    }


#: The full text render of the synthetic document, computed by hand:
#: 11 turns total, 8 decided, 3 excluded (1 UNVERIFIED, 1 skipped, 1 unscored —
#: the count is `total - decided`, so the breakdown sums to it exactly);
#: violations 5/8; ECE 0.375; the reliability curve of the calibration-math
#: fixture (deciles 1/3/7 "no data"); the threshold sweep (score < threshold) and
#: the top-N sweep (N lowest scores, ties by lowest ordinal) — skipped counts
#: against the 8 decided rows, budget saved as the percentage of rows skipped.
_EXPECTED_TEXT = (
    "belay triage ledger: demo/trace-0.jsonl\n"
    "turns: 11 total, 8 decided, 3 excluded (1 UNVERIFIED, 1 skipped, 1 unscored)\n"
    "violations: 5/8 = 62.5%\n"
    "ece: 0.375\n"
    "reliability:\n"
    "  [0.0-0.1): n=1, mean conf 0.0625, rate 0.0%\n"
    "  [0.1-0.2): no data\n"
    "  [0.2-0.3): n=1, mean conf 0.25, rate 100.0%\n"
    "  [0.3-0.4): no data\n"
    "  [0.4-0.5): n=1, mean conf 0.4375, rate 100.0%\n"
    "  [0.5-0.6): n=1, mean conf 0.5625, rate 0.0%\n"
    "  [0.6-0.7): n=1, mean conf 0.6875, rate 100.0%\n"
    "  [0.7-0.8): no data\n"
    "  [0.8-0.9): n=2, mean conf 0.875, rate 50.0%\n"
    "  [0.9-1.0]: n=1, mean conf 1.0, rate 100.0%\n"
    "threshold sweep (skipped = score < threshold):\n"
    "  0.1: skipped 0/8 (0.0%), violations skipped 0\n"
    "  0.2: skipped 1/8 (12.5%), violations skipped 0\n"
    "  0.3: skipped 2/8 (25.0%), violations skipped 1\n"
    "  0.4: skipped 2/8 (25.0%), violations skipped 1\n"
    "  0.5: skipped 4/8 (50.0%), violations skipped 2\n"
    "  0.6: skipped 4/8 (50.0%), violations skipped 2\n"
    "  0.7: skipped 5/8 (62.5%), violations skipped 3\n"
    "  0.8: skipped 6/8 (75.0%), violations skipped 4\n"
    "  0.9: skipped 7/8 (87.5%), violations skipped 4\n"
    "top-N sweep (N lowest scores skipped, ties by lowest ordinal):\n"
    "  1: skipped 1/8 (12.5%), violations skipped 0\n"
    "  2: skipped 2/8 (25.0%), violations skipped 1\n"
    "  3: skipped 3/8 (37.5%), violations skipped 2\n"
    "  4: skipped 4/8 (50.0%), violations skipped 2\n"
    "  5: skipped 5/8 (62.5%), violations skipped 3"
)


def _expected_json_document() -> dict:
    """The machine render of the synthetic document, key order pinned (the bytes
    the command must emit verbatim). Rates and confidences are binary-exact, so
    every literal is exactly representable."""
    return {
        "schema": 1,
        "trace": "demo/trace-0.jsonl",
        "turns_total": 11,
        "turns_decided": 8,
        "excluded": {"unverified": 1, "skipped": 1, "unscored": 1},
        "violations": 5,
        "violation_rate": 0.625,
        "reliability": [
            {"bin": "[0.0-0.1)", "n": 1, "mean_confidence": 0.0625, "observed_rate": 0.0, "no_data": False},
            {"bin": "[0.1-0.2)", "n": 0, "mean_confidence": None, "observed_rate": None, "no_data": True},
            {"bin": "[0.2-0.3)", "n": 1, "mean_confidence": 0.25, "observed_rate": 1.0, "no_data": False},
            {"bin": "[0.3-0.4)", "n": 0, "mean_confidence": None, "observed_rate": None, "no_data": True},
            {"bin": "[0.4-0.5)", "n": 1, "mean_confidence": 0.4375, "observed_rate": 1.0, "no_data": False},
            {"bin": "[0.5-0.6)", "n": 1, "mean_confidence": 0.5625, "observed_rate": 0.0, "no_data": False},
            {"bin": "[0.6-0.7)", "n": 1, "mean_confidence": 0.6875, "observed_rate": 1.0, "no_data": False},
            {"bin": "[0.7-0.8)", "n": 0, "mean_confidence": None, "observed_rate": None, "no_data": True},
            {"bin": "[0.8-0.9)", "n": 2, "mean_confidence": 0.875, "observed_rate": 0.5, "no_data": False},
            {"bin": "[0.9-1.0]", "n": 1, "mean_confidence": 1.0, "observed_rate": 1.0, "no_data": False},
        ],
        "ece": 0.375,
        "threshold_sweep": [
            {"threshold": 0.1, "skipped": 0, "violations_skipped": 0, "budget_saved": 0.0},
            {"threshold": 0.2, "skipped": 1, "violations_skipped": 0, "budget_saved": 0.125},
            {"threshold": 0.3, "skipped": 2, "violations_skipped": 1, "budget_saved": 0.25},
            {"threshold": 0.4, "skipped": 2, "violations_skipped": 1, "budget_saved": 0.25},
            {"threshold": 0.5, "skipped": 4, "violations_skipped": 2, "budget_saved": 0.5},
            {"threshold": 0.6, "skipped": 4, "violations_skipped": 2, "budget_saved": 0.5},
            {"threshold": 0.7, "skipped": 5, "violations_skipped": 3, "budget_saved": 0.625},
            {"threshold": 0.8, "skipped": 6, "violations_skipped": 4, "budget_saved": 0.75},
            {"threshold": 0.9, "skipped": 7, "violations_skipped": 4, "budget_saved": 0.875},
        ],
        "top_n_sweep": [
            {"n": 1, "skipped": 1, "violations_skipped": 0, "budget_saved": 0.125},
            {"n": 2, "skipped": 2, "violations_skipped": 1, "budget_saved": 0.25},
            {"n": 3, "skipped": 3, "violations_skipped": 2, "budget_saved": 0.375},
            {"n": 4, "skipped": 4, "violations_skipped": 2, "budget_saved": 0.5},
            {"n": 5, "skipped": 5, "violations_skipped": 3, "budget_saved": 0.625},
        ],
    }


def test_synthetic_document_pins_the_exact_text(tmp_path) -> None:
    """The rendered text is pinned byte-for-byte: reliability bins (incl. the
    no-data bins), ECE, the threshold sweep and the top-N sweep, the excluded
    counts, and the denominator."""
    doc_path = tmp_path / "verify.json"
    doc_path.write_text(json.dumps(_synthetic_document()), encoding="utf-8")

    rc, text = _run_cli(["triage-ledger", str(doc_path)])

    assert rc == 0, text
    assert text == _EXPECTED_TEXT + "\n", text


def test_synthetic_document_json_is_byte_stable(tmp_path) -> None:
    """`--json` emits the FULL document as one string, byte-identical to the
    pinned key order and values — the machine contract."""
    doc_path = tmp_path / "verify.json"
    doc_path.write_text(json.dumps(_synthetic_document()), encoding="utf-8")

    rc, text = _run_cli(["triage-ledger", "--json", str(doc_path)])

    assert rc == 0, text
    assert text == json.dumps(_expected_json_document()) + "\n", text


# --- (3) EXCLUSIONS: UNVERIFIED and skipped rows are counted, never calibrated --------


def test_rows_from_document_mapping_excludes_and_counts(tmp_path) -> None:
    """The join semantics, pinned directly: FAIL -> violated, PASS/WARN -> clean,
    UNVERIFIED and `"skipped": true` rows excluded from the calibration column and
    counted; an unscored turn is absent (stated as unscored)."""
    from belay.verify.triage_ledger import rows_from_document

    doc = {
        "schema": 1,
        "trace": "t.jsonl",
        "turns": [
            {"ordinal": 0, "status": "FAIL", "tool": "edit", "cause": "c", "sub_verdicts": []},
            {"ordinal": 1, "status": "PASS", "tool": "read", "cause": None, "sub_verdicts": []},
            {"ordinal": 2, "status": "WARN", "tool": "edit", "cause": None, "sub_verdicts": []},
            {"ordinal": 3, "status": "UNVERIFIED", "tool": "read", "cause": "unrestorable-pre-state", "sub_verdicts": []},
            {"ordinal": 4, "status": "UNVERIFIED", "tool": "read", "cause": "skipped by the triage budget", "sub_verdicts": []},
            {"ordinal": 5, "status": "PASS", "tool": "read", "cause": None, "sub_verdicts": []},
        ],
        "triage": {
            "mode": "budgeted",
            "skipped": 1,
            "scores": [
                {"ordinal": 0, "score": 0.8, "confidence": 0.8},
                {"ordinal": 1, "score": 0.6, "confidence": 0.6},
                {"ordinal": 2, "score": 0.6, "confidence": 0.6},
                {"ordinal": 3, "score": 0.4, "confidence": 0.4},
                {"ordinal": 4, "score": 0.2, "confidence": 0.2, "skipped": True},
            ],
        },
    }
    ledger = rows_from_document(doc)

    assert [(row.ordinal, row.violated) for row in ledger.rows] == [
        (0, True),
        (1, False),
        (2, False),
    ]
    assert ledger.turns_total == 6
    assert ledger.turns_decided == 3
    assert ledger.excluded_unverified == 1
    assert ledger.excluded_skipped == 1
    assert ledger.excluded_unscored == 1


def test_score_row_with_no_matching_turn_is_fail_closed(tmp_path) -> None:
    """A score row whose ordinal joins to no turn is a corrupt document — named
    error, exit 2, never a silently smaller ledger."""
    doc = _synthetic_document()
    doc["triage"]["scores"] = doc["triage"]["scores"] + [
        {"ordinal": 99, "score": 0.5, "confidence": 0.5}
    ]
    doc_path = tmp_path / "verify.json"
    doc_path.write_text(json.dumps(doc), encoding="utf-8")

    rc, text = _run_cli(["triage-ledger", str(doc_path)])

    assert rc == 2, text
    assert "matches no turn record" in text, text


# --- (4) THE ZERO-DENOMINATOR REFUSAL: no rates over a 100%-UNVERIFIED column ---------


def _all_unverified_document() -> dict:
    return {
        "schema": 1,
        "trace": "mint/s6.jsonl",
        "turns": [
            {"ordinal": n, "tool": "edit", "status": "UNVERIFIED",
             "cause": "unrestorable-pre-state", "sub_verdicts": []}
            for n in range(7)
        ],
        "aggregate": {"turns_verified": 0, "PASS": 0, "WARN": 0, "FAIL": 0, "UNVERIFIED": 7},
        "coverage": {},
        "exposure": {"recorded": True, "judged_turns": 0, "comparisons": 0},
        "trajectory": {"status": "UNVERIFIED", "cause": "NO_VERIFIABLE_TURNS", "message": ""},
        "triage": {
            "mode": "shadow",
            "skipped": 0,
            "scores": [
                {"ordinal": n, "score": 0.5, "confidence": 0.5} for n in range(7)
            ],
        },
        "error": None,
    }


def test_100_percent_unverified_renders_the_named_refusal_no_rates(tmp_path) -> None:
    """The INSTRUMENT SUSPECT shape: a zero-denominator column renders the named
    refusal with NO rates and exits 0 — a measurement refused, never a fabricated
    0% (the R6 false-zero defense)."""
    doc_path = tmp_path / "verify.json"
    doc_path.write_text(json.dumps(_all_unverified_document()), encoding="utf-8")

    rc, text = _run_cli(["triage-ledger", str(doc_path)])

    assert rc == 0, text
    assert "NO_DECIDED_ROWS" in text, text
    assert "7 turns, 0 decided, 7 excluded (7 UNVERIFIED, 0 skipped)" in text, text
    assert "no calibration measurement rendered over a zero-denominator column" in text, text
    assert "violations:" not in text, text
    assert "ece:" not in text, text


def test_100_percent_unverified_json_refuses_the_rates(tmp_path) -> None:
    """The `--json` refusal carries the named refusal and the counts, and NO
    rates: no reliability, no ece, no sweep keys."""
    doc_path = tmp_path / "verify.json"
    doc_path.write_text(json.dumps(_all_unverified_document()), encoding="utf-8")

    rc, text = _run_cli(["triage-ledger", "--json", str(doc_path)])

    assert rc == 0, text
    parsed = json.loads(text)
    assert parsed == {
        "schema": 1,
        "trace": "mint/s6.jsonl",
        "refusal": "NO_DECIDED_ROWS",
        "cause": (
            "7 turns, 0 decided, 7 excluded (7 UNVERIFIED, 0 skipped); "
            "no calibration measurement rendered over a zero-denominator column"
        ),
        "turns_total": 7,
        "turns_decided": 0,
        "excluded": {"unverified": 7, "skipped": 0, "unscored": 0},
    }, text


# --- (5) FAIL-CLOSED INPUT: the `_cmd_phase0_report` load shape -----------------------


def test_document_without_triage_section_exits_2_named(tmp_path) -> None:
    """No `triage` section => exit 2, named — a ledger over a run that never ran
    triage would be a fabrication, never rendered."""
    doc = _synthetic_document()
    del doc["triage"]
    doc_path = tmp_path / "verify.json"
    doc_path.write_text(json.dumps(doc), encoding="utf-8")

    rc, text = _run_cli(["triage-ledger", str(doc_path)])

    assert rc == 2, text
    assert "no triage section" in text, text


def test_malformed_document_exits_2(tmp_path) -> None:
    """Not JSON => exit 2, named (the `_cmd_phase0_report` load shape)."""
    doc_path = tmp_path / "verify.json"
    doc_path.write_text("{not json", encoding="utf-8")

    rc, text = _run_cli(["triage-ledger", str(doc_path)])

    assert rc == 2, text
    assert "could not read verify document" in text, text


def test_missing_document_exits_2(tmp_path) -> None:
    """No file => exit 2, named — never a silently empty ledger."""
    rc, text = _run_cli(["triage-ledger", str(tmp_path / "nope.json")])

    assert rc == 2, text
    assert "verify document not found" in text, text


# --- (6) DETERMINISM: the same document re-renders byte-identically -------------------


def test_same_document_rerenders_byte_identically(tmp_path) -> None:
    """Run twice, compare: the re-render discipline (the phase0 report precedent)
    pinned — text and `--json` both."""
    doc_path = tmp_path / "verify.json"
    doc_path.write_text(json.dumps(_synthetic_document()), encoding="utf-8")

    rc1, text1 = _run_cli(["triage-ledger", str(doc_path)])
    rc2, text2 = _run_cli(["triage-ledger", str(doc_path)])
    rc3, json3 = _run_cli(["triage-ledger", "--json", str(doc_path)])
    rc4, json4 = _run_cli(["triage-ledger", "--json", str(doc_path)])

    assert rc1 == rc2 == rc3 == rc4 == 0
    assert text1 == text2, (text1, text2)
    assert json3 == json4, (json3, json4)


# --- (7) PARITY: the `--json` row declares the new machine surface --------------------


def test_parity_json_row_declares_triage_ledger() -> None:
    """The flag-parity `--json` row must declare `triage-ledger` — widened in the
    SAME commit as the command, or guard 1 fails (a machine surface that ships
    with `--json` but is not declared). Red until the registry is widened."""
    from test_cli_flag_parity import EXPECTED, _surfaces_carrying

    assert "triage-ledger" in EXPECTED["--json"], EXPECTED["--json"]
    assert "triage-ledger" in _surfaces_carrying("--json"), _surfaces_carrying("--json")