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
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from belay.hashing import CANONICAL_FORM, canonical_hash, hash_bytes

SCHEMA_VERSION = 1

# The reader's contract, stated once here and in docs/technical/TRACE_FORMAT.md:
# a record whose `kind` is unknown, or whose `v` is higher than the reader
# understands, must be SKIPPED and the skip recorded. Never dropped silently
# (that is a false-completeness claim), never fatal (an old reader must survive
# a new writer). C2 appends `denial`; C3 appends `nondeterminism`.
KINDS = (
    "frame",
    "capture_error",
    "connection_window",
    # C2's sandbox. Both are FACTS about what was applied and what the child
    # reported — neither is verdict-shaped. C2 does not decide replayability.
    "denial",
    "network_policy",
)

# The three states the `state_handle` slot may hold, and the reason it is three
# and not two is in `set_state_handle` and in docs/technical/TRACE_FORMAT.md.
# "absent" is never a synonym for failure.
_STATE_HANDLE_STATUSES = frozenset({"absent", "present", "unrestorable"})

# The direction a request travels, and the only one a `state_handle` can be
# pinned to a frame on. Named here rather than imported from `belay.sandbox.gate`:
# the writer must not depend on the snapshot backend it is meant to outlive.
_CLIENT_TO_SERVER = "c2s"
_SERVER_TO_CLIENT = "s2c"

#: How long a response's record waits for its request's record before recording
#: anyway, out of order. The window it covers is one base64, two hashes and one
#: `write` — microseconds, and ~100 ms for a MAX_FRAME frame — so this is four
#: orders of magnitude of headroom. It is not a latency budget: in the causal case
#: the wait is zero, and only a response whose request never crosses (a
#: non-conforming server) ever reaches the deadline. Kept small for that reason —
#: every extra second here is paid by the pathological case alone.
REQUEST_WAIT_TIMEOUT = 2.0

#: The request index is monotone (see `_note_requests_locked`), so it is capped
#: rather than drained. Large enough that no real session evicts a key whose reply
#: is still in flight; small enough that a long-lived proxy cannot grow without
#: bound.
_REQUEST_INDEX_MAX = 4096

Observer = Callable[[bytes, bool], None]


def _classify(message: Any) -> str:
    """`request` | `response` | `notification` | `unknown`, from structure alone.

    **Identical to `belay.index.classify`, and pinned to it by a test.** It is
    re-implemented here rather than imported because the recorder must not depend on
    a derivation that reads what the recorder wrote — but it must agree with it
    exactly, or the writer would defer on a key the reader never builds and the
    deferral would protect nothing.

    Order matters: `result`/`error` is checked first, so a response is still a
    response when a non-conforming server also stamps `method` on it. One such
    server exists in this repo's own fixtures.
    """
    if not isinstance(message, dict):
        return "unknown"
    if "result" in message or "error" in message:
        return "response"
    if "method" in message:
        return "request" if "id" in message else "notification"
    return "unknown"


def _key(identifier: Any) -> Optional[tuple]:
    """The id's index key, with its type in it — or None if it cannot be one.

    The type is in the key for the reason `belay.index._id_key` gives: Python
    conflates ids JSON-RPC keeps apart (`1 == True`, `1 == 1.0`, and `"1"` is not
    `1` on the wire). A container id is illegal JSON-RPC and unhashable besides,
    so it gets no key at all and nothing waits on it.
    """
    if isinstance(identifier, (list, dict)):
        return None
    return (type(identifier).__name__, identifier)


def _messages(frame: bytes) -> tuple:
    """Every message in `frame`: one object, or the members of a JSON-RPC batch.

    A frame that cannot be parsed yields nothing. Nothing here is a judgement about
    the frame — an unreadable frame is carried verbatim and named by the readers,
    exactly as before; it simply contributes no key and waits for nothing.
    """
    try:
        message = json.loads(frame)
    except (ValueError, RecursionError):
        return ()
    return tuple(message) if isinstance(message, list) else (message,)


def _request_keys(frame: bytes) -> list[tuple]:
    """The index keys of every client request in `frame`.

    Batches are unpacked for the same reason `belay.sandbox.gate` unpacks them: the
    2025-03-26 revision permitted them, so a client on that revision can legally put
    a request inside an array. Indexing one costs nothing and can only ever release
    a waiter that was going to wait for exactly that id.
    """
    keys = []
    for message in _messages(frame):
        if _classify(message) != "request":
            continue
        key = _key(message.get("id"))
        if key is not None:
            keys.append(key)
    return keys


def _awaited_key(frame: bytes) -> Optional[tuple]:
    """The key of the request `frame` answers, or None if it answers nothing.

    Deliberately narrow, and every narrowing is a case the reader also refuses to
    pair: a batch (the reader names the shape rather than pairing it), a
    server-originated request, a notification, an unparseable frame, a container id.
    Waiting on any of those would be a guess, and a guess here buys a stall.
    """
    try:
        message = json.loads(frame)
    except (ValueError, RecursionError):
        return None
    # A top-level object, never a batch array — a one-member array is still an
    # array, and the reader names its shape rather than pairing it.
    if not isinstance(message, dict) or _classify(message) != "response":
        return None
    return _key(message.get("id"))


class TraceClosed(Exception):
    """An append arrived after the connection window closed.

    Named, rather than the `OSError: Bad file descriptor` that writing to a
    closed fd used to raise from deep inside `_append`. The distinction matters:
    a bad fd is indistinguishable from the disk having broken, so it degrades to
    a stderr line while the trace keeps its matched open/close pair and reads as
    a complete capture. This says exactly one thing — the window has closed, and
    this observation is outside what the trace claims to have seen.

    The proxy's capture gate stops observation before the writer closes, so this
    should be unreachable through it. It exists so that "unreachable" is a
    property the writer states rather than one it assumes about its callers.
    """


class TraceClaimError(Exception):
    """A `claim` record could not be appended to a trace file.

    Named, rather than the `FileNotFoundError` or `json.JSONDecodeError` that
    a naive read would surface from inside `append_claim_record`. The
    distinction matters: an unrecorded claim is an unjudged instance, and the
    driver must be able to tell "the claim did not land and nothing judged
    this instance" from "the trace vanished" or "the trace was corrupted". All
    three are one refusal, so that a missing or malformed trace can never
    masquerade as a completed claim append.
    """


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
    reader would have to reconcile.

    **The ordering between directions is "when the proxy saw it", with exactly one
    guarantee laid over it: a response is never recorded before the request it
    answers.** That sentence used to have no exception, and the exception is the
    fix. The pump forwards a chunk and observes it afterwards — *"forwarding must
    never wait on the recorder"* — so both directions run ahead of the trace, and a
    server fast enough could have its RESPONSE recorded before its own REQUEST. An
    inverted pair does not correlate (`derive_correlation` pairs a request with a
    *later* response), so `derive_annotations` took no `tools/list` snapshot and
    effect-conformance abstained for the whole run: honest, and a real coverage-loss
    path for any fast local server.

    So an s2c response defers its own record until its request's record is on disk —
    **bounded and fail-open**: past `REQUEST_WAIT_TIMEOUT` it records anyway, out of
    order, and the readers name what they see exactly as they did before. The wait
    releases the lock (it is a `Condition` over it), so the other direction — the one
    it is waiting for — is never blocked by it. Nothing else moves: the frame being
    recorded has already been forwarded, `observation_point` still says `proxy`, and
    no field or record kind is added.
    """

    def __init__(self, path: Path, request_wait: float = REQUEST_WAIT_TIMEOUT) -> None:
        self._path = path
        # O_EXCL: never adopt a file someone else made, so the 0o600 below is a
        # property of a file we created rather than a hope about one we found.
        # The mode is passed to open() rather than chmod'ed afterwards, leaving
        # no window in which the trace exists and is world-readable.
        self._fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._lock = threading.Lock()
        # Over the SAME lock, deliberately: the index must be updated atomically
        # with the append it describes (a waiter that sees a key must know the
        # record is on disk), and a waiter must release that lock while parked or
        # the very record it waits for could never be written.
        self._ready = threading.Condition(self._lock)
        self._request_wait = request_wait
        # Insertion-ordered, and MONOTONE: a key stays once written. Draining it on
        # the answering response would make a `duplicate-response` — a real,
        # reader-named thing a non-conforming server does — wait out the whole
        # deadline for a request recorded long ago. Bounded by eviction instead.
        self._recorded_requests: dict[tuple, None] = {}
        self._seq = 0
        self._closed = False
        # The slot's default, and the only value C1 could ever write. C2 sets
        # this when it attempts a snapshot; see `set_state_handle`.
        self._state_handle: dict[str, Any] = {"status": "absent"}
        # Handles pinned to the exact frame they describe, by content hash. Each
        # is claimed by the frame that earned it and then gone. Two things can
        # leave one unclaimed, and neither is silent: a frame gated but never
        # observed (the trace says so — `capture_error`, or a closed window), and
        # a frame over MAX_FRAME, whose observed copy is truncated and therefore
        # hashes differently than the whole frame the gate saw. The second falls
        # back to the sticky handle and is already marked `truncated: true`, which
        # is the flag that says do not ground anything on this record.
        self._pinned: dict[str, list[dict[str, Any]]] = {}
        self._append({"kind": "connection_window", "phase": "open"})

    @classmethod
    def in_directory(
        cls, directory: str | Path, request_wait: float = REQUEST_WAIT_TIMEOUT
    ) -> "TraceWriter":
        directory = Path(directory)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return cls(
            directory / f"trace-{stamp}-{uuid.uuid4().hex[:8]}.jsonl",
            request_wait=request_wait,
        )

    @property
    def path(self) -> Path:
        return self._path

    def set_state_handle(self, handle: dict[str, Any], *, frame: bytes | None = None) -> None:
        """Set what the `state_handle` slot says, for `frame` and for what follows.

        The handle is **passed in**, not derived here. The writer deliberately
        does not know what any cause means, cannot take a snapshot, and cannot
        tell `UNRESTORABLE_FIFO` from `UNRESTORABLE_SOCKET` — that knowledge is
        C2's (`belay.snapshot.substrate`), and importing it here would put the
        trace format at the mercy of the snapshot backend it is supposed to
        outlive.

        What the writer *does* enforce is that the slot cannot say something the
        format does not define, and — the load-bearing one — that it can never
        say `unrestorable` without naming a cause. A refusal that names nothing
        is indistinguishable downstream from a shrug, and C4 turns this slot
        into UNVERIFIED by reading exactly this field.

        Set on the writer rather than threaded through `observer`, because the
        observer signature is the proxy's and a frame's handle is a property of
        the run's state at that moment, not of the bytes.

        **`frame` is what makes the answer per-frame rather than per-chunk.** The
        sticky slot alone describes "whatever is recorded next", and the pump
        forwards a whole chunk before observing any of it — so when one chunk
        carries two gated frames, both are set before either is recorded and both
        read the last value. At least one then names a state handle that is not
        its own. Passing the frame registers this handle *for those exact bytes*,
        claimed once, when they are recorded.

        Frames are matched by content hash, not by arrival order: order would put
        the trace's correctness at the mercy of two modules agreeing forever about
        which frames they each skip, and a drift would silently shift every handle
        by one. Identical bytes gated twice queue up and are claimed in order,
        which is the only reading that can be right when the bytes cannot tell the
        two apart.
        """
        status = handle.get("status")
        if status not in _STATE_HANDLE_STATUSES:
            raise ValueError(
                f"state_handle status {status!r} is not one of "
                f"{sorted(_STATE_HANDLE_STATUSES)}"
            )
        if status == "unrestorable" and not handle.get("cause"):
            raise ValueError(
                "an unrestorable state_handle must name a cause: an unnamed "
                "refusal cannot be told from a silence by anything downstream"
            )
        with self._lock:
            self._state_handle = dict(handle)
            if frame is not None:
                self._pinned.setdefault(hash_bytes(frame), []).append(dict(handle))

    def _handle_for(self, direction: str, digest: str) -> dict[str, Any]:
        """This frame's own handle if one was pinned for it, else the sticky one.

        c2s only: a handle describes the state a *request* was about to execute
        against, and nothing on the way back is a turn. Consulting the pin from
        both directions would let a reply that happened to be byte-identical to a
        pending request claim that request's snapshot.
        """
        with self._lock:
            pinned = self._pinned.get(digest) if direction == _CLIENT_TO_SERVER else None
            if not pinned:
                return dict(self._state_handle)
            handle = pinned.pop(0)
            if not pinned:
                del self._pinned[digest]
            return handle

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
        # A truncated frame is a fragment, and `belay.frames` already refuses to
        # read one: half a message parsed as if it were the message would index or
        # wait on an id that may not be the one on the wire.
        readable = not truncated
        requests = (
            _request_keys(frame)
            if readable and direction == _CLIENT_TO_SERVER
            else []
        )
        # BEFORE the wait, so a deferred record carries the handle that was current
        # when the frame was SEEN. The deferral must not move any other field's
        # meaning, and the sticky slot changes as the other direction proceeds.
        handle = self._handle_for(direction, digest)
        if readable and direction == _SERVER_TO_CLIENT:
            self._await_request(_awaited_key(frame))
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
                # Three-state from day one, and filled by C2 via
                # `set_state_handle`. If this slot could only say
                # present/absent, C2 would have to overload "absent" to mean
                # both "recorded before snapshots existed" and "we tried to
                # snapshot and failed" - and a replay that cannot tell those
                # apart is how a false PASS gets born. It still defaults to
                # `absent`, which keeps meaning exactly "no snapshot was
                # attempted": a frame from a run without snapshots must not
                # start claiming anything else.
                "state_handle": handle,
            },
            requests=requests,
        )

    def _await_request(self, key: Optional[tuple]) -> None:
        """Block until `key`'s request record exists — bounded, and fail-open.

        Three ways out, and all three are honest. The key arrives (the ordinary
        one, and typically instant: the request was forwarded before the server
        could answer, so its record is a hash and a write away). The writer closes,
        which the append after this reports as `TraceClosed` — the existing
        contract, unchanged. Or the deadline expires, and the record lands out of
        order: no new record kind, no invented cause, and the readers name the pair
        exactly as they do today (`response-without-request` + `unanswered`). What
        must never happen is a wait with no end, which would turn a
        non-conforming server into a hung recorder.

        No lock deadlock: the record this waits for is written by the *other*
        direction, which never waits, and `Condition.wait` releases the lock while
        parked.

        **The PIPE cycle is why the deadline is not optional.** The pump calls this
        synchronously, so a parked response stops that direction being read. A server
        that then floods its stdout fills the pipe and blocks, stops reading its
        stdin, and blocks the other pump mid-write — so the record being waited for
        cannot arrive. A legitimate pair cannot enter that cycle (a reply proves the
        request was forwarded, and the c2s record follows its forward with only a
        hash in between, before the pump can block on anything else), but an ORPHAN
        response can. The deadline is what makes that a bounded pause instead of a
        wedged proxy.
        """
        if key is None:
            return
        deadline = time.monotonic() + self._request_wait
        with self._ready:
            while key not in self._recorded_requests and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self._ready.wait(remaining)

    def _note_requests_locked(self, keys: Sequence[tuple]) -> None:
        """Index `keys`, then wake every waiter. `self._lock` is already held.

        Called only after the line is on disk, which is what makes "a waiter that
        sees the key knows the record exists" true rather than nearly true.

        The oldest key goes when the index is full, never the newest: the newest is
        the one a reply is most likely still in flight for, and evicting it would
        reintroduce exactly the stall this index exists to prevent.
        """
        for key in keys:
            self._recorded_requests[key] = None
        while len(self._recorded_requests) > _REQUEST_INDEX_MAX:
            del self._recorded_requests[next(iter(self._recorded_requests))]
        self._ready.notify_all()

    def record(self, kind: str, **fields: Any) -> None:
        """Append one record of `kind`. The extension point the format was built for.

        `kind` is extensible by design (see `KINDS`), so a later capability adds
        a record type without a schema break — the reader's contract already says
        an unknown `kind` is skipped and the skip recorded. This exists so those
        capabilities append through the writer's own envelope (`v`, `seq`, `t_in`,
        `observation_point`) rather than reaching past it into `_append`, which
        would put the format's guarantees at the mercy of every caller.
        """
        self._append({"kind": kind, **fields})

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

    def _append(self, record: dict[str, Any], requests: Sequence[tuple] = ()) -> None:
        with self._lock:
            if self._closed:
                raise TraceClosed(
                    f"the connection window closed; {record.get('kind')!r} was observed "
                    f"outside the period this trace claims to have seen"
                )
            self._append_locked(record)
            if requests:
                # After the write, inside the same lock. A key published before the
                # line landed would release a waiter into recording ahead of the
                # record it was waiting for — the defect, reintroduced one line
                # further down.
                self._note_requests_locked(requests)

    def _append_locked(self, record: dict[str, Any]) -> None:
        """Allocate `seq` and write, with `self._lock` already held.

        Separate from `_append` so that `close()` can decide it is closing,
        write the record that says so, and release the fd without ever dropping
        the lock in between. Any window in there is one in which a frame lands
        at a higher seq than the close that claims to bracket it.
        """
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
        """Record that observation stopped, then stop.

        The pair of `connection_window` records is the only statement in the
        trace about the period the proxy was *live* — which is the denominator
        for "how much of what the agent did crossed the MCP boundary at all". The
        frames alone cannot say it: the first frame is when the agent first
        spoke, not when Belay started listening, and the two are not the same
        claim.

        **Connection, not session, and the reason outlives the label:** the
        2026-07-28 revision says "an open connection, such as a STDIO process, is
        not a conversation or session: clients may interleave unrelated requests
        on the same transport, and a server must not treat connection or process
        identity as a proxy for conversation or session continuity." What the two
        records below bracket is one open pipe to one server process. Calling
        that a session would claim a continuity the protocol explicitly refuses
        to grant.

        A trace with an `open` and no `close` is therefore honest and expected:
        the proxy was killed, and the window's end is genuinely unknown rather
        than "the last frame we happened to see".

        **Closing is one decision, taken once, under one lock.** The check, the
        close record and the fd all move together: released in between, two
        callers both pass the check and append two closes to one window, and a
        frame racing the close lands at a higher seq than the record asserting
        the window had already shut. The proxy stops observation before calling
        this (see `_CaptureGate`), so by here the writer is idle — this is what
        makes that true rather than hoped for.
        """
        with self._lock:
            if self._closed:
                return
            self._append_locked({"kind": "connection_window", "phase": "close"})
            self._closed = True
            os.close(self._fd)
            self._fd = -1
            # Nothing more will ever be recorded, so a parked response is waiting
            # for a record that cannot come. Wake it here rather than let it sit on
            # its deadline holding up a shutdown it can no longer contribute to.
            self._ready.notify_all()


def append_claim_record(path: Path, *, text: str | None = None) -> int:
    """Append one `claim` record to a closed trace file; return its `seq`.

    The trajectory rule needs the agent's final success claim to judge, but
    the proxy only records what crossed the wire, and the claim never does —
    the model client parses `Done` itself. This is the format's answer: the
    minting driver appends the claim **after the proxy has exited**, so the
    envelope is reproduced here rather than going through a `TraceWriter`
    (whose fd is long closed). The envelope matches `_append_locked`'s shape
    exactly except for `observation_point: "session"` — the observer is the
    driver, not the proxy, and the record must not lie about who saw what.

    `seq` continues the capture's sequence: it is read from the last recorded
    line, so appends are strictly increasing and never duplicate or gap. A
    missing file, an empty file, an unparseable last line, or a last line
    whose `seq` is absent, not an int, or negative raises `TraceClaimError` —
    an unrecorded claim is an unjudged instance and must not masquerade as
    anything else.

    `text` is the claim text when there is one; the key is **absent** (never
    `""`) when `text` is `None` or whitespace-only, because an empty string
    would occupy a meaning it doesn't have.

    **Only for appending after the writer has closed.** This function reads
    and appends to the file directly, with no lock of its own: it is for the
    sequential, post-close driver path, never for racing a live writer.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise TraceClaimError(f"no trace file to append a claim to: {path}") from None
    lines = [line for line in data.split(b"\n") if line.strip()]
    if not lines:
        raise TraceClaimError(
            f"the trace file is empty, so no claim can continue its sequence: {path}"
        )
    try:
        last = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise TraceClaimError(
            f"the last recorded line is not a record, so the claim cannot be "
            f"numbered: {exc}"
        ) from None
    if not isinstance(last, dict) or "seq" not in last:
        raise TraceClaimError(
            "the last recorded line has no usable `seq`, so the claim cannot be "
            "numbered in the capture's sequence"
        )
    seq = last["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise TraceClaimError(
            f"the last recorded `seq` is {seq!r}, not a non-negative int, so the "
            f"claim cannot be numbered in the capture's sequence"
        )
    record: dict[str, Any] = {"kind": "claim"}
    if text is not None and text.strip():
        record["text"] = text
    line = json.dumps(
        {
            "v": SCHEMA_VERSION,
            **record,
            "seq": seq + 1,
            "t_in": _now(),
            "observation_point": "session",
        },
        ensure_ascii=False,
    )
    fd = os.open(path, os.O_APPEND | os.O_WRONLY)
    try:
        _write_all(fd, line.encode("utf-8") + b"\n")
    finally:
        os.close(fd)
    return seq + 1
