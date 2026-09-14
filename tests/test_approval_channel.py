"""The approval channel: the directory contract, the poll, the refusal, the cache.

Aspect `approval-gate/hold-channel`. The channel is the composition object the
proxy root wires (aspect 4): request files written for the human, decision files
read atomically under a bounded fail-closed deadline, refusal bytes produced on
deny, and the tool-facts cache kept current from the live wire so `decide_c2s`
has facts at hold time.

The honesty rules that shape this module:

- **A partially-written decision is absent, never guessed.** A malformed file is
  retried to the deadline; the poll never invents a decision out of one.
- **The deadline is exact under the injected clock, in one pinned order.**
  Each tick reads the decision FIRST: a decision the poll found is a decision
  the human wrote, and the poll's granularity never costs them it. The deadline
  check runs only when no decision was found — past it, the hold is denied
  `APPROVAL_TIMEOUT` (fail-closed, never forwarded) and no later file is ever
  read again (M14: late decisions are ignored, never applied retroactively).
- **A default is not a declaration.** The live cache records what the wire said
  about each annotation through `declared.declared_state`, so an absent
  annotation and a literal `null` stay as different facts.
- **The gate never raises.** An internal fault (a channel I/O failure, a broken
  recorder) suppresses the call with a best-effort refusal and a decision record
  whose cause is `APPROVAL_FAULT` — a gate that cannot evaluate its trigger
  refuses loudly, never forwards a destructive call silently and never lets the
  client hang.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from belay.approval.gate import (
    Hold,
    make_hold_id,
)


def hold(**overrides) -> Hold:
    """A pending hold, as the registry would open one."""
    fields = dict(
        hold_id=make_hold_id("blast", 0),
        request_id=7,
        tool="blast",
        triggers=("destructiveHint",),
        timeout=300.0,
        deadline=100.0,
        created_at=0.0,
    )
    fields.update(overrides)
    return Hold(**fields)


# --- Phase 1: the request/decision file contract -----------------------------


def test_write_request_lands_the_contract_fields(tmp_path):
    from belay.approval.channel import write_request

    path = write_request(tmp_path, hold())
    assert path.name == "0-blast.json"
    assert path.parent.name == "requests"
    body = json.loads(path.read_text())
    assert set(body) == {"hold_id", "tool", "request_id", "triggers", "created_at", "timeout"}
    assert body["hold_id"] == "0-blast"
    assert body["tool"] == "blast"
    assert body["request_id"] == 7
    assert body["triggers"] == ["destructiveHint"]
    assert isinstance(body["created_at"], float)
    assert body["timeout"] == 300.0


def test_write_request_is_atomic_temp_then_rename(monkeypatch, tmp_path):
    from belay.approval.channel import write_request

    observed = []
    real_replace = os.replace

    def spy_replace(src, dst):
        src = Path(src)
        dst = Path(dst)
        # At the moment of the rename, the final name must never exist
        # half-written, and the temp must already carry the complete body.
        assert not dst.exists(), "the final name existed before the rename"
        assert src.exists(), "the temp file did not exist at the rename"
        assert json.loads(src.read_text())["hold_id"] == "0-blast"
        observed.append((src.name, dst.name))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    write_request(tmp_path, hold())

    assert len(observed) == 1
    temp_name, final_name = observed[0]
    assert temp_name.startswith(".belay-request-"), f"no temp name: {temp_name!r}"
    assert final_name == "0-blast.json"
    # The temp is a sibling of the final name: same directory, so the rename is
    # a rename, never a cross-filesystem copy.
    assert Path(tmp_path, "requests", temp_name).parent == Path(tmp_path, "requests", final_name).parent


def test_read_decision_absent_is_none(tmp_path):
    from belay.approval.channel import read_decision

    assert read_decision(tmp_path, "0-blast") is None


def test_read_decision_approve_and_deny(tmp_path):
    from belay.approval.channel import read_decision

    decisions = tmp_path / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "0-blast.json").write_text(json.dumps({"decision": "approve", "reason": "ok"}))
    assert read_decision(tmp_path, "0-blast") == {"decision": "approve", "reason": "ok"}
    (decisions / "0-blast.json").write_text(json.dumps({"decision": "deny", "reason": "no"}))
    assert read_decision(tmp_path, "0-blast") == {"decision": "deny", "reason": "no"}


def test_read_decision_malformed_json_is_none_never_raises(tmp_path):
    from belay.approval.channel import read_decision

    decisions = tmp_path / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "0-blast.json").write_text('{"decision": ')
    assert read_decision(tmp_path, "0-blast") is None


def test_read_decision_unknown_value_and_missing_key_are_none(tmp_path):
    from belay.approval.channel import read_decision

    decisions = tmp_path / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "0-blast.json").write_text(json.dumps({"decision": "maybe"}))
    assert read_decision(tmp_path, "0-blast") is None
    (decisions / "0-blast.json").write_text(json.dumps({"reason": "no decision key"}))
    assert read_decision(tmp_path, "0-blast") is None


def test_an_unusable_approval_dir_is_a_named_startup_failure(tmp_path):
    from belay.approval.channel import ApprovalDirUnusable, validate_dir

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file where a directory is needed")
    with pytest.raises(ApprovalDirUnusable):
        validate_dir(blocker / "requests")


def test_validate_dir_creates_the_contract_subdirs(tmp_path):
    from belay.approval.channel import validate_dir

    validate_dir(tmp_path)
    assert (tmp_path / "requests").is_dir()
    assert (tmp_path / "decisions").is_dir()


# --- Phase 2: the bounded poll loop, fail-closed deadline --------------------


class FakeClock:
    """An injected monotonic clock: each call yields the next scripted reading."""

    def __init__(self, readings):
        self._readings = list(readings)
        self.calls = 0

    def __call__(self) -> float:
        assert self._readings, "the fake clock ran out of scripted readings"
        self.calls += 1
        return self._readings.pop(0)


def poll(hold, reads, clock):
    """Drive await_decision with a scripted reader and clock; record sleeps."""
    from belay.approval.channel import await_decision

    sleeps = []

    def read(hold_id):
        return reads.pop(0) if reads else None

    return await_decision(
        hold, read=read, poll_interval=0.0, clock=clock, sleep=sleeps.append
    ), sleeps, clock.calls


def test_decision_present_on_first_poll_wins_without_consulting_the_clock():

    h = hold()
    decision, sleeps, clock_calls = poll(
        h, [{"decision": "approve", "reason": "ok"}], FakeClock([0.0])
    )
    assert decision == {"decision": "approve", "reason": "ok"}
    # The pinned ordering: the decision is read FIRST, so a decision on disk
    # never even consults the deadline — the poll's granularity cannot cost it.
    assert clock_calls == 0
    assert sleeps == []


def test_no_decision_denies_at_the_deadline_under_the_injected_clock():
    h = hold(deadline=100.0)
    decision, sleeps, clock_calls = poll(h, [None, None], FakeClock([0.0, 100.0]))
    assert decision is None  # the caller denies APPROVAL_TIMEOUT, fail-closed
    assert clock_calls == 2
    # After the deny the loop exited: a file written now would never be read —
    # the M14 boundary is structural, not a post-hoc check.
    assert len(sleeps) == 1


def test_a_decision_arriving_mid_poll_is_found():
    h = hold(deadline=100.0)
    decision, sleeps, clock_calls = poll(
        h, [None, {"decision": "deny"}], FakeClock([0.0, 50.0])
    )
    assert decision == {"decision": "deny"}
    assert clock_calls == 1  # only the first tick checked the deadline


def test_a_reason_string_is_carried_into_the_resolution():
    h = hold()
    decision, _, _ = poll(h, [{"decision": "deny", "reason": "not now"}], FakeClock([]))
    assert decision == {"decision": "deny", "reason": "not now"}


def test_the_ordering_is_pinned_decision_before_deadline():
    """M14's boundary is the poll's decision check, not the clock's exactness.

    The decision file was written before the deadline; the first tick that reads
    it would have clocked PAST the deadline. The decision still wins — the
    deadline check runs only when no decision was found.
    """
    h = hold(deadline=100.0)
    decision, _, clock_calls = poll(
        h, [None, {"decision": "approve"}], FakeClock([0.0, 120.0])
    )
    assert decision == {"decision": "approve"}
    # The second tick never consulted the clock: the decision won first.
    assert clock_calls == 1


def test_the_loop_never_sleeps_longer_than_min_interval_remaining():
    from belay.approval.channel import await_decision

    h = hold(deadline=5.0)
    sleeps = []

    def read(hold_id):
        return None

    clock = FakeClock([0.0, 100.0])
    result = await_decision(
        h, read=read, poll_interval=10.0, clock=clock, sleep=sleeps.append
    )
    assert result is None
    assert sleeps == [5.0]  # min(10, 5) — never past the remaining time


# --- Phase 3: the named JSON-RPC refusal -------------------------------------


def refusal_of(hold_obj, cause="DENIED"):
    from belay.approval.channel import refusal_bytes

    raw = refusal_bytes(hold_obj, cause)
    assert raw.endswith(b"\n"), "the refusal must be newline-terminated"
    return json.loads(raw)


def test_the_refusal_is_a_jsonrpc_2_0_error_with_the_requests_own_id():
    message = refusal_of(hold(request_id=9))
    assert message["jsonrpc"] == "2.0"
    assert message["id"] == 9
    assert message["error"]["code"] == -32000


def test_a_string_request_id_round_trips():
    assert refusal_of(hold(request_id="call-42"))["id"] == "call-42"


def test_a_null_request_id_round_trips():
    assert refusal_of(hold(request_id=None))["id"] is None


def test_the_message_names_the_gate_and_the_tool():
    message = refusal_of(hold(tool="blast"))
    text = message["error"]["message"]
    assert "approval gate" in text
    assert "blast" in text


def test_the_data_names_hold_decision_and_cause():
    message = refusal_of(hold(hold_id="0-blast"), cause="APPROVAL_TIMEOUT")
    approval = message["error"]["data"]["belay"]["approval"]
    assert approval["hold_id"] == "0-blast"
    assert approval["decision"] == "deny"
    assert approval["cause"] == "APPROVAL_TIMEOUT"


# --- Phase 4: the live annotation cache from the wire ------------------------


def tools_list_request(id_=2):
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/list"}


def tools_list_response(id_=2, tools=None):
    return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools or []}}


def tool(name, annotations=None):
    return {"name": name, "inputSchema": {"type": "object", "properties": {}}, **(
        {"annotations": annotations} if annotations is not None else {}
    )}


def cache():
    from belay.approval.channel import ToolFacts

    return ToolFacts(track_max=2)


def test_c2s_tracking_is_a_bounded_fifo_that_drops_the_oldest():
    facts = cache()
    facts.observe_c2s(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())
    facts.observe_c2s(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}).encode())
    facts.observe_c2s(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}).encode())
    # The cap is 2: id 1 was evicted, so its tools/list response updates nothing.
    facts.observe_s2c(json.dumps(tools_list_response(id_=1, tools=[tool("blast", {"destructiveHint": True})])).encode())
    assert facts.facts_for("blast") == {}
    facts.observe_s2c(json.dumps(tools_list_response(id_=3, tools=[tool("blast", {"destructiveHint": True})])).encode())
    assert facts.facts_for("blast")["destructiveHint"]["state"] == "declared-true"


def test_a_tracked_tools_list_response_populates_facts_in_the_annotations_shape():
    from belay.annotations import _tool_facts

    facts = cache()
    declared = {"destructiveHint": True, "readOnlyHint": False}
    facts.observe_c2s(json.dumps(tools_list_request()).encode())
    facts.observe_s2c(json.dumps(tools_list_response(tools=[tool("blast", declared)])).encode())

    # The STORED record is exactly the annotations.py:60-81 shape — pinned
    # against the derivation's own builder so aspect 4's reader and aspect 5's
    # report can consume the same vocabulary.
    stored = facts._facts["blast"]
    assert stored == _tool_facts(tool("blast", declared))
    assert stored["name"] == "blast"
    assert stored["annotations_object"] == "present"
    assert stored["incoherence"] == []
    # The gate consumes the `{annotation: {"state": ...}}` mapping slice.
    live = facts.facts_for("blast")
    assert live == _tool_facts(tool("blast", declared))["annotations"]
    assert live["destructiveHint"] == {"state": "declared-true"}
    assert live["readOnlyHint"] == {"state": "declared-false"}
    assert live["openWorldHint"] == {"state": "not-declared"}


def test_a_response_to_a_non_tools_list_request_never_updates_facts():
    facts = cache()
    facts.observe_c2s(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}).encode())
    facts.observe_s2c(
        json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"serverInfo": {"name": "x"}}}).encode()
    )
    assert facts.facts_for("anything") == {}


def test_an_untracked_id_never_updates_facts():
    facts = cache()
    facts.observe_s2c(json.dumps(tools_list_response(id_=99, tools=[tool("blast")])).encode())
    assert facts.facts_for("blast") == {}


def test_list_changed_clears_and_the_next_snapshot_repopulates():
    facts = cache()
    facts.observe_c2s(json.dumps(tools_list_request(id_=2)).encode())
    facts.observe_s2c(json.dumps(tools_list_response(id_=2, tools=[tool("blast", {"destructiveHint": True})])).encode())
    assert facts.facts_for("blast") != {}
    facts.observe_s2c(json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}).encode())
    assert facts.facts_for("blast") == {}
    facts.observe_c2s(json.dumps(tools_list_request(id_=5)).encode())
    facts.observe_s2c(json.dumps(tools_list_response(id_=5, tools=[tool("blast", {"destructiveHint": False})])).encode())
    assert facts.facts_for("blast")["destructiveHint"]["state"] == "declared-false"


def test_absent_and_literal_null_annotations_are_never_confused():
    facts = cache()
    facts.observe_c2s(json.dumps(tools_list_request(id_=1)).encode())
    facts.observe_s2c(
        json.dumps(
            tools_list_response(
                id_=1,
                tools=[
                    tool("plain"),  # no annotations object at all
                    tool("nulled", {"readOnlyHint": None}),  # a real null
                ],
            )
        ).encode()
    )
    # Absent: not-declared, and the object's absence is recorded separately.
    plain = facts._facts["plain"]
    assert plain["annotations_object"] == "absent"
    assert plain["annotations"]["destructiveHint"] == {"state": "not-declared"}
    # Literal null IS a declaration — a value the wire really sent — and it is
    # not a boolean, so it is declared-non-boolean, never not-declared.
    nulled = facts._facts["nulled"]
    assert nulled["annotations_object"] == "present"
    assert nulled["annotations"]["readOnlyHint"]["state"] == "declared-non-boolean"
    assert nulled["annotations"]["readOnlyHint"]["declared_value"] is None


# --- Phase 5: the hook surface ------------------------------------------------


class ScriptedClock:
    """Scripted readings; the readings must cover every call the gate makes."""

    def __init__(self, readings):
        self._readings = list(readings)
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        assert self._readings, f"scripted clock ran out after {self.calls} calls"
        return self._readings.pop(0)


class ParkClock:
    """A scripted clock that parks deterministically: the SECOND reading (the
    poll's first deadline check) sets `ready` and blocks until `release`, so a
    test can drive `close_all` while a hold is provably mid-poll. Later readings
    are free-running."""

    def __init__(self):
        self.ready = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        if self.calls == 1:
            return 0.0  # register
        if self.calls == 2:
            self.ready.set()
            self.release.wait(timeout=5)
            return 1000.0  # the poll's first deadline check, unparked
        return 5.0  # close_all, and any later resolution


def gate(tmp_path, clock, timeout=300.0, record=None, deliver=None, sleep=None):
    """An ApprovalGate over `tmp_path` with fake record/deliver and a shared
    event log, so call-sequence assertions (M7) can pin record-before-refusal."""
    from belay.approval.channel import ApprovalGate

    events = []

    def recorder(kind, **fields):
        events.append(("record", kind, fields))

    def deliverer(refusal):
        events.append(("deliver", refusal))

    g = ApprovalGate(
        tmp_path,
        timeout=timeout,
        poll_interval=0.0,
        clock=clock,
        sleep=sleep if sleep is not None else (lambda _s: None),
        record=record or recorder,
        deliver=deliver or deliverer,
    )
    return g, events


def seed_facts(g):
    """The wire's normal path: a tools/list round trip declaring blast as
    destructive — the facts `decide_c2s` reads at hold time."""
    g.decide_c2s(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode())
    g.observe_s2c(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {
                            "name": "blast",
                            "inputSchema": {"type": "object", "properties": {}},
                            "annotations": {"destructiveHint": True},
                        }
                    ]
                },
            }
        ).encode()
    )


def call_frame(name="blast", id_=7):
    return json.dumps(
        {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": name, "arguments": {}}, "id": id_}
    ).encode()


def decisions(gate_dir):
    return [
        e for e in gate_dir if e[0] == "record" and e[1] == "approval_decision"
    ]


def test_an_approved_call_forwards_with_hold_and_decision_records(tmp_path):
    clock = ScriptedClock([0.0, 0.0])
    g, events = gate(tmp_path, clock)
    seed_facts(g)
    (tmp_path / "decisions" / "0-blast.json").write_text(
        json.dumps({"decision": "approve", "reason": "looks right"})
    )
    assert g.decide_c2s(call_frame()) is True

    body = json.loads((tmp_path / "requests" / "0-blast.json").read_text())
    assert body["tool"] == "blast"
    assert body["request_id"] == 7
    assert body["triggers"] == ["destructiveHint"]

    kinds = [e[1] for e in events if e[0] == "record"]
    assert kinds == ["approval_hold", "approval_decision"]
    hold_record = events[0][2]
    assert hold_record["hold_id"] == "0-blast"
    assert hold_record["triggers"] == ("destructiveHint",)
    decision_record = events[1][2]
    assert decision_record["cause"] == "APPROVED"
    assert decision_record["decision"] == "approve"
    assert decision_record["reason"] == "looks right"
    assert decision_record["waited"] == 0.0
    assert [e for e in events if e[0] == "deliver"] == []


def test_a_denied_call_is_suppressed_with_one_refusal_recorded_after_the_decision(tmp_path):
    clock = ScriptedClock([0.0, 0.0])
    g, events = gate(tmp_path, clock)
    seed_facts(g)
    (tmp_path / "decisions" / "0-blast.json").write_text(
        json.dumps({"decision": "deny", "reason": "not now"})
    )
    assert g.decide_c2s(call_frame()) is False

    delivers = [e for e in events if e[0] == "deliver"]
    assert len(delivers) == 1, f"exactly one refusal, got {len(delivers)}"
    refusal = json.loads(delivers[0][1])
    assert refusal["id"] == 7
    assert refusal["error"]["data"]["belay"]["approval"]["cause"] == "DENIED"

    # M7: the decision is recorded BEFORE the refusal is delivered.
    decision_index = next(
        i for i, e in enumerate(events) if e[0] == "record" and e[1] == "approval_decision"
    )
    deliver_index = next(i for i, e in enumerate(events) if e[0] == "deliver")
    assert decision_index < deliver_index
    assert events[decision_index][2]["cause"] == "DENIED"
    assert events[decision_index][2]["decision"] == "deny"
    assert events[decision_index][2]["reason"] == "not now"


def test_everything_that_is_not_a_triggered_call_forwards_untouched(tmp_path):
    g, events = gate(tmp_path, ScriptedClock([]))
    frames = [
        b"not json at all",
        b"[1, 2]",  # a batch: never held
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": None}).encode(),
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "safe"}}).encode(),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}).encode(),
    ]
    for frame in frames:
        assert g.decide_c2s(frame) is True
    assert events == []
    assert list((tmp_path / "requests").iterdir()) == []


def test_no_decision_denies_fail_closed_with_APPROVAL_TIMEOUT(tmp_path):
    clock = ScriptedClock([0.0, 100.0, 100.0])
    g, events = gate(tmp_path, clock, timeout=100.0)
    seed_facts(g)
    assert g.decide_c2s(call_frame()) is False

    delivers = [e for e in events if e[0] == "deliver"]
    assert len(delivers) == 1
    assert json.loads(delivers[0][1])["error"]["data"]["belay"]["approval"]["cause"] == "APPROVAL_TIMEOUT"
    decision_record = decisions(events)[0][2]
    assert decision_record["cause"] == "APPROVAL_TIMEOUT"
    assert decision_record["decision"] is None
    assert decision_record["waited"] == 100.0


def test_close_all_resolves_pending_holds_and_the_gate_stays_alive(tmp_path):
    clock = ParkClock()
    g, events = gate(tmp_path, clock, timeout=100.0)
    seed_facts(g)

    outcome = {}
    parked = threading.Thread(target=lambda: outcome.setdefault("v", g.decide_c2s(call_frame())))
    parked.start()
    assert clock.ready.wait(timeout=5), "the poll never parked on its first deadline check"

    g.close_all()
    clock.release.set()
    parked.join(timeout=5)
    assert not parked.is_alive()
    assert outcome["v"] is False

    # One shutdown decision, recorded before its refusal (M7), and one refusal.
    decided = decisions(events)
    assert len(decided) == 1, f"exactly one decision, got {decided!r}"
    assert decided[0][2]["cause"] == "APPROVAL_SHUTDOWN"
    assert decided[0][2]["decision"] is None
    delivers = [e for e in events if e[0] == "deliver"]
    assert len(delivers) == 1
    assert json.loads(delivers[0][1])["error"]["data"]["belay"]["approval"]["cause"] == "APPROVAL_SHUTDOWN"
    assert next(i for i, e in enumerate(events) if e[0] == "record") < next(
        i for i, e in enumerate(events) if e[0] == "deliver"
    )

    # The gate is sticky-but-alive: a NEW triggered call still resolves normally.
    (tmp_path / "decisions" / "1-blast.json").write_text(json.dumps({"decision": "approve"}))
    assert g.decide_c2s(call_frame()) is True


def test_the_holds_facts_are_fixed_at_hold_time(tmp_path):
    ready = threading.Event()
    release = threading.Event()
    clock = ScriptedClock([0.0, 0.0, 0.0])  # register, the parked tick, the resolution

    def blocking_sleep(_seconds):
        ready.set()
        release.wait(timeout=5)

    g, events = gate(tmp_path, clock, sleep=blocking_sleep)
    seed_facts(g)

    # Park the poll on its sleep, clear the cache mid-hold, then release: the
    # hold's triggers were fixed when the call arrived, so the cache clearing
    # cannot retroactively change what this hold is for.
    outcome = {}
    parked = threading.Thread(target=lambda: outcome.setdefault("v", g.decide_c2s(call_frame())))
    parked.start()
    assert ready.wait(timeout=5), "the poll never parked on its sleep"
    g.observe_s2c(json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}).encode())
    assert g._cache.facts_for("blast") == {}
    (tmp_path / "decisions" / "0-blast.json").write_text(json.dumps({"decision": "approve"}))
    release.set()
    parked.join(timeout=5)
    assert outcome["v"] is True

    hold_record = events[0][2]
    assert hold_record["triggers"] == ("destructiveHint",)
    assert json.loads((tmp_path / "requests" / "0-blast.json").read_text())["triggers"] == ["destructiveHint"]


def test_an_internal_fault_suppresses_refuses_and_records_APPROVAL_FAULT(tmp_path):
    clock = ScriptedClock([0.0, 0.0])
    g, events = gate(tmp_path, clock)
    seed_facts(g)
    # The requests dir becomes a file between startup and the call: the request
    # write fails, and the gate must refuse loudly rather than raise or forward.
    (tmp_path / "requests").rmdir()
    (tmp_path / "requests").write_text("a file where the requests dir was")

    assert g.decide_c2s(call_frame()) is False  # totality: never raises

    decided = decisions(events)
    assert len(decided) == 1
    assert decided[0][2]["cause"] == "APPROVAL_FAULT"
    assert decided[0][2]["decision"] is None
    delivers = [e for e in events if e[0] == "deliver"]
    assert len(delivers) == 1
    refusal = json.loads(delivers[0][1])
    assert refusal["id"] == 7
    assert refusal["error"]["data"]["belay"]["approval"]["cause"] == "APPROVAL_FAULT"


def test_a_faulting_recorder_still_suppresses_and_refuses(tmp_path):
    def bad_record(kind, **fields):
        raise RuntimeError("recorder down")

    g, events = gate(tmp_path, ScriptedClock([0.0, 0.0]), record=bad_record)
    seed_facts(g)
    (tmp_path / "decisions" / "0-blast.json").write_text(json.dumps({"decision": "deny"}))

    assert g.decide_c2s(call_frame()) is False
    # The refusal is best-effort and independent of the recorder: it still lands.
    delivers = [e for e in events if e[0] == "deliver"]
    assert len(delivers) == 1
    assert json.loads(delivers[0][1])["id"] == 7