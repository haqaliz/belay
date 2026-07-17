"""`belay verify --replays` enforces the documented determinism floor of 3.

Two rough edges the floor closes, both about a FALSE FAIL on a nondeterministic tool:

- `--replays 1` reached `classify_determinism`, which raises `ValueError` for N<2 — a raw
  traceback instead of a clean error.
- `--replays 2` was accepted, but the determinism module's own docstring names 3 as the
  floor: with N=2 a genuinely nondeterministic tool whose two classification replays
  coincidentally match (a coarse clock, both runs inside one second) is misread as
  DETERMINISTIC, and on a DIVERGED reply that becomes a false FAIL.

The `verify` surface refuses both by validating `--replays >= 3` in the parser, so the
error is a clean argparse message (exit 2), never a traceback and never a false verdict.
This runs cross-platform: the value is rejected during argument parsing, before any replay,
so it needs no macOS sandbox. (The classifier's own floor of 2 is C3's and is left intact.)
"""

from __future__ import annotations

import pytest

from belay import cli


@pytest.mark.parametrize("n", ["1", "2"])
def test_verify_rejects_replays_below_three(n, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            ["verify", "trace.jsonl", "--manifest-dir", "m", "--replays", n, "--server", "srv"]
        )
    assert exc.value.code == 2, f"--replays {n} should be a clean argparse error, not {exc.value.code}"
    err = capsys.readouterr().err
    assert "at least 3" in err, err


def test_verify_accepts_three_replays():
    # A parse-only check: `--replays 3` passes validation. We stop at the parser (a bad
    # trace path would fail later) — the point is only that the floor does not reject 3.
    parser = cli._parser()
    args = parser.parse_args(
        ["verify", "trace.jsonl", "--manifest-dir", "m", "--replays", "3", "--server", "srv"]
    )
    assert args.replays == 3
