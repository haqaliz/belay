"""The `tools/list` probe: ask the replay boundary what it offers (aspect A1, phase 3).

The probe answers ONE question — *does this boundary offer this tool?* — by actually
spawning the boundary the way a replay does and reading its `tools/list`. Everything
here defends one contract, which is the whole point of the unit:

    a set of names   the boundary answered, and this is what it offers
    set()            the boundary answered, and it offers NOTHING
    None             the probe could not run, or its answer could not be read

`set()` and `None` are DIFFERENT FACTS and are never interchangeable. Collapsing them
is how "absence of evidence" becomes "evidence of absence" — the PRD's M4, and the
reason the empty-set case below is asserted with an explicit `is not None`.

The probe also must never raise into the verdict path: a spawn that fails, a server
that dies mid-handshake, a reply that is not JSON — each is `None`, never a traceback
escaping into `verify_turn`.

## What is gated and what is not

The reply-reading half is a pure function over bytes, so it is tested by feeding it
bytes and runs on **both** platforms. Only the tests that drive a REAL spawn are
darwin-gated (`replay-reinvokes-seatbelt`), because `replay_turn` re-invokes inside
the macOS Seatbelt sandbox. That split is deliberate: the three-way contract itself —
the thing most likely to regress — is not hostage to the platform.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fixtures.toolset_probe_server import MODE_ENV, TOOL_NAMES

from belay.replay.client import (
    ANSWERED,
    NO_REPLY_EXPECTED,
    SERVER_EXITED,
    TIMED_OUT,
    FrameOutcome,
)
from belay.replay.persist import persist_snapshot
from belay.replay.probe import _offered_from_outcomes, offered_tools, probe_frames
from belay.snapshot.substrate import take_snapshot

# --- The frames the probe sends ----------------------------------------------


def test_the_probe_sends_only_a_handshake_and_a_tools_list():
    """It asks a question; it never enters the replayed conversation.

    The recorded frames belong to the replay. A probe that injected a `tools/call`
    — or any recorded frame — would change what the server is sent and break the
    byte-identical no-op guarantee the aspect rests on. So the frame list is pinned:
    an `initialize`, the `notifications/initialized` a conforming client owes the
    server, and a `tools/list`. Nothing else, ever.
    """
    import json

    frames = probe_frames()
    methods = [json.loads(frame).get("method") for frame in frames]
    assert methods == ["initialize", "notifications/initialized", "tools/list"], (
        f"the probe sends something other than a bare handshake: {methods!r}"
    )
    assert not any(b"tools/call" in frame for frame in frames), (
        "the probe would enter the replayed conversation"
    )
    # The two requests must carry distinct ids, or `converse` cannot tell the
    # tools/list reply from the initialize reply.
    ids = [json.loads(frame).get("id") for frame in frames]
    assert ids[0] != ids[2] and ids[1] is None


# --- The three-way contract, read off the outcomes ---------------------------


def _outcomes(tools_reply: bytes | None, *, status: str = ANSWERED) -> list[FrameOutcome]:
    """The outcome list a probe conversation produces, with a chosen tools/list reply."""
    frames = probe_frames()
    return [
        FrameOutcome(index=0, frame=frames[0], status=ANSWERED, reply=b'{"jsonrpc":"2.0","id":"belay-probe-init","result":{}}'),
        FrameOutcome(index=1, frame=frames[1], status=NO_REPLY_EXPECTED),
        FrameOutcome(index=2, frame=frames[2], status=status, reply=tools_reply),
    ]


def test_a_readable_tools_list_becomes_the_set_of_names():
    reply = (
        b'{"jsonrpc":"2.0","id":"belay-probe-tools","result":{"tools":'
        b'[{"name":"read_text_file"},{"name":"run_process"}]}}'
    )
    assert _offered_from_outcomes(_outcomes(reply)) == {"read_text_file", "run_process"}


def test_an_empty_tools_list_is_an_empty_set_and_not_none():
    """THE distinction. `set()` means "answered, offers nothing"; `None` means "unread".

    A probe that returned `None` here would report a boundary that truthfully declared
    an empty toolset as a probe FAILURE — and the caller would abstain with the wrong
    cause. A probe that returned `set()` for an unread answer would assert a fact it
    never established. Both directions are wrong; only this test separates them.
    """
    result = _offered_from_outcomes(
        _outcomes(b'{"jsonrpc":"2.0","id":"belay-probe-tools","result":{"tools":[]}}')
    )
    assert result == set() and result is not None, (
        f"an empty answer and an unreadable one were conflated: {result!r}"
    )


@pytest.mark.parametrize(
    "reply, why",
    [
        (b"not json at all", "unparseable bytes"),
        (b"", "an empty reply line"),
        (b'{"jsonrpc":"2.0","id":"belay-probe-tools","result":{}}', "no result.tools"),
        (b'{"jsonrpc":"2.0","id":"belay-probe-tools","result":{"tools":{}}}', "tools is not a list"),
        (b'{"jsonrpc":"2.0","id":"belay-probe-tools","result":"nope"}', "result is not an object"),
        (b'{"jsonrpc":"2.0","id":"belay-probe-tools","error":{"code":-32601,"message":"no"}}', "an error reply"),
        (b'{"jsonrpc":"2.0","id":"belay-probe-tools","result":{"tools":["read_text_file"]}}', "a tool entry that is not an object"),
        (b'{"jsonrpc":"2.0","id":"belay-probe-tools","result":{"tools":[{"description":"x"}]}}', "a tool entry with no name"),
        (b'{"jsonrpc":"2.0","id":"belay-probe-tools","result":{"tools":[{"name":7}]}}', "a tool name that is not a string"),
        (b'["a","batch"]', "a JSON array rather than an object"),
    ],
)
def test_an_unreadable_answer_is_none_never_an_empty_set(reply: bytes, why: str):
    """Fail-closed on every unreadable shape — and `None`, not `set()`.

    Each of these is a reply the probe cannot read as a toolset. Returning `set()`
    for any of them would say "this boundary offers nothing", which is a claim about
    the boundary that was never established.
    """
    result = _offered_from_outcomes(_outcomes(reply))
    assert result is None, f"{why} was read as an answer: {result!r}"


@pytest.mark.parametrize("status", [TIMED_OUT, SERVER_EXITED])
def test_a_tools_list_that_was_never_answered_is_none(status: str):
    assert _offered_from_outcomes(_outcomes(None, status=status)) is None


def test_a_conversation_that_never_reached_tools_list_is_none():
    """The server died after the handshake: there is no tools/list outcome at all."""
    frames = probe_frames()
    outcomes = [
        FrameOutcome(index=0, frame=frames[0], status=ANSWERED, reply=b'{"jsonrpc":"2.0","id":"x","result":{}}'),
        FrameOutcome(index=1, frame=frames[1], status=SERVER_EXITED),
    ]
    assert _offered_from_outcomes(outcomes) is None
    assert _offered_from_outcomes([]) is None


# --- `offered_tools`: the spawning half --------------------------------------
#
# Two tests below run WITHOUT a real spawn, on purpose: the never-raise contract and
# the pass-through of the caller's replay context are the parts a caller depends on
# and are not platform facts. Everything after them drives a real boundary.


def test_the_probe_never_raises_into_the_caller(tmp_path):
    """Any exception out of the replay machinery becomes `None`, never a traceback.

    The probe is called from inside `verify_turn`. An exception escaping it would turn
    a verdict into a crash — strictly worse than the false FAIL it exists to fix — so
    the contract is that it swallows everything and says so by returning `None`.
    """
    from belay.replay import probe as probe_module

    class _Boom(Exception):
        pass

    def _raise(*args, **kwargs):
        raise _Boom("the sandbox refused, the snapshot was gone, anything at all")

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(probe_module, "replay_turn", _raise)
        assert (
            probe_module.offered_tools(
                ["/nonexistent/server"], snapshot_manifest=tmp_path / "manifest.json"
            )
            is None
        )
    finally:
        monkey.undo()


def test_the_replay_context_is_passed_through_unchanged(tmp_path):
    """The probe asks the SAME boundary the replay uses — same argv, manifest, root.

    A probe that quietly dropped `source_root` would spawn an absolute-path server
    rooted at the original workspace and answer about a different boundary than the
    one the verdict is about. The timeout is threaded for the same reason: the caller
    bounds the probe, not this module.
    """
    from belay.replay import probe as probe_module
    from belay.replay.client import ANSWERED, FrameOutcome, ReplayResult

    seen: dict = {}

    def _record(server_command, **kwargs):
        seen["argv"] = server_command
        seen.update(kwargs)
        frames = kwargs["frames"]
        return ReplayResult(
            outcomes=[
                FrameOutcome(
                    index=2,
                    frame=frames[2],
                    status=ANSWERED,
                    reply=b'{"jsonrpc":"2.0","id":"belay-probe-tools-list","result":{"tools":[{"name":"echo"}]}}',
                )
            ],
            workspace=str(tmp_path),
        )

    manifest = tmp_path / "manifest.json"
    policy = object()
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(probe_module, "replay_turn", _record)
        assert probe_module.offered_tools(
            ["/bin/server", "--root", "/w"],
            snapshot_manifest=manifest,
            source_root="/w",
            network=policy,
            timeout=3.5,
        ) == {"echo"}
    finally:
        monkey.undo()

    assert seen["argv"] == ["/bin/server", "--root", "/w"]
    assert seen["snapshot_manifest"] == manifest
    assert seen["source_root"] == "/w"
    assert seen["network"] is policy
    assert seen["timeout"] == 3.5
    assert seen["frames"] == probe_frames(), (
        "the probe sent something other than its own handshake"
    )


# --- Real spawns -------------------------------------------------------------

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox",
)

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING = FIXTURES / "conforming_server.py"
TOOLSET = FIXTURES / "toolset_probe_server.py"
DIES_MIDWAY = FIXTURES / "dies_midway_server.py"
HANGS = FIXTURES / "minting_driver_hang_server.py"


def _manifest(tmp_path: Path) -> Path:
    """A real persisted snapshot of a one-file workspace — the probe restores it."""
    original = tmp_path / "original"
    original.mkdir()
    (original / "keep.txt").write_text("a workspace the probe restores")
    snap = take_snapshot(original, tmp_path / "snap")
    manifest = tmp_path / "manifest.json"
    persist_snapshot(snap, manifest)
    return manifest


@darwin_only
def test_a_tool_the_boundary_serves_is_in_the_offered_set(tmp_path):
    """The offered case, against a real spawned boundary — and the not-offered one.

    `conforming_server.py` serves exactly one tool, `echo`. Both halves of the
    discrimination are asserted here on the same answer: `echo` is present, and
    `run_process` — the tool the PRD's repro turns on — is absent from a set that is
    NOT empty. A probe that returned an empty set on every boundary would pass the
    absence half alone; the non-emptiness is what makes it mean something.
    """
    offered = offered_tools(
        [sys.executable, str(CONFORMING)], snapshot_manifest=_manifest(tmp_path), timeout=15.0
    )
    assert offered is not None, "the probe could not read a conforming boundary"
    assert "echo" in offered
    assert "run_process" not in offered
    assert offered == {"echo"}


@darwin_only
def test_a_boundary_that_offers_nothing_answers_with_an_empty_set(tmp_path, monkeypatch):
    """The distinction, end to end: an answered empty toolset is `set()`, not `None`.

    This is the same fact the byte-level test pins, driven through a real spawn so the
    transport is in the loop: the server really did answer `{"tools": []}`, and the
    probe really did read it.
    """
    monkeypatch.setenv(MODE_ENV, "empty")
    offered = offered_tools(
        [sys.executable, str(TOOLSET)], snapshot_manifest=_manifest(tmp_path), timeout=15.0
    )
    assert offered == set() and offered is not None, (
        f"an honest empty toolset was read as a probe failure: {offered!r}"
    )


@darwin_only
def test_a_boundary_whose_reply_carries_no_tools_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv(MODE_ENV, "no-tools")
    assert (
        offered_tools(
            [sys.executable, str(TOOLSET)], snapshot_manifest=_manifest(tmp_path), timeout=15.0
        )
        is None
    )


@darwin_only
def test_a_boundary_that_serves_tools_is_read_from_a_real_spawn(tmp_path, monkeypatch):
    """The fixture's default mode, so the empty/no-tools modes above are not vacuous."""
    monkeypatch.delenv(MODE_ENV, raising=False)
    assert offered_tools(
        [sys.executable, str(TOOLSET)], snapshot_manifest=_manifest(tmp_path), timeout=15.0
    ) == set(TOOL_NAMES)


@darwin_only
def test_a_spawn_that_fails_is_none_not_a_crash_and_not_an_empty_set(tmp_path):
    """A boundary that cannot even start told us nothing about what it offers."""
    offered = offered_tools(
        [str(tmp_path / "no-such-binary")], snapshot_manifest=_manifest(tmp_path), timeout=5.0
    )
    assert offered is None, f"a failed spawn was read as an answer: {offered!r}"


@darwin_only
def test_a_server_that_dies_midway_is_none(tmp_path):
    """It answers the handshake and leaves — so `tools/list` never comes back."""
    offered = offered_tools(
        [sys.executable, str(DIES_MIDWAY)], snapshot_manifest=_manifest(tmp_path), timeout=5.0
    )
    assert offered is None, f"a half-dead boundary was read as an answer: {offered!r}"


@darwin_only
def test_a_server_that_never_replies_is_bounded_by_the_timeout(tmp_path):
    """The wait is bounded, so a silent boundary is `None` rather than a hung verdict.

    No wall-clock is asserted — the suite completing at all is the evidence, and a
    clock assertion would make a green run depend on the machine's load. What the
    caller's timeout reaches is pinned separately, without a spawn, above.
    """
    offered = offered_tools(
        [sys.executable, str(HANGS)], snapshot_manifest=_manifest(tmp_path), timeout=0.5
    )
    assert offered is None
