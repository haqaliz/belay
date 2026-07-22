"""RED-first tests for `eval.minting_driver.checkpoint` — the resume ledger (Phase 2).

A mint over ≥50 instances is a long, interruptible run; a crash must not restart from
zero. The checkpoint is a small JSON ledger of per-instance disposition, loaded
fail-closed (mirroring `belay.phase0.ledger`) so a corrupt ledger can never be read as
"nothing done yet", and saved atomically (temp file + `os.replace`) so a crash mid-save
cannot corrupt an existing ledger.

Two cases are deliberately distinguished: a NON-EXISTENT path loads as an EMPTY
checkpoint (the first-run case), while a PRESENT-but-corrupt file raises a named
`ValueError` (a ledger that would misreport progress must never be silently discarded).

Fully deterministic, offline, CI-safe: only `tmp_path`, no model, no git, no network.
"""

from __future__ import annotations

import json

import pytest

from eval.minting_driver.checkpoint import load_checkpoint


def test_checkpoint_round_trips(tmp_path):
    path = tmp_path / "checkpoint.json"
    cp = load_checkpoint(path)
    cp.record("inst-a", "captured", trace_path="/batch/trace-inst-a.jsonl")
    cp.record("inst-b", "failed", reason="no trace produced")
    cp.save(path)

    reloaded = load_checkpoint(path)
    assert reloaded.is_done("inst-a")
    assert reloaded.is_done("inst-b")
    assert reloaded.status("inst-a") == "captured"
    assert reloaded.status("inst-b") == "failed"
    assert reloaded.reason("inst-b") == "no trace produced"
    assert reloaded.trace_path("inst-a") == "/batch/trace-inst-a.jsonl"


def test_nonexistent_path_loads_as_empty_checkpoint(tmp_path):
    path = tmp_path / "does-not-exist.json"
    cp = load_checkpoint(path)
    assert not cp.is_done("anything")
    # An empty checkpoint saves cleanly and reloads to an equally-empty one.
    cp.save(path)
    assert not load_checkpoint(path).is_done("anything")


def test_recording_is_atomic_across_a_simulated_crash(tmp_path):
    """A save that fails during serialization must leave the pre-existing ledger intact.

    Atomicity is the temp-file-then-`os.replace` discipline: the durable file is only
    ever swapped in whole. We simulate a crash by recording an UN-serializable value and
    asserting (a) `save` raises, (b) the original file is byte-for-byte unchanged, and
    (c) no leftover temp file is stranded in the directory.
    """
    path = tmp_path / "checkpoint.json"
    good = load_checkpoint(path)
    good.record("inst-a", "captured", trace_path="/batch/trace-inst-a.jsonl")
    good.save(path)
    before = path.read_bytes()

    # A value json cannot serialize forces the write to blow up mid-save.
    poisoned = load_checkpoint(path)
    poisoned.record("inst-b", "captured", trace_path=object())  # not JSON-serializable
    with pytest.raises((TypeError, ValueError)):
        poisoned.save(path)

    # The original ledger survived untouched, and no temp file was left behind.
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_is_done_is_true_for_captured_and_failed(tmp_path):
    cp = load_checkpoint(tmp_path / "cp.json")
    cp.record("cap", "captured")
    cp.record("fail", "failed", reason="boom")
    assert cp.is_done("cap")
    assert cp.is_done("fail")


def test_is_done_is_false_for_unknown_instance(tmp_path):
    cp = load_checkpoint(tmp_path / "cp.json")
    cp.record("cap", "captured")
    assert not cp.is_done("never-seen")


def test_corrupt_checkpoint_is_a_named_error(tmp_path):
    # Invalid JSON.
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_checkpoint(bad_json)

    # Valid JSON, wrong top-level shape (a list, not an object).
    wrong_shape = tmp_path / "list.json"
    wrong_shape.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_checkpoint(wrong_shape)

    # An entry that is not an object.
    bad_entry = tmp_path / "bad-entry.json"
    bad_entry.write_text(json.dumps({"inst": "captured"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_checkpoint(bad_entry)

    # An entry missing its required `status` field.
    missing_status = tmp_path / "missing.json"
    missing_status.write_text(
        json.dumps({"inst": {"reason": None, "trace_path": None}}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_checkpoint(missing_status)

    # An entry with an unknown status.
    bad_status = tmp_path / "bad-status.json"
    bad_status.write_text(
        json.dumps({"inst": {"status": "half-done"}}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_checkpoint(bad_status)
