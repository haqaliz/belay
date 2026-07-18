"""`belay sandbox check` — a one-shot self-test with honest limits.

## What this answers, and what it refuses to answer

Two questions, deliberately unequal:

1. **Does the substrate work on this machine?** Answerable. Seatbelt is
   deprecated, `clonefile` needs APFS, and both are properties of the box in front
   of you. So they are *probed by use* — a snapshot is really taken, a profile is
   really compiled — never declared from a table.

2. **Is the scope too tight for this server?** **Refutable only.** This runs the
   server briefly and reports what it saw. Seeing nothing is not evidence of
   sufficiency, and this command does not pretend otherwise.

That second asymmetry is the whole design. The tempting version of this tool runs
a server for two seconds, observes no denial, and prints "scope OK" — which is a
false PASS with a CLI in front of it, in the product whose entire thesis is that
claims must be grounded in execution. So the words "not proof" appear in the
output, and `test_check_does_not_read_silence_as_sufficiency` keeps them there.

## Two ways a scope kills a server, and only one is visible

A denial record is **inferred from the child's stderr** (`seatbelt._denials_from_stderr`
explains why: Seatbelt reports to the system log, not to the child in any
structured form). So Belay only sees a refusal the child *complains about in the
expected words*.

Measured, and the reason `_run_server` keys on the exit code as well: a Python
server whose `$TMPDIR` is outside the scope dies with
`No usable temporary directory found in [...]` and **no denial record at all** —
`tempfile` catches every `EPERM` itself and reports its own aggregate error. A
check that keyed only on denial records would call that run clean while the server
was dying of exactly the thing this command exists to find. Hence: a non-zero exit
is a finding, stated as an unexplained one.

## It diagnoses; it never fixes

Nothing here widens a scope. A tool that widened the boundary until the error went
away would be authoring the invariant, which is the failure `scope.py` exists to
prevent — the boundary has to come from somewhere better than "the symptom
stopped".
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

__all__ = ["main"]

#: How long the server is given before it is assumed to be running happily. It is
#: a *sample*, not a verdict — see the module docstring. A server that idles on
#: stdin will simply be killed at the end of it, which is a clean exit for our
#: purposes and is why a timeout is not itself reported as a failure.
DEFAULT_SECONDS = 2.0

#: The per-replay timeout `corpus add` records on a case and re-executes the turn under.
#: Kept equal to `belay.replay.client.DEFAULT_TIMEOUT` but declared here so building the
#: parser does not import the replay stack — cli.py imports everything else lazily to keep
#: `belay --help` cheap, and a `test_default_timeout_matches_client` pins the two together.
DEFAULT_TIMEOUT = 10.0

_OK = "ok"
_PROBLEM = "PROBLEM"


def _emit(line: str = "") -> None:
    print(line)


def _check_substrate(scope_root: str) -> bool:
    """Probe the substrate by using it. Returns True if it works here.

    Everything below is executed rather than asserted: a table of what macOS
    supports is a claim about a machine that is not necessarily this one, and this
    command's only purpose is to talk about this one.
    """
    from belay.sandbox import seatbelt
    from belay.snapshot import substrate

    ok = True

    _emit("substrate")
    _emit(f"  platform            {sys.platform} ({_OK if sys.platform == 'darwin' else _PROBLEM})")
    if sys.platform != "darwin":
        _emit("    Belay's sandbox is macOS-only. Nothing here is enforced on this platform.")
        return False

    has_sandbox_exec = Path(seatbelt.SANDBOX_EXEC).exists()
    _emit(f"  sandbox-exec        {seatbelt.SANDBOX_EXEC} ({_OK if has_sandbox_exec else _PROBLEM})")
    ok = ok and has_sandbox_exec

    # Take a real snapshot of a real tree and read it back.
    probe = Path(tempfile.mkdtemp(prefix="belay-check-"))
    try:
        ok = _probe_containment(scope_root, probe) and ok
        source = probe / "source"
        source.mkdir()
        (source / "probe.txt").write_bytes(b"probe")
        snap = substrate.take_snapshot(source, probe / "snapshot")
        substrate.guarded_restore(snap, probe / "restored")
        restored = (probe / "restored" / "probe.txt").read_bytes() == b"probe"
        _emit(f"  snapshot backend    {snap.manifest.backend} ({_OK if restored else _PROBLEM})")
        _emit(f"  capabilities        {', '.join(sorted(snap.manifest.capabilities))}")
        ok = ok and restored
    except Exception as exc:  # noqa: BLE001
        _emit(f"  snapshot backend    {_PROBLEM}: {type(exc).__name__}: {exc}")
        ok = False
    finally:
        substrate.gc(probe)

    return ok


def _probe_containment(scope_root: str, probe: Path) -> bool:
    """Does the sandbox actually CONTAIN on this machine? Attempt an escape and see.

    **Why an escape attempt rather than "the profile compiled".** Building a profile
    is string formatting — `seatbelt.build_profile` returns text, and text enforces
    nothing. The failure this command exists to catch is not a missing binary; it is
    a Seatbelt that runs the command and enforces **nothing at all**, which is a live
    possibility for a mechanism Apple has deprecated. Only an attempted escape
    distinguishes "contained" from "not enforcing".

    **The positive control is load-bearing.** The child writes *inside* the scope as
    well as outside. Without the inside write, a `sandbox-exec` that ran nothing at
    all would produce no escape file, and "the escape did not land" would read as
    containment when the truth is that the probe never happened.

    So three outcomes, all distinguishable:
      inside ✓ / outside ✗ → contained.
      inside ✗            → the probe never ran; conclude nothing.
      inside ✓ / outside ✓ → it ran and enforced nothing. The loudest failure here.
    """
    from belay.sandbox import seatbelt

    inside = Path(scope_root) / ".belay-check-inside"
    outside = probe / "escaped"

    try:
        seatbelt.run(
            [
                "/bin/sh",
                "-c",
                f'echo in > "{inside}"; echo out > "{outside}"',
            ],
            scope=scope_root,
            network=seatbelt.NetworkPolicy.deny_all(),
            timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001
        _emit(f"  containment         {_PROBLEM}: could not run under the profile: {exc}")
        return False
    finally:
        ran = inside.exists()
        inside.unlink(missing_ok=True)

    if not ran:
        _emit(f"  containment         {_PROBLEM}: the probe never ran; nothing was verified")
        return False
    if outside.exists():
        # The sandbox executed the command and did not stop it. Say so plainly:
        # everything else this command reports is worthless if this is true.
        _emit(f"  containment         {_PROBLEM}: a write to {outside} SUCCEEDED — NOT ENFORCING")
        return False

    _emit(f"  containment         {_OK} (a write outside the scope was refused)")
    return True


def _report_scope(scope) -> None:
    _emit()
    _emit("scope")
    _emit(f"  workspace           {scope.snapshot_root}")
    _emit("    Writable, and the only tree a turn's snapshot captures.")
    _emit(f"  TMPDIR              {scope.tmpdir}")
    _emit("    Writable, and NOT snapshotted. Relocated out of the workspace so a")
    _emit("    server's temp files need no hand-widening and no turn's state diff")
    _emit("    carries its temp churn. Created here; safe to delete.")


def _run_server(scope, command: Sequence[str], seconds: float) -> bool:
    """Run `command` briefly under the default profile. Returns True if nothing was seen."""
    from belay.sandbox import seatbelt

    _emit()
    _emit("server")
    _emit(f"  command             {' '.join(command)}")

    try:
        result = seatbelt.run(
            scope.wrap(command),
            scope=scope.write_roots,
            network=seatbelt.NetworkPolicy.deny_all(),
            timeout=seconds,
        )
    except subprocess.TimeoutExpired as exc:
        # Still running when the sample ended. For a stdio server blocked on a
        # client that never comes, that is the **normal** shape rather than a
        # fault — it is what every real MCP server does here.
        _emit(f"  ran {seconds:g}s              {_OK} (still running, killed at the sample's end)")
        denials = _denials_of(exc)
        _emit_denials(denials)
        # But outliving the sample does not un-do a refusal it already reported.
        # Returning True here regardless would have called a denied-then-serving
        # server clean, which is a false PASS on the one signal this command is for.
        return not denials
    except Exception as exc:  # noqa: BLE001
        _emit(f"  {_PROBLEM}: could not run the server at all: {type(exc).__name__}: {exc}")
        return False

    ok = True
    if result.rc != 0 and not result.denials:
        # The measured case: killed by the scope, complaining in its own words.
        _emit(f"  exit                {_PROBLEM}: exited {result.rc} without reporting a denial")
        _emit("    Belay infers denials from the child's stderr, so a server that")
        _emit("    handles the error itself leaves no denial record. Its own output:")
        for line in _tail(result.stderr):
            _emit(f"      {line}")
        ok = False
    elif result.rc != 0:
        _emit(f"  exit                {_PROBLEM}: exited {result.rc}")
        ok = False
    else:
        _emit(f"  exit                {_OK} (0)")

    if result.denials:
        ok = False
    _emit_denials(result.denials)
    return ok


def _emit_denials(denials) -> None:
    if not denials:
        _emit(f"  denials             {_OK}: no denials observed")
        return
    _emit(f"  denials             {_PROBLEM}: {len(denials)} observed")
    for denial in denials:
        _emit(f"    {denial.op:<12} {denial.path}")
        # The provenance travels with the record, exactly as it does in the trace.
        # We saw the child complain; we did not see the kernel deny.
        _emit("      inferred: true  source: child-stderr")
        _emit(f"      {denial.detail}")


def _denials_of(exc: subprocess.TimeoutExpired) -> tuple:
    """Denials from what the child printed before the sample ended.

    Reaches for `seatbelt._denials_from_stderr` by name: a server that reported a
    refusal and then went on waiting for stdin would otherwise have that refusal
    dropped on the floor, which is the one thing this command exists to surface.
    The inference lives in one place and this is that place, private or not.
    """
    from belay.sandbox.seatbelt import _denials_from_stderr

    return _denials_from_stderr(exc.stderr or b"")


def _tail(stream: bytes, lines: int = 4) -> list[str]:
    text = stream.decode("utf-8", errors="replace").strip().splitlines()
    return text[-lines:]


def _caveat(ran_a_server: bool) -> None:
    _emit()
    _emit("what this check does and does not establish")
    _emit("  The substrate result is a fact: it was probed by using it.")
    if ran_a_server:
        _emit("  The scope result is not proof that the scope fits. It reports")
        _emit("  only what this run touched, in a few seconds, on one code path.")
        _emit("  A denial this server hits on its four-hundredth turn is still")
        _emit("  ahead of it. This check can refute a scope; it cannot confirm one.")
    else:
        _emit("  No scope conclusion was reached: no server command was given, so")
        _emit("  nothing exercised the scope. Pass one after `--` to sample it.")


def _cmd_sandbox_check(args: argparse.Namespace) -> int:
    from belay.sandbox.scope import default_scope

    try:
        scope = default_scope(args.scope)
    except ValueError as exc:
        _emit(f"belay: {exc}")
        return 2

    substrate_ok = _check_substrate(scope.snapshot_root)
    _report_scope(scope)

    server_ok = True
    if args.command:
        server_ok = _run_server(scope, args.command, args.seconds)
    else:
        _emit()
        _emit("server")
        _emit("  no server command given — the scope was not exercised.")

    _caveat(bool(args.command))

    _emit()
    if not substrate_ok:
        _emit("belay: the substrate does not work here. Belay cannot contain or")
        _emit("       snapshot anything on this machine.")
        return 1
    if not server_ok:
        _emit("belay: the scope was too tight for this server, or it failed for")
        _emit("       another reason. Nothing was widened — the paths above are the")
        _emit("       diagnosis, and the decision is yours.")
        return 1
    _emit("belay: substrate ok" + (", nothing refused in this run" if args.command else ""))
    return 0


def _pct(fraction: float) -> str:
    """A percentage with no false precision — the rate is a coverage fact, not a grade."""
    return f"{round(fraction * 100)}%"


def _cmd_replay(args: argparse.Namespace) -> int:
    """`belay replay <trace>` — replay a trace and report the UNVERIFIED rate.

    Reads the trace back, replays each recorded `tools/call` against its restored
    pre-state, and prints per-turn observations plus the aggregate: the UNVERIFIED
    rate with every instance filed under a named cause. It states
    replayed/unverified/not-verifiable — never PASS/FAIL, which is C4's. The rate is
    an observation about coverage, not a verdict.
    """
    from belay.replay.reader import TraceCorrupt, read_trace
    from belay.replay.report import replay_trace

    if not args.server:
        _emit("belay: a server command is required, after --server. Nothing to replay against.")
        return 2

    trace_path = Path(args.trace)
    if not trace_path.exists():
        _emit(f"belay: trace not found: {trace_path}")
        return 2

    try:
        read = read_trace(trace_path)
    except TraceCorrupt as exc:
        _emit(f"belay: {exc}")
        return 2

    manifest_dir = Path(args.manifest_dir)
    try:
        report = replay_trace(
            read.records,
            server_command=args.server,
            manifest_dir=manifest_dir,
            replays=args.replays,
            only=args.turn,
        )
    except ValueError as exc:
        _emit(f"belay: {exc}")
        return 2

    turns = report.turns

    _emit(f"belay replay {trace_path}")
    _emit()
    _emit(f"  {len(report.turns)} tool-call turn(s), replayed against restored pre-state.")
    _emit(f"  manifests             {manifest_dir}")
    _emit("    A turn's snapshot manifest is written by the gate to a SIBLING of the")
    _emit("    snapshot dir: BELAY_SNAPSHOT_DIR=./sn -> ./sn.manifests/. Point")
    _emit("    --manifest-dir there. A present turn whose manifest is not found is an")
    _emit("    honest UNVERIFIED (manifest not found), never a fabricated result.")

    _emit()
    _emit("turns")
    for turn in turns:
        _emit_turn(turn)

    _emit()
    _emit("coverage")
    _emit(f"  turns total           {report.total}")
    _emit(f"  replayed              {report.replayed}")
    _emit(f"  unverified            {report.unverified}")
    _emit(f"  not-verifiable        {report.not_verifiable}")
    _emit()
    _emit(
        f"  UNVERIFIED RATE       {report.unverified} / {report.total} "
        f"({_pct(report.unverified_rate)})"
    )
    if report.by_cause:
        _emit("    by cause")
        for cause, count in sorted(report.by_cause.items(), key=lambda kv: (-kv[1], kv[0])):
            _emit(f"      {cause:<44}{count}")
    if report.unverified == 0:
        _emit("    no turn was unverified in this run.")

    _emit()
    _emit("  Every unverified turn is named above. This is an observation about")
    _emit("  coverage, not a verdict — C3 reports what replayed and what did not;")
    _emit("  it does NOT emit PASS/FAIL. That is C4.")
    return 0


def _emit_turn(turn) -> None:
    from belay.replay.report import REPLAYED

    tool = turn.tool or "?"
    head = f"  turn {turn.turn_index:<3} {tool:<16}{turn.status:<16}"
    if turn.status == REPLAYED:
        tail = f"result {turn.result_equivalence or 'n/a'}; {turn.delta_summary or 'no delta'}"
        if turn.determinism is not None:
            tail += f"; {turn.determinism}"
        _emit(head + tail)
    else:
        # UNVERIFIED / NOT_VERIFIABLE: the named cause, and — when the engine gave a
        # longer verbatim reason — that too, so the bucket never hides the specifics.
        _emit(head + (turn.cause or "?"))
        if turn.raw_cause and turn.raw_cause != turn.cause:
            _emit(f"      {turn.raw_cause}")


# --- belay verify: the whole-trace verdict (A2 replay + A1 invariants) ----------------

#: The honest coverage statement, in the user's words. It appears BOTH here (printed
#: under every run) and in the `verify --help` description, because a user who never
#: reads --help still must not misread a PASS. Every clause is load-bearing and is
#: pinned by `tests/test_verify_cli.py`; do not soften one without changing the test.
_VERIFY_COVERAGE = (
    "what a verdict here means, exactly\n"
    "  A2 PASS means THE TRACE REPRODUCES: the recorded tool call, re-executed against\n"
    "  its restored pre-state, produced the same result and its filesystem effect\n"
    "  matched its declared readOnlyHint.\n"
    "  It does NOT mean the agent did the right thing.\n"
    "  A2 ALONE does not catch a cheating agent: a cheater's trace is faithful — replay\n"
    "  reproduces it and A2 PASSes, correctly — because the tampering is in the pre-state\n"
    "  A2 was handed. That corrupt success is caught by a declared invariant (A1): the\n"
    "  tests/ read-only default is composed into every turn (disable with\n"
    "  --no-default-invariants, or add your own with --invariants FILE), and an A1 FAIL\n"
    "  drives the turn to FAIL even when A2 PASSes. A1 grounds in the SAME observed delta —\n"
    "  it FAILs a turn whose replay wrote under a read-only scope, and is UNVERIFIED (never\n"
    "  a false PASS) when no post-state was observed or the rule cannot be grounded.\n"
    "  Verified: filesystem effects (the delta), result-equivalence, protocol/tool\n"
    "  errors. NOT verified: network egress, so openWorldHint conformance is UNVERIFIED,\n"
    "  never a network PASS. Belay observes no outbound bytes — successful egress under\n"
    "  allow-all is uncaptured, and a deny-all denial cannot be told from a filesystem one.\n"
    "  No model is consulted. The verdict is re-execution and diffing — no LLM."
)

_VERIFY_DESCRIPTION = (
    "Verify a whole trace by RE-EXECUTION. For each recorded tools/call, replay it "
    "against its restored pre-state and render its verdict: the A2 axis — "
    "result-equivalence (did the reply reproduce?) and effect-conformance (did the "
    "filesystem effect match the declared readOnlyHint?) — plus the A1 axis, the "
    "task-scoped invariants this run enforces (default: tests/ read-only, on unless "
    "--no-default-invariants; add more with --invariants FILE). All sub-verdicts are "
    "reduced worst-status-wins to one PASS/FAIL/UNVERIFIED per turn, each shown so a "
    "FAIL is explainable.\n\n" + _VERIFY_COVERAGE + "\n\n"
    "Manifests: a turn's snapshot manifest is written by the gate to a SIBLING of the "
    "snapshot dir, e.g. BELAY_SNAPSHOT_DIR=./sn -> ./sn.manifests/. Point "
    "--manifest-dir there; a present turn whose manifest is not found is an honest "
    "UNVERIFIED, never a fabricated PASS."
)


def _cmd_verify(args: argparse.Namespace) -> int:
    """`belay verify <trace>` — replay every tools/call and render its verdict.

    Whole-trace by default; `--turn N` narrows to one. Each turn is composed by
    `verify_turn` (one replay, both A2 checks, plus any A1 invariants, reduced), and
    printed with its reduced
    status AND both sub-verdicts so "why did this turn FAIL?" is answerable. The
    aggregate reports the PASS/FAIL/UNVERIFIED counts, the FAIL list with its concrete
    grounding, and the UNVERIFIED list with each named cause — never a hidden or
    spun-as-PASS unverified. Exit is non-zero if any turn is FAIL or UNVERIFIED: a run
    Belay could not fully stand behind must not read as success to a shell.
    """
    from belay.index import derive_correlation, tool_calls
    from belay.replay.reader import TraceCorrupt, read_trace
    from belay.verify.invariants import default_invariants, load_invariants
    from belay.verify.turn import verify_turn
    from belay.verify.verdict import Status

    if not args.server:
        _emit("belay: a server command is required, after --server. Nothing to replay against.")
        return 2

    trace_path = Path(args.trace)
    if not trace_path.exists():
        _emit(f"belay: trace not found: {trace_path}")
        return 2

    # The A1 policy this run enforces: the defaults (unless dropped) plus any operator file.
    # A file that will not parse is a fail-closed error — verifying against a silently dropped
    # policy would report the run against LESS than the operator declared, the exact false PASS
    # A1 exists to refuse. So a bad file exits 2 rather than proceeding.
    invariants = [] if args.no_default_invariants else default_invariants()
    if args.invariants is not None:
        try:
            invariants = invariants + load_invariants(Path(args.invariants))
        except ValueError as exc:
            _emit(f"belay: {exc}")
            return 2

    try:
        read = read_trace(trace_path)
    except TraceCorrupt as exc:
        _emit(f"belay: {exc}")
        return 2

    records = list(read.records)
    calls = tool_calls(derive_correlation(records))
    total = len(calls)

    if args.turn is not None:
        if not (0 <= args.turn < total):
            _emit(f"belay: --turn {args.turn} out of range; the trace holds {total} tool call(s)")
            return 2
        indices = [args.turn]
    else:
        indices = list(range(total))

    manifest_dir = Path(args.manifest_dir)

    _emit(f"belay verify {trace_path}")
    _emit()
    _emit(f"  {total} tool-call turn(s); verifying {len(indices)} by re-execution.")
    _emit(f"  manifests             {manifest_dir}")
    _emit()

    verdicts = []
    _emit("turns")
    for n in indices:
        verdict = verify_turn(
            records, n,
            server_command=args.server, manifest_dir=manifest_dir, replays=args.replays,
            invariants=invariants,
        )
        verdicts.append(verdict)
        _emit_verdict(verdict)

    _emit_aggregate(verdicts, Status)

    _emit()
    for line in _VERIFY_COVERAGE.splitlines():
        _emit(line)

    worst = _worst(verdicts, Status)
    return 0 if worst is Status.PASS else 1


def _emit_verdict(verdict) -> None:
    """One turn: its reduced status, tool, then each sub-verdict grouped by axis.

    The sub-verdicts are printed per AXIS (A1 / A2 / A3), not hard-coded to A2, so when
    A1 (C5) and A3 (C8) begin contributing sub-verdicts they render in the same shape
    without a rewrite here. Today only A2 speaks, and the loop shows exactly that.
    """
    tool = verdict.tool_name or "?"
    _emit(f"  turn {verdict.turn_index:<3} {tool:<18}{verdict.status.value}")
    for axis in _axes_in_order(verdict.sub_verdicts):
        for sub in (s for s in verdict.sub_verdicts if s.axis == axis):
            _emit(f"      {sub.axis} {sub.kind:<10}{sub.status.value:<12}{sub.message}")
    if verdict.cause is not None:
        _emit(f"      cause: {verdict.cause}")


def _axes_in_order(sub_verdicts) -> list[str]:
    """The distinct axes present, in first-seen order — A1, then A2, then A3 as built."""
    seen: list[str] = []
    for sub in sub_verdicts:
        if sub.axis not in seen:
            seen.append(sub.axis)
    return seen


def _emit_aggregate(verdicts, Status) -> None:
    counts = {status: 0 for status in Status}
    for verdict in verdicts:
        counts[verdict.status] += 1

    _emit()
    _emit("aggregate")
    _emit(f"  turns verified        {len(verdicts)}")
    _emit(f"  PASS                  {counts[Status.PASS]}")
    _emit(f"  WARN                  {counts[Status.WARN]}")
    _emit(f"  FAIL                  {counts[Status.FAIL]}")
    _emit(f"  UNVERIFIED            {counts[Status.UNVERIFIED]}")

    fails = [v for v in verdicts if v.status is Status.FAIL]
    if fails:
        _emit()
        _emit("  FAILs (with grounding)")
        for verdict in fails:
            for sub in verdict.sub_verdicts:
                if sub.status is Status.FAIL:
                    tool = verdict.tool_name or "?"
                    _emit(f"    turn {verdict.turn_index:<3} {tool:<18}{sub.axis} {sub.kind}: {sub.message}")

    unverified = [v for v in verdicts if v.status is Status.UNVERIFIED]
    if unverified:
        _emit()
        _emit("  UNVERIFIED (each with a named cause — never spun as PASS)")
        for verdict in unverified:
            tool = verdict.tool_name or "?"
            cause = verdict.cause or _first_unverified_message(verdict, Status)
            _emit(f"    turn {verdict.turn_index:<3} {tool:<18}{cause}")


def _first_unverified_message(verdict, Status) -> str:
    """The message of a REPLAYED-but-UNVERIFIED turn's driving sub-verdict.

    A turn that WAS replayed can still reduce to UNVERIFIED (an un-annotated tool, a
    nondeterministic divergence) with `cause is None` — its explanation lives in the
    sub-verdict, not a bucket. Surface it so no UNVERIFIED turn is causeless in the list.
    """
    for sub in verdict.sub_verdicts:
        if sub.status is Status.UNVERIFIED:
            return sub.message
    return "unverified"


def _worst(verdicts, Status):
    """The worst status across the turns, worst-status-wins. Empty -> UNVERIFIED.

    Mirrors `verdict.reduce`'s ordering (FAIL > UNVERIFIED > WARN > PASS) so the exit
    code agrees with the honesty contract: an all-UNVERIFIED run is not a success.
    """
    rank = {Status.PASS: 0, Status.WARN: 1, Status.UNVERIFIED: 2, Status.FAIL: 3}
    if not verdicts:
        return Status.UNVERIFIED
    return max((v.status for v in verdicts), key=lambda s: rank[s])


#: The floor `belay verify` enforces on `--replays`. The determinism classifier itself
#: only requires 2 (determinism.py), but its own docstring names 3 as the real floor: with
#: N=2 a genuinely nondeterministic tool whose two classification replays coincidentally
#: match (a coarse clock, both runs inside one second) is misread as DETERMINISTIC, which
#: on a DIVERGED reply becomes a FALSE FAIL. The verify surface refuses that. Below 3 also
#: covers N=1, which would otherwise reach the classifier and raise an uncaught ValueError
#: (a raw traceback instead of a clean error). One floor closes both.
_VERIFY_REPLAYS_FLOOR = 3


def _verify_replays(value: str) -> int:
    """An `--replays` value for `verify`, enforced `>= 3` with a clean argparse error."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < _VERIFY_REPLAYS_FLOOR:
        raise argparse.ArgumentTypeError(
            f"must be at least {_VERIFY_REPLAYS_FLOOR} (got {n}): with fewer replays a "
            f"nondeterministic tool can be misclassified as deterministic and FAILed falsely"
        )
    return n


def _cmd_corpus_add(args: argparse.Namespace) -> int:
    """`belay corpus add <trace> --turn N` — compose a self-contained case from a run.

    Recomputes the target turn's verdict by REAL re-execution (the same `verify_turn` the
    verify surface runs, with the same effective A1 policy), then bundles it into a case:
    the trace slice, the pre-state tree, the A1 policy, and the recomputed expected verdict.
    The human label is a PASS-THROUGH: `--label` sets it, and its ABSENCE stores `pending` —
    the engine never derives a label from the verdict it just computed. A malformed
    `--invariants` file is fail-closed (exit 2), matching `verify`.
    """
    from datetime import datetime, timezone

    from belay.corpus.add import add_case
    from belay.index import derive_correlation, tool_calls
    from belay.replay.reader import TraceCorrupt, read_trace
    from belay.verify.invariants import default_invariants, load_invariants
    from belay.verify.turn import verify_turn

    if not args.server:
        _emit("belay: a server command is required, after --server. Nothing to replay against.")
        return 2

    trace_path = Path(args.trace)
    if not trace_path.exists():
        _emit(f"belay: trace not found: {trace_path}")
        return 2

    # The A1 policy this case records — identical to verify: the defaults (unless dropped)
    # plus any operator file, fail-closed on a file that will not parse.
    invariants = [] if args.no_default_invariants else default_invariants()
    if args.invariants is not None:
        try:
            invariants = invariants + load_invariants(Path(args.invariants))
        except ValueError as exc:
            _emit(f"belay: {exc}")
            return 2

    try:
        read = read_trace(trace_path)
    except TraceCorrupt as exc:
        _emit(f"belay: {exc}")
        return 2

    records = list(read.records)
    total = len(tool_calls(derive_correlation(records)))
    if not (0 <= args.turn < total):
        _emit(f"belay: --turn {args.turn} out of range; the trace holds {total} tool call(s)")
        return 2

    manifest_dir = Path(args.manifest_dir)
    verdict = verify_turn(
        records, args.turn,
        server_command=args.server, manifest_dir=manifest_dir, replays=args.replays,
        invariants=invariants, timeout=args.timeout,
    )

    # The CLI is the boundary that may read the clock; `add_case` itself never does.
    captured_at = datetime.now(timezone.utc).isoformat()
    try:
        case_dir = add_case(
            Path(args.corpus_dir),
            records=records,
            target_turn_index=args.turn,
            verdict=verdict,
            manifest_dir=manifest_dir,
            server_command=list(args.server),
            invariants=invariants,
            human_label=args.label,
            replays=args.replays,
            timeout=args.timeout,
            source_trace_id=trace_path.stem,
            captured_at=captured_at,
        )
    except ValueError as exc:
        _emit(f"belay: {exc}")
        return 2

    _emit(f"belay corpus add: composed case {case_dir}")
    _emit(f"  turn {args.turn}  verdict {verdict.status.value}  label {args.label}")
    _emit("  A recomputed verdict and a HUMAN label — the label is 'pending' until a human")
    _emit("  relabels it; the engine never labels a case from its own verdict.")
    return 0


def _cmd_corpus_run(args: argparse.Namespace) -> int:
    """`belay corpus run [corpus_dir]` — re-verify every case; exit non-zero IFF a REGRESSION.

    Re-verifies every stored case against the live engine (the corpus IS the regression
    suite) and prints each case's outcome plus an aggregate. A REGRESSION shows its diverging
    axis/kind (expected -> got); a SKIP shows why the case could not be evaluated on this box.
    The exit is non-zero IFF at least one case REGRESSED — a run that is all MATCH/SKIP exits
    0, because a pure SKIP is partial coverage (a non-darwin box, an unavailable server), not
    a CI failure. The SKIP count is stated plainly so partial coverage is never mistaken for
    a clean full pass.
    """
    from belay.corpus.run import MATCH, REGRESSION, SKIP, run_corpus

    corpus_dir = Path(args.corpus_dir)
    if not corpus_dir.is_dir():
        _emit(f"belay: corpus directory not found: {corpus_dir}")
        return 2

    try:
        run = run_corpus(corpus_dir)
    except ValueError as exc:
        # A corrupt/unreadable case dir is fail-closed — never a silent skip.
        _emit(f"belay: {exc}")
        return 2

    _emit(f"belay corpus run {corpus_dir}")
    _emit()
    _emit(f"  {len(run.results)} case(s) re-verified by re-execution.")
    _emit()
    _emit("cases")
    for result in run.results:
        if result.outcome == REGRESSION:
            _emit(f"  {result.case_id:<32}{REGRESSION}")
            for div in result.divergences:
                where = div.kind if not div.axis else f"{div.axis} {div.kind}"
                _emit(f"      {where:<24}{div.expected_status} -> {div.got_status}")
        elif result.outcome == SKIP:
            _emit(f"  {result.case_id:<32}{SKIP}")
            _emit(f"      {result.skip_reason}")
        else:
            _emit(f"  {result.case_id:<32}{MATCH}")

    _emit()
    _emit("aggregate")
    _emit(f"  cases                 {len(run.results)}")
    _emit(f"  MATCH                 {run.matches}")
    _emit(f"  REGRESSION            {run.regressions}")
    _emit(f"  SKIP                  {run.skips}")

    _emit()
    if run.skips:
        _emit(
            f"  {run.skips} case(s) were SKIPPED — not evaluated on this box (off substrate, "
            f"server unavailable, or capability mismatch). Coverage here was PARTIAL; a SKIP "
            f"is never a pass and never a regression."
        )
    if run.has_regression:
        _emit(
            f"belay: {run.regressions} case(s) REGRESSED — a recorded verdict no longer "
            f"reproduces. The corpus is the regression suite; this is a real drift, not a "
            f"skip."
        )
        return 1
    _emit("belay: no regressions" + (f" ({run.skips} skipped)" if run.skips else ""))
    return 0


def _rate(value: Optional[float]) -> str:
    """A rate as a 2-decimal string, or the literal "n/a" for a `None` denominator.

    "n/a" is never rendered as "1.00" or "0.00": a rate with no cases under it is undefined,
    and printing a number there would manufacture a score the corpus never earned.
    """
    return "n/a" if value is None else f"{value:.2f}"


def _cmd_corpus_score(args: argparse.Namespace) -> int:
    """`belay corpus score [corpus_dir]` — precision, recall AND coverage vs HUMAN labels.

    Loads every case (fail-closed on a corrupt one) and scores the engine's stored verdicts
    against the human ground-truth labels: precision, recall, and — always beside them, never
    omitted — coverage, plus the confusion matrix and the excluded tallies. UNVERIFIED verdicts
    and `pending`/`unverifiable` labels are EXCLUDED from precision/recall by construction and
    reported on their own lines; an n/a rate is printed "n/a", never a fabricated 1.00. This is
    the number the Phase-0 gate publishes. It scores stored data — it does not replay.
    """
    from belay.corpus.case import CASE_FILENAME, load_case
    from belay.corpus.metrics import score

    corpus_dir = Path(args.corpus_dir)
    if not corpus_dir.is_dir():
        _emit(f"belay: corpus directory not found: {corpus_dir}")
        return 2

    case_dirs = sorted(p.parent for p in corpus_dir.glob(f"*/{CASE_FILENAME}"))
    cases = []
    for case_dir in case_dirs:
        try:
            cases.append(load_case(case_dir))
        except ValueError as exc:
            # A corrupt case is fail-closed, exactly as `corpus run` refuses to silently skip
            # one: a metric scored over a case that would not load is a metric over the wrong set.
            _emit(f"belay: {exc}")
            return 2

    m = score(cases)

    _emit(f"belay corpus score {corpus_dir}")
    _emit()
    _emit(f"  {m.total} case(s) scored against HUMAN labels (no replay — stored verdicts only).")
    _emit()
    _emit("confusion matrix (positive = engine FAIL; over decided verdict x adjudicable label)")
    _emit(f"  TP                    {m.tp}")
    _emit(f"  FP                    {m.fp}")
    _emit(f"  FN                    {m.fn}")
    _emit(f"  TN                    {m.tn}")
    _emit()
    _emit("metrics")
    _emit(f"  precision             {_rate(m.precision)}   TP/(TP+FP)")
    _emit(f"  recall                {_rate(m.recall)}   TP/(TP+FN)")
    _emit(f"  coverage              {_rate(m.coverage)}   decided / adjudicable")
    _emit()
    _emit("excluded (not scored in precision/recall — never folded in as PASS)")
    _emit(f"  UNVERIFIED verdict    {m.unverified}   engine could not decide; lowers coverage")
    _emit(f"  pending label         {m.pending}   not yet adjudicated by a human")
    _emit(f"  unverifiable label    {m.unverifiable}   no ground truth to score against")
    _emit()
    _emit("  Precision/recall are reported ONLY with coverage: a corpus can look perfect on the")
    _emit("  cases it decided while shrugging on the rest. An n/a rate means a 0 denominator —")
    _emit("  it is NOT a 1.00. UNVERIFIED and unadjudicated labels are excluded, never a PASS.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="belay", description="The agent harness.")
    subcommands = parser.add_subparsers(dest="group", required=True)

    sandbox = subcommands.add_parser("sandbox", help="the execution boundary").add_subparsers(
        dest="action", required=True
    )
    check = sandbox.add_parser(
        "check",
        help="does the substrate work here, and is the scope too tight for this server?",
        description=(
            "Probe the sandbox substrate on this machine, and optionally run a "
            "server briefly under the default scope to see what it is refused. "
            "This command can refute a scope; it cannot confirm one."
        ),
    )
    check.add_argument("--scope", required=True, help="the workspace the server may write to")
    check.add_argument(
        "--seconds",
        type=float,
        default=DEFAULT_SECONDS,
        help=f"how long to sample the server (default: {DEFAULT_SECONDS:g})",
    )
    check.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="-- server-command ...",
        help="the server to sample, after a bare --",
    )
    check.set_defaults(func=_cmd_sandbox_check)

    replay = subcommands.add_parser(
        "replay",
        help="replay a trace and report the UNVERIFIED rate, every instance named",
        description=(
            "Replay each recorded tools/call against its restored pre-state and "
            "report, per turn and in aggregate, what replayed, what was unverified "
            "(with a named cause) and what was not verifiable — plus the UNVERIFIED "
            "rate broken down by cause. This OBSERVES coverage; it emits no PASS/FAIL. "
            "\n\n"
            "Manifests: a turn's snapshot manifest is written by the gate to a SIBLING "
            "of the snapshot dir, e.g. BELAY_SNAPSHOT_DIR=./sn -> ./sn.manifests/. "
            "Point --manifest-dir there; a present turn whose manifest is not found is "
            "an honest UNVERIFIED (manifest not found), never a fabricated result."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    replay.add_argument("trace", help="the trace file (.jsonl) to replay")
    replay.add_argument(
        "--manifest-dir",
        required=True,
        help="where the gate persisted this run's snapshot manifests (the .manifests sibling)",
    )
    replay.add_argument(
        "--turn",
        type=int,
        default=None,
        help="replay only this tools/call turn (0-based); default is the whole trace",
    )
    replay.add_argument(
        "--replays",
        type=int,
        default=1,
        help="replay each turn this many times to classify determinism (>=2 to enable)",
    )
    replay.add_argument(
        "--server",
        nargs=argparse.REMAINDER,
        default=[],
        metavar="cmd ...",
        help="the MCP server to replay against; everything after --server is its command",
    )
    replay.set_defaults(func=_cmd_replay)

    verify = subcommands.add_parser(
        "verify",
        help="verify a whole trace by re-execution: per-turn A2 replay + A1 invariant verdict + aggregate",
        description=_VERIFY_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    verify.add_argument("trace", help="the trace file (.jsonl) to verify")
    verify.add_argument(
        "--manifest-dir",
        required=True,
        help="where the gate persisted this run's snapshot manifests (the .manifests sibling)",
    )
    verify.add_argument(
        "--turn",
        type=int,
        default=None,
        help="verify only this tools/call turn (0-based); default is the whole trace",
    )
    verify.add_argument(
        "--replays",
        type=_verify_replays,
        default=3,
        help="on a DIVERGED reply, re-invoke this many times to classify determinism (default: 3, minimum: 3)",
    )
    verify.add_argument(
        "--invariants",
        default=None,
        metavar="path",
        help=(
            "an operator-declared invariant file (JSON) to enforce as A1, on top of the "
            "defaults; a malformed file is a fail-closed error, never a silent skip"
        ),
    )
    verify.add_argument(
        "--no-default-invariants",
        action="store_true",
        help="do not apply the built-in default invariants (tests/ is read-only)",
    )
    verify.add_argument(
        "--server",
        nargs=argparse.REMAINDER,
        default=[],
        metavar="cmd ...",
        help="the MCP server to replay against; everything after --server is its command",
    )
    verify.set_defaults(func=_cmd_verify)

    corpus = subcommands.add_parser(
        "corpus", help="the failure corpus: labeled, replayable cases from flagged runs"
    ).add_subparsers(dest="action", required=True)
    corpus_add = corpus.add_parser(
        "add",
        help="compose a self-contained, labeled case from one flagged turn of a trace",
        description=(
            "Recompute one tools/call turn's verdict by RE-EXECUTION (the same verify_turn "
            "the verify surface runs, with the same effective A1 policy) and bundle it into "
            "a SELF-CONTAINED corpus case: the trace, the pre-state tree (copied in, so the "
            "case survives deletion of the original run), the A1 policy, and the recomputed "
            "expected verdict. A later `corpus run` re-replays the case and asserts it still "
            "reaches this verdict.\n\n"
            "The human label is a PASS-THROUGH: --label sets it, and its ABSENCE stores "
            "'pending'. The engine NEVER derives a label from the verdict it just computed — "
            "a case is labeled true/false-positive by a HUMAN, later, not by the engine that "
            "flagged it. That separation is what keeps the corpus's precision honest.\n\n"
            "Manifests: point --manifest-dir at the gate's .manifests sibling, as with verify."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    corpus_add.add_argument("trace", help="the trace file (.jsonl) the flagged turn is in")
    corpus_add.add_argument(
        "--turn",
        type=int,
        required=True,
        help="the tools/call turn (0-based) to compose a case from",
    )
    corpus_add.add_argument(
        "--manifest-dir",
        required=True,
        help="where the gate persisted this run's snapshot manifests (the .manifests sibling)",
    )
    corpus_add.add_argument(
        "--corpus-dir",
        default="corpus",
        help="the corpus directory the case is written under (default: ./corpus)",
    )
    corpus_add.add_argument(
        "--label",
        choices=["true-positive", "false-positive", "unverifiable"],
        default="pending",
        help=(
            "the HUMAN ground-truth label for this case; omit it and the case is stored "
            "'pending' for a human to relabel. The engine never labels from its own verdict."
        ),
    )
    corpus_add.add_argument(
        "--invariants",
        default=None,
        metavar="path",
        help=(
            "an operator-declared invariant file (JSON) to enforce as A1 when recomputing "
            "the verdict, on top of the defaults; a malformed file is a fail-closed error"
        ),
    )
    corpus_add.add_argument(
        "--no-default-invariants",
        action="store_true",
        help="do not apply the built-in default invariants (tests/ is read-only)",
    )
    corpus_add.add_argument(
        "--replays",
        type=_verify_replays,
        default=3,
        help="on a DIVERGED reply, re-invoke this many times to classify determinism (min 3)",
    )
    corpus_add.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"per-replay timeout in seconds recorded on the case (default: {DEFAULT_TIMEOUT:g})",
    )
    corpus_add.add_argument(
        "--server",
        nargs=argparse.REMAINDER,
        default=[],
        metavar="cmd ...",
        help="the MCP server to replay against; everything after --server is its command",
    )
    corpus_add.set_defaults(func=_cmd_corpus_add)

    corpus_run = corpus.add_parser(
        "run",
        help="re-verify every stored case and assert it still reaches its recorded verdict",
        description=(
            "Re-verify every case in the corpus against the live engine and assert each still "
            "reaches its recorded verdict. The corpus IS the regression suite: a case that no "
            "longer reproduces its per-sub-verdict SET (not merely its reduced status) is a "
            "caught detector DRIFT, and the run exits NON-ZERO.\n\n"
            "A SKIP is kept distinct from a REGRESSION and is never a pass: a case this box "
            "cannot evaluate — off the macOS Seatbelt substrate, the recorded server not "
            "runnable, a backend capability mismatch on restore — is SKIPPED, not failed, so "
            "the corpus does not fail CI on every non-darwin box. The run exits non-zero IFF "
            "at least one case REGRESSED; an all-MATCH/SKIP run exits 0 with its SKIP count "
            "stated plainly."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    corpus_run.add_argument(
        "corpus_dir",
        nargs="?",
        default="corpus",
        help="the corpus directory of case dirs to re-verify (default: ./corpus)",
    )
    corpus_run.set_defaults(func=_cmd_corpus_run)

    corpus_score = corpus.add_parser(
        "score",
        help="precision, recall AND coverage of the stored verdicts against HUMAN labels",
        description=(
            "Score the corpus: how well do the engine's STORED verdicts match the HUMAN "
            "ground-truth labels? Prints precision, recall, and — always beside them, never "
            "alone — coverage, plus the TP/FP/FN/TN matrix and the excluded tallies. This "
            "reads each case's recorded verdict and label; it does NOT replay (that is "
            "`corpus run`).\n\n"
            "Two exclusions are load-bearing and by construction: an UNVERIFIED verdict is "
            "NEVER folded into PASS — it is excluded from precision/recall and lowers "
            "coverage; a `pending` or `unverifiable` label has no ground truth and is "
            "excluded too. The engine's own verdict can never stand in for a human label, so "
            "precision cannot be inflated to 1.0 by counting every FAIL as a hit. A rate with "
            "a 0 denominator prints 'n/a', never a fabricated 1.00."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    corpus_score.add_argument(
        "corpus_dir",
        nargs="?",
        default="corpus",
        help="the corpus directory of case dirs to score (default: ./corpus)",
    )
    corpus_score.set_defaults(func=_cmd_corpus_score)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    command = getattr(args, "command", None)
    if command and command[0] == "--":
        args.command = command[1:]
    # `--server` also captures a leading bare `--` when a user writes `--server -- cmd`.
    server = getattr(args, "server", None)
    if server and server[0] == "--":
        args.server = server[1:]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
