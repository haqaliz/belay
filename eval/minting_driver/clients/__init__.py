"""BYOK reference `Model` clients — real LLM adapters, isolated from the driver core.

`AnthropicModel` (`anthropic_client.py`) and `LocalOpenAICompatModel` (`local_client.py`)
are thin adapters mapping one model response to one `ToolCall` or `Done` (`model.py`'s
seam) — no planning, no memory, no agentic retry loop of their own; that stays the
driver loop's job (`loop.py`).

**Import isolation is the whole point of this subpackage's boundary.** The driver core
(`loop.py`, `transport.py`, `model.py`, `session.py`, `capture.py`, `mcp.py`, `fakes.py`)
must stay importable with zero third-party dependencies, so the SDKs these clients wrap
(`anthropic`, `openai`) are never imported here at module top — each client module lazily
imports its SDK inside `__init__`, and this package `__init__` imports neither client
module, let alone either SDK, at package-import time. `tests/test_minting_driver_clients_
import.py` is what proves that boundary holds; nothing here is a formal contract.
"""

from __future__ import annotations

__all__: list[str] = []
