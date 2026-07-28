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


# --------------------------------------------------------------------------------------
# `no_observation` + history (quota-circuit-breaker, Phase 3)
#
# A quota/period cap produces NO observation: the instance was never actually driven, so
# recording it `failed` — which `is_done` treats as done, permanently — is what stranded 56
# instances on 2026-07-24. The ledger gains a third disposition that a resume RE-ARMS, and
# an append-only `history` so the re-arm never erases the record of what already ran.
# --------------------------------------------------------------------------------------


def test_no_observation_round_trips(tmp_path):
    path = tmp_path / "checkpoint.json"
    cp = load_checkpoint(path)
    cp.record("inst-q", "no_observation", reason="429 RESOURCE_EXHAUSTED")
    cp.save(path)

    reloaded = load_checkpoint(path)
    assert reloaded.status("inst-q") == "no_observation"
    assert reloaded.reason("inst-q") == "429 RESOURCE_EXHAUSTED"


def test_is_done_is_false_for_no_observation(tmp_path):
    """The re-arm rule, in one assertion: a no-observation instance is NOT done.

    This is the whole mechanism — there is deliberately no flag and no `--force`. An
    instance that produced an observation (`captured` or `failed`) stays done forever;
    only one that produced none becomes eligible again.
    """
    cp = load_checkpoint(tmp_path / "cp.json")
    cp.record("cap", "captured")
    cp.record("fail", "failed", reason="boom")
    cp.record("quota", "no_observation", reason="quota exhausted")
    assert cp.is_done("cap")
    assert cp.is_done("fail")
    assert not cp.is_done("quota")


def test_re_recording_appends_the_prior_disposition_to_history(tmp_path):
    cp = load_checkpoint(tmp_path / "cp.json")
    cp.record("inst", "no_observation", reason="quota exhausted")
    cp.record("inst", "captured", trace_path="/batch/trace-inst.jsonl")

    assert cp.status("inst") == "captured"
    assert cp.history("inst") == [
        {"status": "no_observation", "reason": "quota exhausted"}
    ]


def test_history_survives_a_save_load_round_trip(tmp_path):
    """The `_validate_entry` drop-unknown-keys trap.

    The loader rebuilds each entry from a fixed set of keys, so a `history` it does not
    name is silently dropped on every load — which would make the append-only guarantee
    hold only in memory, exactly the failure this history exists to prevent.
    """
    path = tmp_path / "checkpoint.json"
    cp = load_checkpoint(path)
    cp.record("inst", "no_observation", reason="quota exhausted")
    cp.record("inst", "captured", trace_path="/batch/trace-inst.jsonl")
    cp.save(path)

    reloaded = load_checkpoint(path)
    assert reloaded.history("inst") == [
        {"status": "no_observation", "reason": "quota exhausted"}
    ]


def test_two_re_records_build_a_two_entry_history_in_order(tmp_path):
    cp = load_checkpoint(tmp_path / "cp.json")
    cp.record("inst", "no_observation", reason="first stop")
    cp.record("inst", "no_observation", reason="second stop")
    cp.record("inst", "captured", trace_path="/batch/trace-inst.jsonl")

    assert cp.history("inst") == [
        {"status": "no_observation", "reason": "first stop"},
        {"status": "no_observation", "reason": "second stop"},
    ]


def test_history_is_empty_for_a_first_record_and_an_unknown_instance(tmp_path):
    cp = load_checkpoint(tmp_path / "cp.json")
    cp.record("inst", "captured")
    assert cp.history("inst") == []
    assert cp.history("never-seen") == []


def test_a_legacy_checkpoint_without_history_still_loads(tmp_path):
    """Backward compatibility: the real Stage-3 ledger's shape, which has no `history`.

    68 entries were written before this vocabulary existed, in exactly the
    `{status, reason, trace_path}` shape below. They must load, not raise, and read as
    having no history rather than as having lost one.
    """
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "django__django-11039": {
                    "status": "captured",
                    "reason": None,
                    "trace_path": "/mint/s3/trace-django__django-11039.jsonl",
                },
                "sympy__sympy-24152": {
                    "status": "failed",
                    "reason": "429 RESOURCE_EXHAUSTED",
                    "trace_path": None,
                },
            }
        ),
        encoding="utf-8",
    )

    cp = load_checkpoint(path)
    assert cp.status("django__django-11039") == "captured"
    assert cp.status("sympy__sympy-24152") == "failed"
    assert cp.history("django__django-11039") == []
    assert cp.history("sympy__sympy-24152") == []


def test_instance_ids_enumerates_every_recorded_instance_in_insertion_order(tmp_path):
    """An auditor can enumerate the ledger without reaching into `_entries`.

    `eval/scripts/rearm_checkpoint.py` has to walk every entry to find the quota
    failures. The alternative — re-reading the JSON alongside `load_checkpoint` — would
    duplicate the parse and quietly bypass the fail-closed load, which is the one
    property the ledger cannot afford to have two versions of.
    """
    path = tmp_path / "cp.json"
    cp = load_checkpoint(path)
    cp.record("inst-b", "captured")
    cp.record("inst-a", "failed", reason="boom")
    cp.record("inst-c", "no_observation", reason="quota")

    assert cp.instance_ids() == ("inst-b", "inst-a", "inst-c")

    # Survives the round trip (the loader sorts keys on save; what matters is that every
    # recorded instance is enumerable, not the order).
    cp.save(path)
    assert set(load_checkpoint(path).instance_ids()) == {"inst-a", "inst-b", "inst-c"}
    assert load_checkpoint(tmp_path / "absent.json").instance_ids() == ()


def test_record_with_an_invalid_status_still_raises_immediately(tmp_path):
    cp = load_checkpoint(tmp_path / "cp.json")
    with pytest.raises(ValueError):
        cp.record("inst", "no-observation")  # hyphen, not underscore
    assert cp.status("inst") is None


def test_a_malformed_history_is_a_named_load_error(tmp_path):
    """Fail-closed extends to the new field: a history that is not a list of objects raises.

    A ledger whose history cannot be read is a ledger whose re-arm record cannot be
    audited, and silently coercing it would hide exactly the loss D3 forbids.
    """
    not_a_list = tmp_path / "history-scalar.json"
    not_a_list.write_text(
        json.dumps({"inst": {"status": "captured", "history": "nope"}}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_checkpoint(not_a_list)

    not_objects = tmp_path / "history-items.json"
    not_objects.write_text(
        json.dumps({"inst": {"status": "captured", "history": ["nope"]}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_checkpoint(not_objects)


# --------------------------------------------------------------------------------------
# `accounting` (run-accounting, Phase 3)
#
# What a mint COSTS was recorded nowhere: `record` stored exactly
# `{status, reason, trace_path, history}`, so no stop-loss could be expressed and the
# write-up could not state the cost of the number. The entry gains one more optional
# field — `{wall_clock_seconds, model_requests, retry_count, input_tokens, output_tokens,
# model, provider}` — and `_validate_entry` has to NAME it, exactly as it had to name
# `history`, or the loader's fixed key set drops it silently on every load.
# --------------------------------------------------------------------------------------


def test_accounting_round_trips(tmp_path):
    path = tmp_path / "checkpoint.json"
    cp = load_checkpoint(path)
    cp.record(
        "inst-a",
        "captured",
        trace_path="/batch/trace-inst-a.jsonl",
        accounting={
            "wall_clock_seconds": 12.5,
            "model_requests": 4,
            "retry_count": 1,
            "input_tokens": 900,
            "output_tokens": 120,
            "model": "gemini-flash-latest",
            "provider": "openai-compat",
        },
    )
    cp.save(path)

    reloaded = load_checkpoint(path)
    assert reloaded.accounting("inst-a") == {
        "wall_clock_seconds": 12.5,
        "model_requests": 4,
        "retry_count": 1,
        "input_tokens": 900,
        "output_tokens": 120,
        "model": "gemini-flash-latest",
        "provider": "openai-compat",
    }


def test_accounting_is_none_when_unrecorded_and_for_an_unknown_instance(tmp_path):
    """Absent, not an empty dict: "this instance has no accounting" and "its accounting
    was all zeroes" are different facts and must stay so."""
    cp = load_checkpoint(tmp_path / "cp.json")
    cp.record("inst", "captured")
    assert cp.accounting("inst") is None
    assert cp.accounting("never-seen") is None


def test_absent_token_fields_are_omitted_not_nulled(tmp_path):
    """D3 at the ledger boundary: a provider that reported no usage leaves NO key.

    A `"input_tokens": 0` written for a provider that never reported usage would be a
    fabricated measurement, and any later total over the column would silently absorb it.
    """
    path = tmp_path / "cp.json"
    cp = load_checkpoint(path)
    cp.record(
        "inst",
        "captured",
        accounting={"wall_clock_seconds": 3.0, "model_requests": 2, "retry_count": 0},
    )
    cp.save(path)

    stored = json.loads(path.read_text(encoding="utf-8"))["inst"]["accounting"]
    assert "input_tokens" not in stored
    assert "output_tokens" not in stored
    assert stored == {"wall_clock_seconds": 3.0, "model_requests": 2, "retry_count": 0}


def test_a_legacy_entry_without_accounting_still_loads(tmp_path):
    """Backward compatibility, same shape the `history` change had to keep working."""
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "django__django-11039": {
                    "status": "captured",
                    "reason": None,
                    "trace_path": "/mint/s3/trace-django__django-11039.jsonl",
                }
            }
        ),
        encoding="utf-8",
    )

    cp = load_checkpoint(path)
    assert cp.status("django__django-11039") == "captured"
    assert cp.accounting("django__django-11039") is None


def test_a_malformed_accounting_is_a_named_load_error(tmp_path):
    """Fail-closed extends to the new field, as it did to `history`.

    An accounting that cannot be read is spend that cannot be audited, and coercing it
    would hide exactly the loss the field exists to prevent.
    """
    path = tmp_path / "bad-accounting.json"
    path.write_text(
        json.dumps({"inst": {"status": "captured", "accounting": "12 seconds"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_checkpoint(path)


def test_a_re_record_carries_the_prior_accounting_into_history(tmp_path):
    """A re-armed instance's earlier spend is superseded, never erased.

    The quota-stopped attempt really did consume requests; dropping its accounting on
    re-arm would under-report the cost of the number by exactly the attempts that failed.
    """
    path = tmp_path / "cp.json"
    cp = load_checkpoint(path)
    cp.record(
        "inst",
        "no_observation",
        reason="quota exhausted",
        accounting={"wall_clock_seconds": 2.0, "model_requests": 1, "retry_count": 0},
    )
    cp.record(
        "inst",
        "captured",
        trace_path="/batch/trace-inst.jsonl",
        accounting={"wall_clock_seconds": 40.0, "model_requests": 6, "retry_count": 0},
    )
    cp.save(path)

    reloaded = load_checkpoint(path)
    assert reloaded.history("inst") == [
        {
            "status": "no_observation",
            "reason": "quota exhausted",
            "accounting": {
                "wall_clock_seconds": 2.0,
                "model_requests": 1,
                "retry_count": 0,
            },
        }
    ]
    assert reloaded.accounting("inst") == {
        "wall_clock_seconds": 40.0,
        "model_requests": 6,
        "retry_count": 0,
    }


def test_a_history_entry_omits_accounting_entirely_when_there_was_none(tmp_path):
    """No `"accounting": null` noise on the ledger written by a pre-accounting record.

    Also what keeps every history assertion written before this aspect true, rather than
    quietly needing a third key added to each of them.
    """
    cp = load_checkpoint(tmp_path / "cp.json")
    cp.record("inst", "no_observation", reason="quota exhausted")
    cp.record("inst", "captured")

    assert cp.history("inst") == [{"status": "no_observation", "reason": "quota exhausted"}]


def test_no_currency_field_can_enter_the_ledger_unnoticed(tmp_path):
    """D4, pinned at the durable boundary: nothing money-shaped is written.

    Under a subscription there is no per-token price; a dollar figure would be fabricated
    precision. If a metered key is ever used, price is applied at REPORT time from a
    stated rate — never baked into the ledger.
    """
    path = tmp_path / "cp.json"
    cp = load_checkpoint(path)
    cp.record(
        "inst",
        "captured",
        accounting={
            "wall_clock_seconds": 3.0,
            "model_requests": 2,
            "retry_count": 0,
            "input_tokens": 10,
            "output_tokens": 5,
            "model": "gemini-flash-latest",
            "provider": "openai-compat",
        },
    )
    cp.save(path)

    text = path.read_text(encoding="utf-8")
    assert "$" not in text
    for word in ("cost", "price", "usd", "dollar"):
        assert word not in text.lower()
