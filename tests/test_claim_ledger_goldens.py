"""surface-threading S2: the committed mint ledgers re-render as they did before this unit.

`belay phase0 report` is a pure re-render of a stored ledger, and the four
`docs/planning/phase0-corpus-mint/mint-run/ledgers/cm-*.json` are committed evidence. No
test exercised them before; the claim that they re-render byte-identically was made by
hand. The goldens under `tests/fixtures/claim_ledger_goldens/` were rendered from
`1ada903` — before `claim-axis-legibility` touched any claim surface — by
`make_goldens.sh`, in a scratch worktree with its own venv, and are never hand-edited.

Exactly ONE difference is permitted: `silence-record` corrected
`_CLAIM_UNRECORDED_SENTENCE` (it used to attribute D3 silence to a missing author). The
comparison applies that one old -> new substitution to the golden and nothing else.
Measured at capture (2026-09-25): these four ledgers hold **no** claim-less instance, so
the substitution never fires on them — the sentence change is pinned by
`tests/test_claim_silence.py`. What this pin holds is the rest: in particular the two
`NO_CHECK_AUTHOR` lines in `cm-run3-stage2`, which render unchanged because a ledger
written before the sub-cause existed carries none.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from belay import cli
from belay.phase0.report import _CLAIM_UNRECORDED_SENTENCE

REPO = Path(__file__).resolve().parent.parent
LEDGERS = REPO / "docs" / "planning" / "phase0-corpus-mint" / "mint-run" / "ledgers"
GOLDENS = Path(__file__).resolve().parent / "fixtures" / "claim_ledger_goldens"

#: `_CLAIM_UNRECORDED_SENTENCE` as `1ada903` rendered it — the one permitted difference.
OLD_UNRECORDED_SENTENCE = (
    "claim unrecorded — no A3 verdict was recorded here (no claim author was "
    "configured for this run, the claim axis was disabled, or this ledger predates "
    "the field); this is NOT a claim that the intent drift was clean"
)

LEDGER_NAMES = sorted(p.stem for p in LEDGERS.glob("cm-*.json"))


def test_there_are_four_committed_ledgers_and_a_golden_for_each() -> None:
    assert LEDGER_NAMES == [
        "cm-run2-stage1", "cm-run3-stage1", "cm-run3-stage2", "cm-stage1",
    ]
    assert sorted(p.name for p in GOLDENS.glob("*.report.txt")) == [
        f"{name}.report.txt" for name in LEDGER_NAMES
    ]


@pytest.mark.parametrize("name", LEDGER_NAMES)
def test_the_committed_ledger_re_renders_as_its_golden(name, tmp_path) -> None:
    empty_corpus = tmp_path / "empty-corpus"
    empty_corpus.mkdir()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(
            ["phase0", "report", "--corpus-dir", str(empty_corpus),
             str(LEDGERS / f"{name}.json")]
        )
    assert rc == 0
    golden = (GOLDENS / f"{name}.report.txt").read_text(encoding="utf-8")
    expected = golden.replace(OLD_UNRECORDED_SENTENCE, _CLAIM_UNRECORDED_SENTENCE)
    assert buf.getvalue() == expected
