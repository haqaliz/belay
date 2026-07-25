"""Every UNVERIFIED turn names its cause — including the ones that REPLAYED fine.

The Phase-0 gate's contract (ROADMAP.md:112) is *"every UNVERIFIED must trace to a named
cause."* Half of it was already true: a turn that never replayed early-returns through
`turn._unverifiable_verdict`, which buckets the engine's verbatim cause through
`canonical_cause`. The other half was silently broken — a turn that replayed *fine* and
only then reduced to UNVERIFIED (an un-annotated tool, an unrestorable sub-dimension, an
A1 invariant that could not be evaluated) returned `cause=None` unconditionally, so
`phase0/runner.py` filed it under the causeless catch-all `"unknown"`. The Stage-1
re-mint published `unknown: 12` — a gate blocker, since "unknown" names nothing.

Two halves are needed and either alone is worthless:

- a cause on the REPLAYED path, derived from the **deciding** sub-verdict (the one whose
  status drove the reduction) rather than an arbitrary one; and
- a **stable label** for it, so the breakdown buckets by dimension. Without the label,
  `canonical_cause` falls through to `return cause` and every turn gets its own bucket
  keyed by a long verbatim message — no more useful than `unknown`, just noisier.

Deterministic and offline: `replay_turn` is stubbed exactly as `test_verify_turn.py`
stubs it, so what is under test is the composition, never re-execution.
"""

from __future__ import annotations

import json

from conftest import trace_of
from fixtures.annotation_frames import TOOLS_LIST_REQUEST, TOOLS_LIST_RESPONSE

from belay.phase0.runner import _UNKNOWN_CAUSE, run_batch
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.replay.report import canonical_cause
from belay.snapshot.bth1 import FieldDiff
from belay.trace import TraceWriter
from belay.verify import turn as turn_module
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status, Verdict

LISTING = [("c2s", TOOLS_LIST_REQUEST), ("s2c", TOOLS_LIST_RESPONSE)]
UNUSED = ["unused-server"]
CAPTURED_AT = "2026-07-23T00:00:00+00:00"


def _call(msg_id: int, name: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    ).encode()


def _reply(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _mutation(*paths: str) -> list[FieldDiff]:
    return [FieldDiff(path=p.encode(), field=None, left=None, right=b"content") for p in paths]


def _stub_replay(monkeypatch, reply: TurnReplay) -> None:
    monkeypatch.setattr(turn_module, "replay_turn", lambda *a, **k: reply)


def _replayed(delta) -> TurnReplay:
    """A cleanly REPLAYED turn whose reply reproduced — only the delta varies."""
    return TurnReplay(
        turn_index=0,
        status=REPLAYED,
        reinvoked=True,
        result_equivalence=EQUAL,
        recorded_reply=_reply(3, "ok"),
        replayed_reply=_reply(3, "ok"),
        delta=delta,
    )


def _run(records, monkeypatch) -> TurnVerdict:
    return verify_turn(records, 0, server_command=UNUSED, manifest_dir="/nonexistent")


# --- 1. The fix: a replayed-but-UNVERIFIED turn names a cause -------------------------


def test_replayed_unverified_turn_names_its_cause(tmp_path, monkeypatch) -> None:
    """An un-annotated tool replays fine, effect is UNVERIFIED (no contract) -> the turn
    is UNVERIFIED and MUST carry a named cause. `None` here is what became `unknown: 12`."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "mystery"))])
    _stub_replay(monkeypatch, _replayed(_mutation("x")))

    verdict = _run(records, monkeypatch)

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.cause is not None, (
        "a replayed turn that reduced to UNVERIFIED carries no cause, so the Phase-0 "
        "report can only file it under the causeless catch-all"
    )
    assert verdict.cause != _UNKNOWN_CAUSE, verdict.cause
    assert verdict.cause.strip() != "", verdict.cause


def test_the_replayed_cause_names_the_deciding_dimension(tmp_path, monkeypatch) -> None:
    """The cause is derived from the sub-verdict that DROVE the reduction, not an
    arbitrary one: an effect-driven UNVERIFIED and a result-driven UNVERIFIED must not
    collapse into the same bucket."""
    records = trace_of(tmp_path / "a", LISTING + [("c2s", _call(3, "mystery"))])
    _stub_replay(monkeypatch, _replayed(_mutation("x")))
    effect_driven = _run(records, monkeypatch)

    # A reply that could not be compared at all: the RESULT sub-verdict is the UNVERIFIED
    # one, while the tool is declared-false so the effect dimension is a clean PASS.
    records = trace_of(tmp_path / "b", LISTING + [("c2s", _call(3, "write_file"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=None,
            recorded_reply=None,
            replayed_reply=None,
            delta=[],
        ),
    )
    result_driven = _run(records, monkeypatch)

    assert effect_driven.status is Status.UNVERIFIED, effect_driven
    assert result_driven.status is Status.UNVERIFIED, result_driven
    assert effect_driven.cause != result_driven.cause, (
        "the two dimensions share one bucket, so the breakdown cannot say WHICH check "
        "could not speak", effect_driven.cause,
    )


def test_replayed_causes_bucket_by_dimension_not_one_bucket_per_turn(
    tmp_path, monkeypatch
) -> None:
    """Two turns unverified for the same reason but with different verbatim detail (a
    different observed delta, a different tool) file under the SAME bucket.

    This is the half that the `_PREFIX_LABELS` entry buys. A cause that carries per-turn
    detail and is not labelled falls through `canonical_cause` verbatim, and a breakdown
    with one bucket per turn explains no more than `unknown` did.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "mystery"))])
    _stub_replay(monkeypatch, _replayed(_mutation("a/one.txt")))
    first = _run(records, monkeypatch)

    _stub_replay(monkeypatch, _replayed(_mutation("b/two.txt", "c/three.txt")))
    second = _run(records, monkeypatch)

    assert first.status is second.status is Status.UNVERIFIED
    assert first.cause == second.cause, (first.cause, second.cause)


def test_the_replayed_cause_is_a_canonical_bucket(tmp_path, monkeypatch) -> None:
    """`TurnVerdict.cause` is the canonical bucket on BOTH paths, so a consumer never has
    to know which path produced it, and re-bucketing is a no-op."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "mystery"))])
    _stub_replay(monkeypatch, _replayed(_mutation("x")))

    verdict = _run(records, monkeypatch)

    assert canonical_cause(verdict.cause) == verdict.cause, verdict.cause
    # And it is not the raw sub-verdict message leaking through as its own bucket.
    messages = {v.message for v in verdict.sub_verdicts}
    assert verdict.cause not in messages, verdict.cause
    assert len(verdict.cause) < 80, ("the bucket is a label, not a sentence", verdict.cause)


# --- 2. No regression: a decided turn still carries no cause --------------------------


def test_a_replayed_pass_turn_still_carries_no_cause(tmp_path, monkeypatch) -> None:
    """`cause` explains an UNVERIFIED. A PASS has nothing to explain and must stay `None`
    — a cause on a passing turn would be tallied by any consumer that reads the field."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])
    _stub_replay(monkeypatch, _replayed([]))

    verdict = _run(records, monkeypatch)

    assert verdict.status is Status.PASS, verdict
    assert verdict.cause is None, verdict


def test_a_replayed_fail_turn_still_carries_no_cause(tmp_path, monkeypatch) -> None:
    """Same for a FAIL: the sub-verdicts say why it failed; `cause` is the UNVERIFIED field."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])
    _stub_replay(monkeypatch, _replayed(_mutation("mutated.txt")))

    verdict = _run(records, monkeypatch)

    assert verdict.status is Status.FAIL, verdict
    assert verdict.cause is None, verdict


# --- 3. The runner publishes buckets through `canonical_cause` ------------------------


def _write_trace(trace_dir, tool: str, n_calls: int):
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for i in range(n_calls):
            call_id = 10 + i
            writer.observer("c2s")(_call(call_id, tool), False)
            writer.observer("s2c")(_reply(call_id, "ok"), False)
    finally:
        writer.close()
    return writer.path


def test_phase0_buckets_unverified_causes_through_canonical_cause(tmp_path) -> None:
    """`phase0/runner` must bucket by the CANONICAL name, as the spec says it does.

    It never called `canonical_cause` at all — it copied `TurnVerdict.cause` straight into
    the tally — so any consumer handing it a verbatim engine string (the corpus rig does,
    and a fake verifier certainly can) produced a per-turn bucket in the published table.
    """
    trace_dir = tmp_path / "traces"
    raw = "no persisted snapshot manifest for handle 0123abcd (dir /nope)"
    _write_trace(trace_dir, "mystery", 1)

    def verifier(records, n, **kwargs) -> TurnVerdict:
        return TurnVerdict(
            turn_index=n,
            tool_name="mystery",
            status=Status.UNVERIFIED,
            sub_verdicts=[Verdict("A2", "replay", Status.UNVERIFIED, None, None, raw)],
            cause=raw,
        )

    ledger = run_batch(
        trace_dir,
        corpus_dir=tmp_path / "corpus",
        server_command=UNUSED,
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=verifier,
        ingester=lambda corpus_dir, **kw: tmp_path / "unused",
    )

    buckets = ledger.unverified_by_cause()
    assert _UNKNOWN_CAUSE not in buckets, buckets
    assert raw not in buckets, ("the verbatim engine string became its own bucket", buckets)
    assert buckets.get(canonical_cause(raw)) == 1, buckets
