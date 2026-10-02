"""surface-threading: a final-state sub-cause, end to end through the real CLI.

`belay verify --json --claim-author <stub>` on the committed demo capture, with an EMPTY
`--manifest-dir`: no snapshot manifest persists for any handle, so every turn is
UNVERIFIED (the pre-state cannot be restored) and the A3 final-state replay answers
`unverified: no persisted snapshot manifest ...` -> `FINAL_STATE_NOT_REPLAYED`. This is the
one reason reachable through the shipped CLI without a new fake server or a contrived trace
shape, and it replays nothing (no sandbox, no ~44 s turns), so it needs no platform gate.

Not reachable this way, a stated gap (pinned by the producer's unit tests, not here):
`FINAL_STATE_NO_TURN` (the demo capture has `tools/call` turns, and a trace without any is a
new trace shape), `FINAL_STATE_REPLAY_RAISED` (needs `replay_turn` to raise), and
`FINAL_STATE_NO_WORKSPACE` (needs a REPLAYED reply with no workspace).

The record refines what A3 SAYS and never a verdict: `turns`, `aggregate`, `trajectory` and
the exit code equal the no-author run's, and no `claim_silence` appears.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from test_claim_axis_e2e import _BELAY, _stubs
from test_demo_capture import REPLAY_TIMEOUT, SERVER, _capture_trace, _recorded_source_root


def _run(tmp_path, extra: list[str]) -> tuple[int, dict]:
    empty = tmp_path / "no-manifests"
    empty.mkdir(exist_ok=True)
    argv = [
        *_BELAY,
        "verify",
        str(_capture_trace()),
        "--manifest-dir",
        str(empty),
        "--timeout",
        str(int(REPLAY_TIMEOUT)),
        "--json",
        *extra,
        "--server",
        sys.executable,
        str(SERVER),
        _recorded_source_root(),
    ]
    # An inherited BELAY_CLAIM_AUTHOR would give the baseline an author it must not have.
    env = {k: v for k, v in os.environ.items() if k != "BELAY_CLAIM_AUTHOR"}
    proc = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=300)
    assert proc.stdout.strip(), (proc.returncode, proc.stderr)
    return proc.returncode, json.loads(proc.stdout)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("final-state-e2e")
    return {
        "baseline": _run(tmp, []),
        "author": _run(tmp, ["--claim-author", _stubs()["exit_zero"]]),
    }


def test_the_baseline_has_no_claim_and_no_silence(runs) -> None:
    rc, doc = runs["baseline"]
    assert "claim" not in doc and "claim_silence" not in doc, doc
    assert doc["turns"] and all(t["status"] == "UNVERIFIED" for t in doc["turns"]), doc


def test_an_unrestorable_final_turn_names_its_sub_cause(runs) -> None:
    rc, doc = runs["author"]
    claim = doc["claim"]
    assert {k: v for k, v in claim.items() if k != "sub_cause_detail"} == {
        "axis": "A3",
        "kind": "claim",
        "status": "UNVERIFIED",
        "cause": "FINAL_STATE_UNOBSERVABLE",
        "check": {"source": "", "exit_code": None},
        "sub_cause": "FINAL_STATE_NOT_REPLAYED",
    }
    # The detail is the per-turn surface's own string: status plus the engine's cause.
    assert claim["sub_cause_detail"].startswith("unverified: no persisted snapshot manifest")
    assert list(claim)[-2:] == ["sub_cause", "sub_cause_detail"]
    assert "claim_silence" not in doc, doc


def test_the_sub_cause_moves_no_verdict(runs) -> None:
    base_rc, base = runs["baseline"]
    rc, doc = runs["author"]
    assert rc == base_rc
    for key in ("turns", "aggregate", "trajectory"):
        assert doc[key] == base[key], key
