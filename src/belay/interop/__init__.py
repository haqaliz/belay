"""C9 — observability interop: ingesting spans recorded by tools other than Belay.

Belay complements existing observability (Langfuse, Phoenix, OpenTelemetry-style
tracing) rather than competing with it — see `CLAUDE.md`'s "the wedge". This
package is the ingest half: turning a foreign trace encoding into a small internal
shape Belay can correlate against its own recorded MCP turns. `otlp.py` is the
first source (OTLP/JSON); it does no correlation and emits no verdict.
"""

from __future__ import annotations
