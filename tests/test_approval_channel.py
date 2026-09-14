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
from pathlib import Path

import pytest

from belay.approval.gate import (
    APPROVAL_TIMEOUT,
    APPROVED,
    DECISION_APPROVE,
    DECISION_DENY,
    DENIED,
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