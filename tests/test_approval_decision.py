"""The approval gate's pure decision core: parse a frame, decide, hold.

Aspect `approval-gate/decision-model` (spec.md). Everything here is a pure
function of bytes and dicts — no I/O, no proxy coupling, no trace writes — so
the tests below drive plain frames and plain facts.

The two honesty rules that shape this module:

- **Never hold on doubt.** A frame that is not a single `tools/call` REQUEST
  (notification, response, batch, garbage) is forwarded untouched, and a
  `params.name` that is not a string yields no tool name. A hold is a state
  change the proxy makes; doubt must never manufacture one.
- **A default is not a declaration.** `triggers_for` reads the tri-state
  vocabulary from `belay.declared` — only `declared-true` on `destructiveHint`
  or `openWorldHint` triggers a hold. The MCP spec's fail-safe defaults
  (`destructiveHint: true`, `openWorldHint: true` when omitted) are exactly the
  declarations that must NOT trigger one.

Batch JSON-RPC frames (arrays) are never held: holding one would require
rewriting the frame to split it, which the proxy cannot do — they are
forwarded untouched.
"""

from __future__ import annotations

import json

import pytest

from belay.approval.gate import (
    APPROVAL_SHUTDOWN,
    APPROVAL_TIMEOUT,
    APPROVED,
    DENIED,
    TRIGGER_ANNOTATIONS,
    HoldRegistry,
    is_tools_call,
    make_hold_id,
    request_id,
    tool_name,
    triggers_for,
)
from belay.declared import (
    DECLARED_FALSE,
    DECLARED_NON_BOOLEAN,
    DECLARED_TRUE,
    NOT_DECLARED,
    declared_state,
)


def tools_call(**overrides: object) -> bytes:
    """A single `tools/call` REQUEST, as the wire would carry it (bytes)."""
    frame = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "write_file", "arguments": {"path": "/tmp/x"}},
        "id": 1,
    }
    frame.update(overrides)
    return json.dumps(frame).encode()


def test_is_tools_call_true_for_single_tools_call_requests():
    """String, int, and null ids are all valid JSON-RPC request ids."""
    assert is_tools_call(tools_call(id="abc"))
    assert is_tools_call(tools_call(id=7))
    assert is_tools_call(tools_call(id=None))


def test_is_tools_call_false_for_a_notification():
    """A `tools/call` without an `id` is a notification, never a hold candidate."""
    notification = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "write_file"},
    }
    assert not is_tools_call(json.dumps(notification).encode())


def test_is_tools_call_false_for_other_methods():
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "method": "initialize", "id": 1}).encode())
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": None}).encode())
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 2}).encode())


def test_is_tools_call_false_for_response_frames():
    """A response carries `result`/`error`, never a `method` — structurally not a call."""
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode())
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "nope"}}).encode())


def test_is_tools_call_false_for_a_batch():
    """Batch frames are arrays; the gate never holds one (see the module docstring)."""
    batch = [tools_call(id=1), tools_call(id=2)]
    assert not is_tools_call(b"[" + b",".join(batch) + b"]")


def test_is_tools_call_never_raises_on_garbage():
    """The hook runs on every c2s frame; a raise would kill the direction it guards."""
    for garbage in (b"", b"{", b"not json", b"\x00\xff\xfe", b"[]", b"null", b"42"):
        assert is_tools_call(garbage) is False


def test_tool_name_extracts_the_string_name():
    assert tool_name(tools_call()) == "write_file"
    assert tool_name(tools_call(params={"name": "read_file"})) == "read_file"


def test_tool_name_non_string_name_yields_none():
    """`params.name: 42` is not a tool name; doubt yields no hold."""
    assert tool_name(tools_call(params={"name": 42})) is None
    assert tool_name(tools_call(params={"name": None})) is None
    assert tool_name(tools_call(params={"name": {"nested": True}})) is None


def test_tool_name_absent_or_unreadable_params_yields_none():
    assert tool_name(tools_call(params={})) is None
    assert tool_name(tools_call(params=None)) is None
    # JSON-RPC 2.0 permits positional params (a list); a list has no `name`.
    assert tool_name(tools_call(params=["write_file", {}])) is None
    assert tool_name(b"garbage") is None


def test_request_id_extracts_the_json_rpc_id():
    assert request_id(tools_call(id=1)) == 1
    assert request_id(tools_call(id="abc")) == "abc"


def test_request_id_null_is_distinct_from_absent():
    """`"id": null` is a request id the wire really carried; absence is None too,
    but the pair is only ever read together with `is_tools_call`, which
    guarantees the key was present."""
    assert request_id(tools_call(id=None)) is None
    assert request_id(b"garbage") is None


def facts_of(**states: str) -> dict:
    """A `{annotation: {"state": tri-state}}` dict, the annotations.py shape."""
    return {annotation: {"state": state} for annotation, state in states.items()}


def test_triggers_for_declared_true_on_both_trigger_annotations():
    """`destructiveHint` and `openWorldHint` declared-true both trigger, in order."""
    facts = facts_of(destructiveHint=DECLARED_TRUE, openWorldHint=DECLARED_TRUE)
    assert triggers_for(facts) == ["destructiveHint", "openWorldHint"]


def test_triggers_for_only_declared_true_triggers():
    """Every other tri-state yields no trigger, on every annotation."""
    for annotation in TRIGGER_ANNOTATIONS:
        for state in (DECLARED_FALSE, NOT_DECLARED, DECLARED_NON_BOOLEAN):
            assert triggers_for(facts_of(**{annotation: state})) == []
    # And on the non-trigger annotations, even declared-true is silent.
    for annotation in ("readOnlyHint", "idempotentHint"):
        assert triggers_for(facts_of(**{annotation: DECLARED_TRUE})) == []


def test_triggers_for_absent_facts_yield_no_triggers():
    assert triggers_for(None) == []
    assert triggers_for({}) == []
    assert triggers_for(facts_of(readOnlyHint=DECLARED_TRUE)) == []


def test_triggers_for_consumes_the_annotations_shape():
    """Facts built the way `annotations.py` builds them feed `triggers_for` directly."""
    declared = {"destructiveHint": True, "readOnlyHint": False, "openWorldHint": None}
    facts = {
        annotation: declared_state(declared.get(annotation), annotation in declared)
        for annotation in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
    }
    assert facts["destructiveHint"]["state"] == DECLARED_TRUE
    assert facts["openWorldHint"]["state"] == DECLARED_NON_BOOLEAN
    assert triggers_for(facts) == ["destructiveHint"]


def test_triggers_for_malformed_entries_yield_no_triggers():
    """A bare string state or a non-dict facts value is doubt, not a declaration."""
    assert triggers_for({"destructiveHint": DECLARED_TRUE}) == []
    assert triggers_for(["destructiveHint"]) == []


class FakeClock:
    """A monotonic clock the test can wind; `time.monotonic`-shaped."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def registry(clock: FakeClock) -> HoldRegistry:
    return HoldRegistry(clock=clock)


def test_hold_resolves_exactly_once():
    """A resolved hold never re-resolves — the second resolution is refused by name.

    The registry forgets a resolved hold (it is no longer pending), so its
    refusal reads "unknown hold"; the hold itself refuses with "already
    resolved". Both refusals are by name.
    """
    clock = FakeClock()
    reg = registry(clock)
    hold = reg.register(1, "write_file", ("destructiveHint",), timeout=10.0)

    resolved = reg.resolve(hold.hold_id, "approve")
    assert resolved.cause == APPROVED
    assert resolved.decision == "approve"
    assert reg.pending() == []

    with pytest.raises(ValueError, match="unknown hold"):
        reg.resolve(hold.hold_id, "approve")
    with pytest.raises(ValueError, match="already resolved"):
        hold.resolve(APPROVED, decision="approve", now=clock.t)


def test_registry_refuses_an_unknown_hold():
    reg = registry(FakeClock())
    with pytest.raises(ValueError, match="unknown hold"):
        reg.resolve("0-never_registered", "approve")


def test_registry_refuses_an_unknown_decision():
    reg = registry(FakeClock())
    hold = reg.register(1, "write_file", ("destructiveHint",), timeout=10.0)
    with pytest.raises(ValueError, match="not a human decision"):
        reg.resolve(hold.hold_id, "maybe")


def test_a_decision_observed_before_the_deadline_wins():
    """At the deadline the timeout owns the resolution; just before it, the human does."""
    clock = FakeClock()
    reg = registry(clock)
    early = reg.register(1, "write_file", ("destructiveHint",), timeout=10.0)
    late = reg.register(2, "write_file", ("destructiveHint",), timeout=10.0)

    clock.t = 9.999
    resolved = reg.resolve(early.hold_id, "deny")
    assert resolved.cause == DENIED
    assert resolved.decision == "deny"

    clock.t = 10.0
    with pytest.raises(ValueError, match="deadline reached"):
        reg.resolve(late.hold_id, "approve")


def test_sweep_resolves_each_expired_hold_as_timeout():
    clock = FakeClock()
    reg = registry(clock)
    soon = reg.register(1, "write_file", ("destructiveHint",), timeout=10.0)
    later = reg.register(2, "run_process", ("openWorldHint",), timeout=100.0)

    clock.t = 50.0
    timed_out = reg.sweep()

    assert [h.hold_id for h in timed_out] == [soon.hold_id]
    assert soon.cause == APPROVAL_TIMEOUT
    assert soon.decision is None
    assert later.cause is None
    assert reg.pending() == [later]


def test_timeout_decisions_are_exact_functions_of_the_injected_clock():
    """Same clock readings, same operations, same outcomes — nothing else enters."""
    def run() -> list[dict]:
        clock = FakeClock()
        reg = registry(clock)
        hold = reg.register(1, "write_file", ("destructiveHint",), timeout=10.0)
        clock.t = 10.0
        (timed_out,) = reg.sweep()
        clock.t = 20.0
        reg.close_all()
        return [
            {"cause": hold.cause, "waited": hold.waited, "deadline": hold.deadline},
            {"cause": timed_out.cause, "waited": timed_out.waited},
        ]

    assert run() == run()


def test_waited_seconds_come_from_the_injected_clock():
    clock = FakeClock()
    reg = registry(clock)
    approved = reg.register(1, "write_file", ("destructiveHint",), timeout=10.0)
    reg.register(2, "run_process", ("openWorldHint",), timeout=10.0)

    clock.t = 5.0
    reg.resolve(approved.hold_id, "approve")
    clock.t = 10.0
    (timed_out_hold,) = reg.sweep()

    assert approved.waited == 5.0
    assert timed_out_hold.waited == 10.0


def test_close_all_resolves_every_pending_hold_as_shutdown():
    clock = FakeClock()
    reg = registry(clock)
    holds = [
        reg.register(i, "write_file", ("destructiveHint",), timeout=10.0) for i in range(3)
    ]

    closed = reg.close_all()

    assert [h.hold_id for h in closed] == [h.hold_id for h in holds]
    assert all(h.cause == APPROVAL_SHUTDOWN for h in holds)
    assert reg.pending() == []
    assert reg.sweep() == []


def test_pending_holds_are_bounded_and_the_oldest_is_evicted():
    """At the cap the OLDEST pending hold is evicted — never the newest — and
    resolved, so nothing pending silently disappears (every hold is pending or
    carries a closed cause)."""
    clock = FakeClock()
    reg = registry(clock)
    first = reg.register(0, "write_file", ("destructiveHint",), timeout=10.0)

    for i in range(1, 4096):
        reg.register(i, "write_file", ("destructiveHint",), timeout=10.0)
    assert len(reg) == 4096

    newest = reg.register(4096, "run_process", ("openWorldHint",), timeout=10.0)

    assert len(reg) == 4096
    assert first.cause == APPROVAL_SHUTDOWN
    assert newest in reg.pending()
    assert reg.pending()[0] is not first


def test_make_hold_id_shape_and_determinism():
    """`<seq>-<tool-slug>`, and the same inputs always produce the same id."""
    assert make_hold_id("write_file", 0) == "0-write_file"
    assert make_hold_id("write_file", 0) == make_hold_id("write_file", 0)


def test_make_hold_id_unique_across_a_sequence():
    ids = [make_hold_id("write_file", seq) for seq in range(10)]
    assert len(set(ids)) == 10


def test_make_hold_id_sanitizes_pathological_tool_names():
    """No path separator and no empty segment can survive the slug."""
    assert make_hold_id("a/b", 3) == "3-a_b"
    assert make_hold_id("a b", 3) == "3-a_b"
    assert make_hold_id("a\\b", 3) == "3-a_b"
    assert make_hold_id("a..b", 3) == "3-a..b"
    assert make_hold_id("../x", 3) == "3-.._x"
    assert make_hold_id("café", 3) == "3-café"
    assert make_hold_id("🔥", 3) == "3-tool"


def test_make_hold_id_empty_slug_falls_back():
    """A tool name that leaves no alphanumeric character gets the `tool` slug —
    an empty segment would be unwriteable and `..` alone would name a parent."""
    for pathological in ("", "///", "..", "___"):
        assert make_hold_id(pathological, 5) == "5-tool"


def test_registry_hold_ids_carry_the_tool_and_never_reuse_the_sequence():
    clock = FakeClock()
    reg = registry(clock)
    first = reg.register(1, "write_file", ("destructiveHint",), timeout=10.0)
    second = reg.register(2, "run_process", ("openWorldHint",), timeout=10.0)

    assert first.hold_id == "0-write_file"
    assert second.hold_id == "1-run_process"

    reg.close_all()
    third = reg.register(3, "write_file", ("destructiveHint",), timeout=10.0)
    assert third.hold_id == "2-write_file"