"""BYOK reference `Model` clients — real LLM adapters, isolated from the driver core.

`AnthropicModel` (`anthropic_client.py`), `LocalOpenAICompatModel` (`local_client.py`) and
`ClaudeCliModel` (`claude_cli_client.py`) are thin adapters mapping one model response to
one `ToolCall` or `Done` (`model.py`'s seam) — no planning, no memory, no agentic retry
loop of their own; that stays the driver loop's job (`loop.py`).

The first two run on a metered API key. The third runs the `claude` CLI as a subprocess on
the operator's own subscription credentials, so a mint needs no per-token key at all; it is
selected by an explicit `--provider claude-cli` and never by which credential happens to be
exported (`entrypoint.PROVIDERS`).

**Import isolation is the whole point of this subpackage's boundary.** The driver core
(`loop.py`, `transport.py`, `model.py`, `session.py`, `capture.py`, `mcp.py`, `fakes.py`)
must stay importable with zero third-party dependencies, so the SDKs these clients wrap
(`anthropic`, `openai`) are never imported here at module top — each client module lazily
imports its SDK inside `__init__`, and this package `__init__` imports no client module,
let alone any SDK, at package-import time. `claude_cli_client.py` wraps no SDK at all: its
boundary is a process, so it holds the contract by construction rather than by a lazy
import. `tests/test_minting_driver_clients_import.py` is what proves that boundary holds;
nothing here is a formal contract.
"""

from __future__ import annotations

__all__: list[str] = []
