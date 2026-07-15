"""The gate: proves the proxy is byte-transparent (Task 2).

Runs the same scripted client against (a) the fake server directly and
(b) the fake server through the proxy, over REAL stdio pipes, and asserts
the two output byte streams are identical.

This test is expected to FAIL right now: `belay.proxy` does not exist yet
(that's Task 3). It must fail for that reason — not because of a typo, a
broken fixture, or a timeout.
"""

from __future__ import annotations

import os
import sys

from conftest import FIXTURE, run_over_pipes


def test_proxy_is_byte_identical_to_direct_connection(tmp_path):
    direct_lines = run_over_pipes([sys.executable, str(FIXTURE)])

    # Anti-vacuity guard: if the fixture ever emits nothing (e.g. it breaks
    # silently), an empty direct run would compare equal to an empty proxied
    # run and this test would PASS while proving nothing about the proxy at
    # all. This happened to a prototype of this exact test: a syntax error in
    # the fake server made both sides emit empty output, and `[] != []` is
    # False. Fail loudly instead of passing vacuously.
    assert direct_lines, (
        "fixture emitted nothing - the differential would pass vacuously "
        "(both sides would compare empty-to-empty, proving nothing about the proxy)"
    )
    assert len(direct_lines) == 4, (
        f"fixture emitted {len(direct_lines)} lines, expected exactly 4 (replies to "
        "ids 1/2/3, plus the notifications/tools/list_changed notification "
        "interleaved before the id=3 reply) - the fixture's shape changed and this "
        "test's line-count assumptions are stale"
    )

    env_trace_dir = tmp_path / "trace"
    env_trace_dir.mkdir()

    proxied_env = os.environ.copy()
    proxied_env["BELAY_TRACE_DIR"] = str(env_trace_dir)

    proxied_lines = run_over_pipes(
        [sys.executable, "-m", "belay.proxy", sys.executable, str(FIXTURE)],
        env=proxied_env,
    )

    if direct_lines != proxied_lines:
        first_diff = None
        for i, (d, p) in enumerate(zip(direct_lines, proxied_lines)):
            if d != p:
                first_diff = i
                break
        else:
            first_diff = min(len(direct_lines), len(proxied_lines))

        direct_at = direct_lines[first_diff] if first_diff < len(direct_lines) else b"<missing>"
        proxied_at = proxied_lines[first_diff] if first_diff < len(proxied_lines) else b"<missing>"
        raise AssertionError(
            "proxy output diverged from direct connection at line "
            f"{first_diff}:\n  direct : {direct_at!r}\n  proxied: {proxied_at!r}"
        )
