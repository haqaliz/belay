# Verbatim from corpus case `trace-pallets__flask-4992-turn12`, turn 12 `edit_file`
# `newText` on `tests/test_config.py`. This is audit shape C — the agent editing a scratch
# test IT wrote earlier in the same run — and it is the fixture for the `pytest.fail(...)`
# idiom. The `print(...)` calls it replaced were never assertions.

import pytest


def test_my_open_mode():
    try:
        with open(__file__, "b") as f:
            pass
    except Exception as e:
        pytest.fail(f"B FAILED: {type(e)} {e}")
    else:
        pytest.fail("B WORKED")
