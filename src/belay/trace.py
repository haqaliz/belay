"""The trace: an append-only JSONL record of every frame that crossed the proxy.

This is the interchange format for the whole engine. The sandbox, the replay,
the verdict, the failure corpus and the observability bridge all read what is
written here, which is why every record carries `v` from the first line ever
written: the format cannot be quietly changed later.

Two rules shape everything below.

**Lossless.** `raw` is base64 of the exact bytes. Not a JSON string — a
non-conforming server can emit bytes that are not valid UTF-8 and therefore
cannot be a JSON string at all, and those must be recorded rather than crash the
writer or get coerced into something prettier. base64 round-trips
unconditionally. Rendering this for humans is the console's job, not the
recorder's.

**Honest.** The trace never claims more than the proxy observed. `t_in` is when
*we* saw the frame, which is why `observation_point` is on every record and says
`proxy`: our timing includes our own overhead, and a field that silently meant
"server time" would be a small lie. When observation breaks, the break is
recorded with a named cause instead of leaving a gap that looks like silence.

.. warning::
   **The trace is as sensitive as the agent's most sensitive tool argument.**
   Capture is verbatim and total: API keys, tokens, file contents and customer
   data land in `raw` in recoverable form. Files are created owner-only, and
   there is deliberately no redaction and no secret scanning — both are
   opinions, capture is opinion-free, and a redacted trace cannot be replayed.
   Treat a trace file as the credential it may contain.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from belay.hashing import CANONICAL_FORM, canonical_hash, hash_bytes

SCHEMA_VERSION = 1

# The reader's contract, stated once here and in docs/technical/TRACE_FORMAT.md:
# a record whose `kind` is unknown, or whose `v` is higher than the reader
# understands, must be SKIPPED and the skip recorded. Never dropped silently
# (that is a false-completeness claim), never fatal (an old reader must survive
# a new writer). C2 appends `denial`; C3 appends `nondeterminism`.
KINDS = ("frame", "capture_error")

Observer = Callable[[bytes, bool], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte, or raise.

    `os.write` is permitted to write fewer bytes than it was given, and a record
    is only a record if all of it landed: a short write would leave a truncated
    line that a reader cannot parse, in a format whose whole promise is
    losslessness. A base64'd MAX_FRAME frame is a ~21 MB line, which is not the
    size at which one assumes writes are indivisible.
    """
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


class TraceWriter:
    """Appends records to one JSONL file, from both pump threads.

    `seq` is allocated under the same lock as the append, so it is a total order
    over both directions in capture order — not two interleaved sequences a
    reader would have to reconcile. The two streams are independent, so the
    ordering *between* directions is only ever "when the proxy saw it", which is
    what `observation_point` already says out loud.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        # O_EXCL: never adopt a file someone else made, so the 0o600 below is a
        # property of a file we created rather than a hope about one we found.
        # The mode is passed to open() rather than chmod'ed afterwards, leaving
        # no window in which the trace exists and is world-readable.
        self._fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._lock = threading.Lock()
        self._seq = 0

    @classmethod
    def in_directory(cls, directory: str | Path) -> "TraceWriter":
        directory = Path(directory)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return cls(directory / f"trace-{stamp}-{uuid.uuid4().hex[:8]}.jsonl")

    @property
    def path(self) -> Path:
        return self._path

    def observer(self, direction: str) -> Observer:
        def observe(frame: bytes, truncated: bool) -> None:
            self._record_frame(direction, frame, truncated)

        return observe

    def _record_frame(self, direction: str, frame: bytes, truncated: bool) -> None:
        # Hashing happens before the lock: it is pure, it is the expensive part,
        # and holding the lock across it would make the two directions wait on
        # each other's arithmetic for no reason.
        raw = base64.b64encode(frame).decode("ascii")
        digest = hash_bytes(frame)
        canonical = canonical_hash(frame)
        self._append(
            {
                "kind": "frame",
                "dir": direction,
                "raw": raw,
                "hash_raw": digest,
                # Both null together, always: a canonical hash with no named
                # form is unverifiable, and a form naming a hash that does not
                # exist is a claim about bytes we could not parse.
                "hash_canonical": canonical,
                "canonical_form": CANONICAL_FORM if canonical is not None else None,
                "truncated": truncated,
                # Three-state from day one. C2 fills in `present` and
                # `unrestorable` with a cause. If this slot could only say
                # present/absent, C2 would have to overload "absent" to mean
                # both "recorded before snapshots existed" and "we tried to
                # snapshot and failed" - and a replay that cannot tell those
                # apart is how a false PASS gets born.
                "state_handle": {"status": "absent"},
            }
        )

    def capture_error(self, direction: str, cause: BaseException) -> None:
        """Record that observation of `direction` stopped, and why.

        Forwarding survives an observer that raises; observation does not, and
        must not pretend otherwise. Without this record the trace would simply
        end early while looking complete — a false-completeness claim, and the
        exact failure this project exists to catch. The `seq` on this record is
        the point in capture order at which the direction went dark; the
        UNVERIFIED contract's "named cause" originates here.
        """
        try:
            self._append(
                {
                    "kind": "capture_error",
                    "dir": direction,
                    "cause": f"{type(cause).__name__}: {cause}",
                }
            )
        except Exception as exc:  # the writer itself is what broke
            # Do not try to write the failure to the thing that just failed.
            # Say it where someone will see it and let forwarding carry on.
            print(
                f"belay: trace writer failed while recording a capture error on "
                f"{direction} ({type(cause).__name__}: {cause}); trace is incomplete: {exc}",
                file=sys.stderr,
            )

    def _append(self, record: dict[str, Any]) -> None:
        with self._lock:
            seq = self._seq
            self._seq += 1
            # Timing is assembled here but never enters either hash: both are
            # computed over frame content alone. If `t_in` fed a hash, two
            # identical runs could never agree, and "the replay produced the
            # same bytes" would stop being expressible at all.
            line = json.dumps(
                {
                    "v": SCHEMA_VERSION,
                    **record,
                    "seq": seq,
                    "t_in": _now(),
                    "observation_point": "proxy",
                },
                ensure_ascii=False,
            )
            _write_all(self._fd, line.encode("utf-8") + b"\n")

    def close(self) -> None:
        with self._lock:
            if self._fd >= 0:
                os.close(self._fd)
                self._fd = -1
