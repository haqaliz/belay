"""`belay verify --timeout` — the per-replay timeout the console and the demo need.

The engine's per-replay default is 10 seconds (`cli.DEFAULT_TIMEOUT`). `belay corpus
add`, `belay phase0 run` and `belay interop correlate` each expose `--timeout` to raise
it; `belay verify` did not. So the only way to verify a trace whose turns take longer
than 10s was to go through one of the *other* surfaces — and a turn that outruns the
timeout does not fail, it reports UNVERIFIED: an honest abstention, but a false one,
caused by the clock rather than by anything about the run.

That is not hypothetical here. The C7 console shells out to `belay verify --json`, and
the launch demo's capture replays `run_process` turns that re-run a real suite in ~44s.
Without this flag the console renders the demo's execution evidence as UNVERIFIED — on
the launch surface that reads as "Belay could not check this", which is the opposite of
what the capture proves.

It is also the flag the console had already begun passing before it existed: argparse
answered `unrecognized arguments: --timeout <trace>` on stderr with an EMPTY stdout and
exit 2, so every console verify degraded to the `empty-output` error path rather than to
a verdict. A flag the caller sends and the callee rejects is worse than the abstention it
was meant to fix, which is why the passthrough is pinned here rather than only in the
console's own suite (where the engine is a stub that echoes argv and cannot object).

Parser-level and passthrough only: `verify_turn` is stubbed, so nothing is re-invoked and
nothing is sandboxed — these run cross-platform.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from belay import cli
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURE = REPO_ROOT / "demo" / "capture"


def _capture_trace() -> Path:
    """The committed demo capture's trace — a real trace with real tool-call turns.

    Used as *input shape* only: `verify_turn` is stubbed in the passthrough tests below,
    so no replay happens and the capture's verdict is not what is under test here (that
    is `tests/test_demo_capture.py`).
    """
    traces = sorted(CAPTURE.glob("trace-*.jsonl"))
    assert len(traces) == 1, f"expected exactly one committed capture trace, got {traces}"
    return traces[0]


def _parse(*extra: str):
    return cli._parser().parse_args(
        ["verify", str(_capture_trace()), "--manifest-dir", "m", *extra, "--server", "srv"]
    )


def test_verify_timeout_defaults_to_the_engine_default():
    assert _parse().timeout == cli.DEFAULT_TIMEOUT


def test_verify_accepts_a_raised_timeout():
    assert _parse("--timeout", "300").timeout == 300.0


@pytest.mark.parametrize(
    ("extra", "expected"),
    [(["--timeout", "300"], 300.0), ([], cli.DEFAULT_TIMEOUT)],
)
def test_verify_passes_the_timeout_through_to_verify_turn(monkeypatch, capsys, extra, expected):
    """The flag is only worth having if it reaches the replay: assert the value
    `verify_turn` is called with, not merely that argparse accepted a string."""
    seen: list[float | None] = []

    def _stub(records, n, **kwargs):
        seen.append(kwargs.get("timeout"))
        return TurnVerdict(turn_index=n, tool_name="stub", status=Status.PASS)

    monkeypatch.setattr("belay.verify.turn.verify_turn", _stub)

    # `--turn 0` keeps the run to one turn (and skips the trajectory block, which is
    # whole-trace only); `--json` keeps stdout machine-shaped.
    cli.main(
        [
            "verify",
            str(_capture_trace()),
            "--manifest-dir",
            str(CAPTURE / f"{_capture_trace().stem}.manifests"),
            "--turn",
            "0",
            "--json",
            *extra,
            "--server",
            "srv",
        ]
    )
    capsys.readouterr()

    assert seen == [expected]
