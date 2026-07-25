"""Phase 1 (RED) — the tests that should have existed for `replay-batch-server-rooting`.

`tests/test_replay_relocation_e2e.py` proved absolute-path relocation, but **every** case
in it builds the server command from the SAME root as the capture (`_server_cmd(root)`,
used at :312, :339, :369, :401, :488, :592). That symmetry is exactly what hid this defect:
`engine._relocation_decision` gates relocation on the RECORDED root and the turn's own
arguments, and never checks that the **server argv** is actually rooted under that root.
`client.replay_turn` then calls `remap_argv(argv, source_root, resolved)[0]` and DISCARDS
the `changed` flag, so a mis-rooted server is spawned anyway and rejects the scratch paths
as out-of-root, and the reply diverges from a recorded success.

## What the RED phase actually MEASURED (read this before Phase 2)

The aspect spec predicts the divergence then reduces `DIVERGED + DETERMINISTIC -> FAIL`.
**Against this fixture it does not** — and the reason is worth knowing. The fixture's
out-of-root refusal embeds the offending path, which is the per-replay `mkdtemp` scratch,
so `determinism._signature` (raw parsed reply; NO root canonicalization, unlike the
engine's recorded-vs-replayed comparison) sees three different replies and classifies the
turn `NONDETERMINISTIC`. The observed defect is therefore:

    UNVERIFIED, cause=None, "the tool 'edit_abs' is nondeterministic (axis: unknown)"

A **causeless** UNVERIFIED, misattributed to a tool that is perfectly deterministic, which
`phase0.runner` then buckets under `"unknown"` in the published UNVERIFIED-by-cause table.

That is not a milder bug — it is the same bug with a coin flip on top. Whether a mis-rooted
replay reads as UNVERIFIED or as a fabricated FAIL depends only on whether the server
happens to echo the scratch path in its refusal. Nothing guarantees the safe side, so the
spec's FAIL remains live for any server with a path-free refusal, and the gate that makes
this an abstention *by construction* is still what Phase 2 must add.

A rooting problem is an **evaluation failure, not a violation**. The honest verdict is
UNVERIFIED with a named cause, decided BEFORE any restore or spawn. In a heterogeneous
Phase-0 batch (one static `--server` over traces from many workspaces) the current
behavior would publish a ~100% violation rate made entirely of fabricated FAILs — which is
why this is the aspect that blocks live spend.

Every test below **breaks the `_server_cmd(root)` symmetry**: the capture root and the
server's argv root are deliberately different.

The helpers are imported from `test_replay_relocation_e2e` rather than re-derived, so the
two files cannot drift apart: if the gated-capture rig changes there, these tests move with
it. See that file's module docstring for why each helper is shaped the way it is.

Tests 3 and 4 are regression guards — they assert TODAY's behavior and are expected to
pass in the RED phase. Tests 1, 2, 5 and 6 are the RED.

## Phase 3 — tests 7 and 8 (the load-bearing criteria)

Tests 1–6 buy the honesty floor: a replay that cannot be correctly rooted abstains instead
of fabricating a FAIL. That is honest but USELESS for the mint — a heterogeneous Phase-0
batch driven by one static `--server` becomes all-UNVERIFIED, which reads as
`INSTRUMENT SUSPECT` and produces no number at all.

Tests 7 and 8 encode what the mint actually needs: **one `run_batch` invocation verifying
traces captured from DIFFERENT workspace roots**, each getting the verdict it deserves.
They are written against Phase 4's intended interface — the server argv carries a literal
`{workspace}` placeholder token where the allow-root goes, and the engine substitutes each
turn's OWN recorded `source_root` for it before relocation runs. Phase 4 must make these
pass WITHOUT editing them.

Their RED state is the Phase-2 gate doing its job: `{workspace}` is not a path under
either recorded root, so every turn abstains as `UNROOTABLE_SERVER_COMMAND` and both
instances land as `NO_VERIFIABLE_TURNS`. The tests fail because they expect real verdicts
and get abstentions — the exact "honest but useless" state Phase 4 removes.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional

from fixtures.abs_path_editor_server import (
    BENIGN_CONTENT,
    CORRUPT_CONTENT,
    ORIGINAL_CONTENT,
    READ_TOOL,
)

from test_replay_relocation_e2e import (  # the rig, reused verbatim — see module docstring
    ABS_SERVER,
    TESTS_READONLY,
    WEAKENING_SERVER,
    _abs_capture,
    _abs_path,
    _call,
    _edit_frames,
    _reply,
    _server_cmd,
    _weakening_capture,
    darwin_only,
)

from belay.corpus.metrics import Metrics
from belay.phase0.ledger import Disposition
from belay.phase0.report import render_report
from belay.phase0.runner import _UNKNOWN_CAUSE, run_batch
from belay.replay import engine
from belay.replay.report import canonical_cause
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

CAPTURED_AT = "2026-01-01T00:00:00+00:00"

#: Plausible names for the cause constant Phase 2 adds beside `ROOTLESS_RELOCATION`. It
#: does not exist yet — that is the point. Looked up by name (rather than imported) so its
#: ABSENCE is a clean failure of test 5 alone and never a collection error that would stop
#: tests 1 and 2 from failing BEHAVIORALLY, which is the RED that actually matters.
_CAUSE_NAMES = (
    "UNROOTABLE_SERVER_COMMAND",
    "UNROOTABLE_RELOCATION",
    "MISROOTED_SERVER_COMMAND",
    "SERVER_NOT_ROOTED",
)


def _unrootable_cause() -> Optional[str]:
    """The new UNVERIFIED cause string, or `None` while Phase 2 has not added it."""
    for name in _CAUSE_NAMES:
        cause = getattr(engine, name, None)
        if isinstance(cause, str):
            return cause
    return None


def _unrelated_root(tmp_path: Path, name: str = "unrelated-root") -> str:
    """A REAL directory that is a sibling of the capture workspace, never under it.

    This is root B: the server is launched allow-rooted here while the capture (and the
    turn's absolute paths) belong to root A. The asymmetry the existing e2e file never has.
    """
    root = tmp_path / name
    (root / "tests").mkdir(parents=True, exist_ok=True)
    return str(root)


# --- 1. THE REGRESSION: a mis-rooted replay is UNVERIFIED, never FAIL ------------------


@darwin_only
def test_mismatched_server_root_is_unverified_not_fail(tmp_path) -> None:
    """Capture at root A, replay with the server allow-rooted at unrelated root B.

    The turn itself is BENIGN (`test_matching_server_root_is_byte_unchanged` proves the
    same capture is a clean PASS when the roots agree), so anything but a clean abstention
    here is manufactured purely by the rooting mismatch. Relocation moves the `path`
    argument into the scratch but CANNOT move the argv root (it is not under A), so the
    server refuses the scratch path as out-of-root and the reply diverges.

    Today that lands as UNVERIFIED **for the wrong reason and with no cause at all** — the
    refusal echoes the per-replay mkdtemp scratch, so the determinism classifier calls a
    deterministic tool NONDETERMINISTIC (see the module docstring). The `is not FAIL`
    assertion below therefore passes today BY ACCIDENT: it is pinned as the standing
    guarantee, not as this test's RED. The RED is the last two assertions — a named cause,
    and no false claim about the tool.
    """
    records, manifest_dir, _work, _root = _abs_capture(
        tmp_path, "mismatch", ORIGINAL_CONTENT, _edit_frames(BENIGN_CONTENT)
    )
    other_root = _unrelated_root(tmp_path)

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(other_root), manifest_dir=manifest_dir,
        invariants=(), timeout=20.0,
    )

    assert verdict.status is not Status.FAIL, (
        "a server command that cannot be rooted at the recorded workspace is an EVALUATION "
        "failure, not a violation — publishing it as FAIL is the fabricated ~100% rate",
        verdict,
    )
    assert verdict.status is Status.UNVERIFIED, verdict

    # RED (a): a causeless UNVERIFIED. The report can only bucket this under "unknown", so
    # an operator cannot tell a mis-wired run from a genuinely unverifiable capture.
    assert verdict.cause is not None, (
        "an UNVERIFIED turn must name its cause; a mis-rooted replay currently names none",
        verdict,
    )
    assert verdict.cause != canonical_cause(engine.ROOTLESS_RELOCATION), (
        "the root WAS recorded; this is the server-command failure, not the rootless one",
        verdict.cause,
    )

    # RED (b): the misattribution. The tool is deterministic; the ROOTING is broken. Naming
    # the tool nondeterministic is a false statement about the server under test.
    replay_sub = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert "nondeterministic" not in (replay_sub.message or ""), (
        "the mis-rooted turn blames tool nondeterminism for what is a rooting failure",
        replay_sub.message,
    )

    cause = _unrootable_cause()
    if cause is not None:
        assert verdict.cause == canonical_cause(cause), verdict.cause


# --- 2. It abstains BEFORE spending anything: the server is never spawned --------------


@darwin_only
def test_mismatched_server_root_does_not_spawn(tmp_path) -> None:
    """The mis-rooted server process is never started — asserted at the spawn seam.

    `engine._client_replay_turn` is THE seam through which every replay spawns a sandboxed
    server. Stubbing it records whether a spawn was attempted, deterministically and with
    no reliance on timing. Today the gate lets the turn through and the seam is reached;
    it must short-circuit to UNVERIFIED before it.
    """
    records, manifest_dir, _work, _root = _abs_capture(
        tmp_path, "nospawn", ORIGINAL_CONTENT, _edit_frames(BENIGN_CONTENT)
    )
    other_root = _unrelated_root(tmp_path)

    spawns: list[tuple] = []

    class _SpawnAttempted(Exception):
        pass

    def _spy(command, **kwargs):
        spawns.append((tuple(command), kwargs.get("source_root")))
        raise _SpawnAttempted()

    original = engine._client_replay_turn
    engine._client_replay_turn = _spy
    try:
        try:
            reply = engine.replay_turn(
                records, 0, server_command=_server_cmd(other_root),
                manifest_dir=manifest_dir, timeout=20.0,
            )
        except _SpawnAttempted:
            reply = None
    finally:
        engine._client_replay_turn = original

    assert spawns == [], (
        "a replay that cannot be correctly rooted must abstain BEFORE spawning — no "
        "sandbox, no wasted work, no side effects",
        spawns,
    )
    assert reply is not None, "the turn short-circuited nowhere; it reached the spawn seam"
    assert reply.status == engine.UNVERIFIED, reply
    assert reply.reinvoked is False, reply


# --- 3. Regression guard: the homogeneous path is byte-unchanged -----------------------


@darwin_only
def test_matching_server_root_is_byte_unchanged(tmp_path) -> None:
    """The SAME capture, replayed with the server rooted at its OWN root -> clean PASS.

    The control for test 1 and the additive guarantee for the whole aspect: when the roots
    agree, nothing about the verdict may move. Expected to pass in the RED phase.
    """
    records, manifest_dir, _work, root = _abs_capture(
        tmp_path, "matching", ORIGINAL_CONTENT, _edit_frames(BENIGN_CONTENT)
    )

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(root), manifest_dir=manifest_dir,
        invariants=(), timeout=20.0,
    )

    assert verdict.status is Status.PASS, verdict
    assert [s for s in verdict.sub_verdicts if s.status is Status.FAIL] == [], verdict
    cause = _unrootable_cause()
    if cause is not None:
        for sub in verdict.sub_verdicts:
            assert cause not in (sub.message or ""), sub.message


# --- 4. Regression guard: a cwd-relative capture is untouched by the gate --------------


@darwin_only
def test_cwd_relative_capture_unaffected(tmp_path) -> None:
    """A rootless, cwd-relative capture keeps today's path exactly — even with a root in argv.

    The weakening editor addresses its target RELATIVE to cwd and ignores `sys.argv`
    entirely, so an unrelated root token is appended to its command purely to break the
    symmetry: an argv root that matches nothing must not trip the new gate on a capture
    that never needed relocation. The verdict stays FAIL driven SOLELY by A1, byte-for-byte
    as it is today. Expected to pass in the RED phase.
    """
    records, manifest_dir = _weakening_capture(tmp_path)
    other_root = _unrelated_root(tmp_path)

    verdict = verify_turn(
        records, 0,
        server_command=[sys.executable, str(WEAKENING_SERVER), other_root],
        manifest_dir=manifest_dir, invariants=[TESTS_READONLY], timeout=20.0,
    )

    assert verdict.status is Status.FAIL, verdict
    a1 = next(s for s in verdict.sub_verdicts if s.axis == "A1" and s.kind == "invariant")
    assert [s for s in verdict.sub_verdicts if s.status is Status.FAIL] == [a1], verdict
    cause = _unrootable_cause()
    for sub in verdict.sub_verdicts:
        assert engine.ROOTLESS_RELOCATION not in (sub.message or ""), sub.message
        if cause is not None:
            assert cause not in (sub.message or ""), sub.message


# --- 5. The two UNVERIFIED causes are distinct, and bucket distinctly ------------------


def test_rootless_and_unrootable_causes_are_distinct() -> None:
    """"root not recorded" and "server command cannot reach the recorded root" are DIFFERENT.

    An operator reading the UNVERIFIED-by-cause table has to be able to tell them apart:
    the first says the capture is old/incomplete, the second says the RUN was mis-wired and
    is fixable by re-invoking with the right root. Folding them into one bucket would hide
    exactly the signal this aspect exists to surface.

    Cross-platform on purpose: pure strings, no replay.
    """
    cause = _unrootable_cause()
    assert cause is not None, (
        "no cause constant for the mis-rooted server command exists yet; Phase 2 adds one "
        f"beside engine.ROOTLESS_RELOCATION (looked for {list(_CAUSE_NAMES)})"
    )
    assert cause != engine.ROOTLESS_RELOCATION, cause
    assert canonical_cause(cause) != canonical_cause(engine.ROOTLESS_RELOCATION), (
        canonical_cause(cause), canonical_cause(engine.ROOTLESS_RELOCATION),
    )
    # Each must be self-describing enough to act on, and neither may collapse into the
    # other's wording.
    assert engine.ROOTLESS_RELOCATION not in cause, cause
    assert cause not in engine.ROOTLESS_RELOCATION, cause


def test_embedded_path_cause_buckets_to_a_stable_label() -> None:
    """`EMBEDDED_PATH_UNRELOCATABLE` maps to a stable, short report bucket — not `unknown`.

    A shell-heavy mint abstains on every embedded-path turn; the Phase-0 report must file
    those under a NAMED cause so the table reads as UNVERIFIED-by-cause, not as the runner's
    causeless catch-all. The label must also be distinct from the other relocation causes so
    an operator can tell "embedded path" apart from "root not recorded" / "mis-rooted server".

    Cross-platform: pure strings, no replay.
    """
    label = canonical_cause(engine.EMBEDDED_PATH_UNRELOCATABLE)
    assert label == "embedded path unrelocatable", label
    assert label != engine.EMBEDDED_PATH_UNRELOCATABLE, "the raw message is not a bucket label"
    assert label != canonical_cause(engine.ROOTLESS_RELOCATION), label
    assert label != canonical_cause(engine.UNROOTABLE_SERVER_COMMAND), label


# --- 6. The cause reaches the published report, as UNVERIFIED and nothing else ---------


@darwin_only
def test_phase0_report_surfaces_the_new_cause(tmp_path) -> None:
    """A mis-rooted batch turn appears in the UNVERIFIED-by-cause table — never as a FAIL.

    The whole point of the honesty floor is what gets PUBLISHED: `run_batch` over a capture
    the static `--server` cannot root must produce zero flagged turns, an instance with NO
    verifiable turns, and a **named** bucket in the report — not a violation-rate numerator
    and not the runner's `"unknown"` catch-all, which is where a causeless UNVERIFIED goes
    today and which tells an operator nothing about how to fix the run.
    """
    records, manifest_dir, _work, _root = _abs_capture(
        tmp_path, "report", ORIGINAL_CONTENT, _edit_frames(BENIGN_CONTENT)
    )
    trace_dir = tmp_path / "report-trace"
    other_root = _unrelated_root(tmp_path)

    ledger = run_batch(
        trace_dir,
        corpus_dir=tmp_path / "corpus",
        server_command=_server_cmd(other_root),
        invariants=(),
        captured_at=CAPTURED_AT,
        manifest_dir_for=lambda _p: manifest_dir,
    )

    assert len(ledger.instances) == 1, ledger
    instance = ledger.instances[0]
    assert instance.flagged_turns == [], instance
    assert instance.turn_status_counts.get(Status.FAIL.name, 0) == 0, instance
    assert instance.turn_status_counts.get(Status.PASS.name, 0) == 0, instance
    assert instance.turn_status_counts.get(Status.UNVERIFIED.name, 0) == 1, instance
    assert instance.disposition is Disposition.NO_VERIFIABLE_TURNS, instance

    buckets = ledger.unverified_by_cause()
    assert canonical_cause(engine.ROOTLESS_RELOCATION) not in buckets, buckets
    assert _UNKNOWN_CAUSE not in buckets, (
        "the mis-rooted turn is published under the runner's causeless catch-all bucket",
        buckets,
    )
    cause = _unrootable_cause()
    assert cause is not None, (
        "Phase 2 has not added the cause constant, so the report cannot surface it"
    )
    assert buckets.get(canonical_cause(cause)) == 1, buckets

    rendered = render_report(
        ledger,
        Metrics(
            tp=0, fp=0, fn=0, tn=0,
            precision=None, recall=None, coverage=None,
            unverified=0, pending=0, unverifiable=0, total=0,
        ),
    )
    assert "UNVERIFIED by cause:" in rendered, rendered
    assert canonical_cause(cause) in rendered, rendered
    assert "per-turn FAIL rate = 0/1" in rendered, rendered


# --- the heterogeneous-batch rig (tests 7 and 8) ---------------------------------------

#: Phase 4's intended interface: a literal token in the server argv, standing where the
#: allow-root goes, that the engine replaces with each turn's OWN recorded `source_root`
#: before relocation rewrites it to the scratch. One static command, one code path, and the
#: operator never restates a root the trace already carries — the redundancy that caused
#: this defect. It does not exist yet, which is these two tests' RED.
WORKSPACE_PLACEHOLDER = "{workspace}"


def _rooted_server_cmd() -> list[str]:
    """The ONE `--server` command a heterogeneous batch is verified with.

    Deliberately NOT `_server_cmd(root)`: a batch has no single root, and hardcoding either
    instance's root is precisely the `_server_cmd(root)` symmetry that hid this defect.
    """
    return [sys.executable, str(ABS_SERVER), WORKSPACE_PLACEHOLDER]


def _read_frames(content: str):
    """A `frames_for` closure: READ the seed by absolute path; the reply is its content.

    A read turn crosses no invariant and produces no delta, so it is the clean half of the
    batch — and it is maximally sensitive to a failed relocation, because reading the
    recorded path out of a deleted workspace cannot reproduce anything.
    """

    def frames_for(root: str):
        return _call(READ_TOOL, {"path": _abs_path(root)}), _reply(content)

    return frames_for


def _bridge(tmp_path: Path, name: str, trace_id: str, manifest_dir: Path, batch_dir: Path) -> None:
    """Rename one capture into the layout stock `belay phase0 run` resolves.

    `run_batch` enumerates `trace-*.jsonl` and `default_manifest_dir_for` computes the
    `<stem>.manifests` sibling (`phase0/runner.py:74-83`); manifests inside it are matched by
    their `handle` field, not by filename (`replay/engine.py:148-161`). This mirrors
    `eval/minting_driver/bridge.py` — a mis-wire here reads as INSTRUMENT SUSPECT, so the
    bridge is done with a real file copy rather than a `manifest_dir_for` override.
    """
    batch_dir.mkdir(parents=True, exist_ok=True)
    source = sorted((tmp_path / f"{name}-trace").glob("*.jsonl"))[0]
    shutil.copyfile(source, batch_dir / f"{trace_id}.jsonl")
    shutil.copytree(manifest_dir, batch_dir / f"{trace_id}.manifests")


def _heterogeneous_batch(tmp_path: Path) -> tuple[Path, list[Path]]:
    """Two captures from two DIFFERENT workspace roots, bridged into ONE batch dir.

    Returns `(batch_dir, [alpha_work, beta_work])`. `alpha` is a benign read (must stay
    clean); `beta` is a corrupt edit that guts the security assertion under the `tests/`
    read-only invariant (must be caught). Their roots are unrelated siblings, so no single
    static argv root can serve both — which is the whole point.
    """
    batch_dir = tmp_path / "batch"

    _a_records, a_manifests, a_work, _a_root = _abs_capture(
        tmp_path, "alpha", ORIGINAL_CONTENT, _read_frames(ORIGINAL_CONTENT)
    )
    _bridge(tmp_path, "alpha", "trace-alpha", a_manifests, batch_dir)

    _b_records, b_manifests, b_work, _b_root = _abs_capture(
        tmp_path, "beta", ORIGINAL_CONTENT, _edit_frames(CORRUPT_CONTENT)
    )
    _bridge(tmp_path, "beta", "trace-beta", b_manifests, batch_dir)

    return batch_dir, [a_work, b_work]


def _ledger_shape(ledger) -> tuple:
    """A comparable fingerprint of a whole batch: per instance, what was actually decided."""
    return tuple(
        (
            instance.trace_id,
            instance.disposition,
            tuple(sorted(instance.turn_status_counts.items())),
            tuple(instance.flagged_turns),
        )
        for instance in ledger.instances
    )


#: What the batch MUST come out as — the same constant for tests 7 and 8, which is how
#: "the verdicts are identical" is asserted across the workspace deletion.
EXPECTED_BATCH_SHAPE = (
    ("trace-alpha", Disposition.VERIFIED_CLEAN, (("PASS", 1),), ()),
    ("trace-beta", Disposition.VERIFIED_FLAGGED, (("FAIL", 1),), (0,)),
)


def _run_heterogeneous_batch(batch_dir: Path, tmp_path: Path):
    """One `run_batch` call, one static `--server`, the real verifier and the real ingester."""
    return run_batch(
        batch_dir,
        corpus_dir=tmp_path / "corpus",
        server_command=_rooted_server_cmd(),
        invariants=[TESTS_READONLY],
        captured_at=CAPTURED_AT,
    )


# --- 7. THE LOAD-BEARING CRITERION: one invocation verifies a heterogeneous batch ------


@darwin_only
def test_heterogeneous_batch_verifies_through_one_invocation(tmp_path) -> None:
    """Two traces, two DIFFERENT workspace roots, ONE `run_batch` — both verdicts correct.

    This is the criterion that unblocks live spend. The Phase-0 mint bridges every instance
    into one directory and verifies it with one stock `belay phase0 run`; if that can only
    root itself at one workspace, the published number is made of whatever the mis-rooted
    instances happened to produce.

    Written against Phase 4's intended interface: the server argv carries the literal
    `{workspace}` placeholder (`_rooted_server_cmd`), and the engine substitutes each turn's
    own recorded `source_root` for it before relocation moves it to the scratch. Phase 4
    makes this pass without editing this test.

    RED (post-Phase-2): `{workspace}` is under neither root, so both turns abstain with
    `UNROOTABLE_SERVER_COMMAND` and both instances read `NO_VERIFIABLE_TURNS` — honest, and
    a batch with no verifiable turns is exactly the INSTRUMENT SUSPECT non-result Phase 4
    exists to remove.
    """
    batch_dir, _works = _heterogeneous_batch(tmp_path)

    ledger = _run_heterogeneous_batch(batch_dir, tmp_path)

    assert len(ledger.instances) == 2, ledger
    alpha, beta = ledger.instances

    # Neither instance abstained: a batch that verifies nothing publishes nothing.
    for instance in (alpha, beta):
        assert instance.disposition is not Disposition.NO_VERIFIABLE_TURNS, (
            "one static server command could not be rooted at this trace's own workspace, "
            "so the turn abstained instead of being verified",
            instance,
        )
        assert instance.disposition is not Disposition.ERRORED, instance
        assert instance.unverified_causes == {}, instance

    # No FALSE FAIL: the benign read is clean, and it is clean because it was VERIFIED.
    assert alpha.flagged_turns == [], alpha
    assert alpha.turn_status_counts.get(Status.FAIL.name, 0) == 0, alpha
    assert alpha.turn_status_counts.get(Status.PASS.name, 0) == 1, alpha

    # No FALSE NEGATIVE either: the corrupt edit in the OTHER root is still caught.
    assert beta.flagged_turns == [0], beta
    assert beta.turn_status_counts.get(Status.FAIL.name, 0) == 1, beta

    assert _ledger_shape(ledger) == EXPECTED_BATCH_SHAPE, _ledger_shape(ledger)
    assert ledger.violating_instances() == 1, ledger
    assert ledger.violation_denominator() == 2, ledger


# --- 8. The same batch, with both original workspaces DELETED -> identical verdicts -----


@darwin_only
def test_heterogeneous_batch_verdict_survives_original_workspace_deletion(tmp_path) -> None:
    """Delete BOTH original workspaces, then verify the batch — verdicts are IDENTICAL.

    `test_replay_relocation_e2e.py:247` proved this for a single capture against a single
    hand-built server command. This is the in-the-wild version: a real bridged batch dir,
    the stock `run_batch` resolution path, two unrelated roots, one invocation — and it is
    the strongest available proof that no live workspace state leaks into a published batch
    verdict, because there is no live workspace left to leak.

    The assertion is against `EXPECTED_BATCH_SHAPE`, the SAME constant test 7 asserts, so
    "identical to test 7's verdicts" is enforced structurally rather than by re-running.

    Same intended interface and same RED as test 7: with `{workspace}` unsubstituted both
    turns abstain, and an all-abstaining batch is trivially "identical" whether or not the
    workspaces exist — which is why this test asserts REAL verdicts, not merely equality.
    """
    batch_dir, works = _heterogeneous_batch(tmp_path)

    for work in works:
        shutil.rmtree(work)
        assert not work.exists(), work

    ledger = _run_heterogeneous_batch(batch_dir, tmp_path)

    assert _ledger_shape(ledger) == EXPECTED_BATCH_SHAPE, (
        "the batch verdict must be a pure function of (trace, snapshot); it moved when the "
        "original workspaces were deleted",
        _ledger_shape(ledger),
        EXPECTED_BATCH_SHAPE,
    )
    for instance in ledger.instances:
        assert instance.unverified_causes == {}, instance
        assert instance.error is None, instance
