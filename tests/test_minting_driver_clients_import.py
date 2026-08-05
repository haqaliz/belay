"""RED-first isolation tests for the minting-driver's BYOK clients (Task 8).

The driver CORE (`loop.py`, `transport.py`, `model.py`, `session.py`, `capture.py`,
`mcp.py`, `fakes.py`, `resilience.py`) must stay importable with zero third-party dependencies — that is
what keeps the default `uv run pytest` environment (and CI, which only `uv sync`s the
`dev` group) green without ever installing `anthropic` or `openai`. Those SDKs are real
BYOK clients behind the `Model` seam (`clients/anthropic_client.py`,
`clients/local_client.py`); they must be *reachable* by anyone who wants to run a live
mint, but their SDK imports must never leak into the core import graph, and their modules
must stay importable even in an environment where the SDKs are absent (a lazy
`import anthropic`/`import openai` INSIDE `__init__`, not at module top).

The third client, `clients/claude_cli_client.py`, satisfies the same contract by a
different and stronger route: its boundary is a `subprocess`, so it imports **no** SDK at
any point, lazily or otherwise. That is asserted here rather than assumed — and asserted
as "nothing outside the standard library", not merely "not those two SDKs", because the
plausible future import on that path (a vendor exception type, to recognise a subscription
usage limit) is one nobody would think to add to a two-name denylist.

Every assertion here runs in a **subprocess** — mirroring the approach
`tests/test_import_guard.py` uses for `src/belay` (a static AST walk there; a fresh
interpreter here) — because `sys.modules` state leaks across tests in a shared process:
if any earlier test (or pytest plugin) has already imported `anthropic`/`openai` for an
unrelated reason, an in-process `sys.modules` check would silently pass for the wrong
reason. A subprocess starts with a clean `sys.modules` every time, so the only way
`anthropic`/`openai` ends up in it is if the import under test actually pulled it in.

None of these tests instantiate a real client or talk to a network — importability only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: Repo root — `eval/` and `src/` both live directly under it. `pyproject.toml`'s
#: `pythonpath = ["."]` ini option puts this on `sys.path` for pytest's own process,
#: but a subprocess spawned via `subprocess.run` does not inherit that; running the
#: subprocess with this as its `cwd` gets the same effect for free, because `python -c`
#: puts the current directory (`''`) at `sys.path[0]`.
REPO_ROOT = Path(__file__).parent.parent


def _run(code: str) -> subprocess.CompletedProcess[str]:
    """Run `code` in a fresh subprocess, cwd'd to the repo root so `import eval...`
    resolves exactly as it does under pytest — with none of pytest's own import
    machinery or any earlier test's `sys.modules` state carried over."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )


def test_importing_driver_core_does_not_import_anthropic_or_openai() -> None:
    code = (
        "import eval.minting_driver.model\n"
        "import eval.minting_driver.transport\n"
        "import eval.minting_driver.mcp\n"
        "import eval.minting_driver.loop\n"
        "import eval.minting_driver.session\n"
        "import eval.minting_driver.capture\n"
        "import eval.minting_driver.fakes\n"
        # `resilience.py` classifies PROVIDER exceptions, which is exactly the module an
        # `import openai` would look natural in — `isinstance(exc, openai.RateLimitError)`
        # is the obvious wrong way to write it. It reads `status_code` off whatever it is
        # handed instead, and this line is what keeps it that way.
        "import eval.minting_driver.resilience\n"
        "import sys\n"
        "assert 'anthropic' not in sys.modules, 'anthropic leaked into the core import graph'\n"
        "assert 'openai' not in sys.modules, 'openai leaked into the core import graph'\n"
        "print('OK')\n"
    )
    result = _run(code)

    assert result.returncode == 0, (
        f"importing the driver core failed or leaked an SDK import\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_anthropic_client_module_importable_without_anthropic_installed() -> None:
    """`clients/anthropic_client.py` must import cleanly even when `anthropic` is not
    installed — proof that `import anthropic` is lazy (inside `__init__`), not at
    module top. This test does not fake-out or block the real import; it simply
    asserts the module-level import succeeds and `anthropic` never lands in
    `sys.modules` merely from importing the module (constructing `AnthropicModel` is
    a separate, unexercised step here)."""
    code = (
        "import eval.minting_driver.clients.anthropic_client as m\n"
        "import sys\n"
        "assert 'anthropic' not in sys.modules, "
        "'anthropic imported at module load, not lazily inside __init__'\n"
        "assert hasattr(m, 'AnthropicModel')\n"
        "print('OK')\n"
    )
    result = _run(code)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "OK" in result.stdout


def test_local_client_module_importable_without_openai_installed() -> None:
    """Same guarantee as above, for `clients/local_client.py` and `openai`."""
    code = (
        "import eval.minting_driver.clients.local_client as m\n"
        "import sys\n"
        "assert 'openai' not in sys.modules, "
        "'openai imported at module load, not lazily inside __init__'\n"
        "assert hasattr(m, 'LocalOpenAICompatModel')\n"
        "print('OK')\n"
    )
    result = _run(code)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "OK" in result.stdout


def test_claude_cli_client_module_imports_no_sdk_at_all() -> None:
    """`clients/claude_cli_client.py` imports **no** SDK — not lazily, not at all.

    Its boundary is a `subprocess`, not a vendor client, so the isolation contract holds
    here by construction rather than by a lazy `import` inside `__init__`. That is the
    strongest form of the guarantee in this file and it is **asserted rather than assumed**:
    an SDK import would be an easy and plausible future addition — reaching for
    `anthropic`'s exception types to recognise a subscription usage limit is exactly the
    shape it would take — and it would put a third-party dependency behind a path whose
    entire selling point is running on credentials the operator already has.

    Constructing `ClaudeCliModel` is deliberately part of this test, unlike the two above:
    there is no `__init__`-time import to keep lazy, so there is nothing to protect by
    leaving it unexercised, and doing it here proves the *whole* module is SDK-free rather
    than only its import. No `claude` binary is spawned — nothing calls `propose_next`.
    """
    code = (
        # The baseline is taken BEFORE the import, so what is measured is what this module
        # pulled in — not whatever the interpreter starts with.
        "import sys\n"
        "before = set(sys.modules)\n"
        "import eval.minting_driver.clients.claude_cli_client as m\n"
        "pulled = {name.split('.')[0] for name in set(sys.modules) - before}\n"
        # Stronger than naming the two SDKs: NOTHING outside the standard library and this
        # repo's own trees may enter the graph. A future `import httpx` to talk to a local
        # endpoint would fail here even though it is neither `anthropic` nor `openai`.
        "third_party = sorted(\n"
        "    name for name in pulled\n"
        # `belay` is NOT on this allowlist either: `eval/` may not import the product tree
        # (guardrail #1), and this client has no reason to be the first place that does.
        "    if name not in sys.stdlib_module_names and name != 'eval'\n"
        ")\n"
        "assert not third_party, f'the CLI client imported {third_party}'\n"
        "assert 'anthropic' not in sys.modules, "
        "'the CLI client pulled in the anthropic SDK; its boundary is a subprocess'\n"
        "assert 'openai' not in sys.modules\n"
        "assert hasattr(m, 'ClaudeCliModel')\n"
        # A real construction, with a runner that would fail loudly if anything called it.
        "def never(*a, **k):\n"
        "    raise AssertionError('no claude invocation may happen here')\n"
        "model = m.ClaudeCliModel(model=m.DEFAULT_CLAUDE_CLI_MODEL, tools=[], "
        "runner=never)\n"
        "assert model.provider == m.PROVIDER_NAME\n"
        "assert 'anthropic' not in sys.modules and 'openai' not in sys.modules\n"
        "print('OK')\n"
    )
    result = _run(code)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "OK" in result.stdout


def test_clients_package_importable_without_sdks_installed() -> None:
    """`clients/__init__.py` itself must not import either SDK at module top —
    otherwise merely doing `from eval.minting_driver.clients import anthropic_client`
    style access, or any tooling that imports the package, would require both SDKs
    present even for a user who only wants one of the two clients."""
    code = (
        "import eval.minting_driver.clients\n"
        "import sys\n"
        "assert 'anthropic' not in sys.modules\n"
        "assert 'openai' not in sys.modules\n"
        "print('OK')\n"
    )
    result = _run(code)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "OK" in result.stdout
