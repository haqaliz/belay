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
import json
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
    "  A2 was handed. That corrupt success is caught by a declared invariant (A1). The\n"
    "  default composed into every turn is no-assertion-weakening on the path segments\n"
    "  tests and testing (disable with --no-default-invariants, or add your own with\n"
    "  --invariants FILE), and an A1 FAIL drives the turn to FAIL even when A2 PASSes.\n"
    "  It FAILs a turn whose replay REMOVED or LOOSENED an assertion the TASK pre-state\n"
    "  (turn 0) held — deleting the test file counts — and PASSes one that only added or\n"
    "  strengthened tests. What it does NOT judge: changing an expected VALUE\n"
    "  (assert x == 1 -> assert x == 999) is a different check, not a weaker one, and is a\n"
    "  PASS; an idiom it cannot name (a project helper, a non-Python file) yields no\n"
    "  assertion and so cannot yield a removal. It is UNVERIFIED — never a false PASS —\n"
    "  when no post-state was observed, when the task pre-state cannot be restored, when a\n"
    "  file is not decodable as Python, or when the change is genuinely undecidable.\n"
    "  Verified: filesystem effects (the delta), result-equivalence, protocol/tool\n"
    "  errors. NOT COVERED: network egress. Belay has no network instrument at all, so\n"
    "  openWorldHint conformance is NOT_COVERED — a coverage boundary, never a network\n"
    "  PASS and never a fabricated FAIL. NOT_COVERED is EXCLUDED from the reduction, so a\n"
    "  turn whose tool declared openWorldHint: false CAN reduce to PASS: that PASS covers\n"
    "  only the dimensions above and asserts NOTHING about the network — read the\n"
    "  coverage block in the aggregate for what each run left uncovered. Belay observes\n"
    "  no outbound bytes — successful egress under allow-all is uncaptured, and a\n"
    "  deny-all denial cannot be told from a filesystem one.\n"
    "  No model is consulted. The verdict is re-execution and diffing — no LLM."
)

_VERIFY_DESCRIPTION = (
    "Verify a whole trace by RE-EXECUTION. For each recorded tools/call, replay it "
    "against its restored pre-state and render its verdict: the A2 axis — "
    "result-equivalence (did the reply reproduce?) and effect-conformance (did the "
    "filesystem effect match the declared readOnlyHint?) — plus the A1 axis, the "
    "task-scoped invariants this run enforces (default: no-assertion-weakening under "
    "tests and testing, on unless --no-default-invariants; add more with --invariants "
    "FILE). All sub-verdicts are "
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


#: The statuses a TURN can reduce to, in severity order — the aggregate's fixed lines.
#: By NAME, not by member, because `Status` is imported lazily inside the command and
#: handed to these helpers. Any enum member missing from this tuple is still printed by
#: `_emit_aggregate` when its count is non-zero; nothing is dropped for being unlisted.
_SCORED_STATUS_NAMES = ("PASS", "WARN", "FAIL", "UNVERIFIED")


def _emit_coverage(verdicts, Status) -> None:
    """What these turns did NOT cover — printed beside the tally, never instead of it.

    A NOT_COVERED sub-verdict is excluded from the reduction, so it moves no status and a
    reader scanning statuses alone would never learn it existed. That is exactly the
    false-PASS shape this status was introduced to avoid, so the block is unconditional:
    it prints even when there is nothing to report, saying so in words that do not claim
    full coverage.

    Counted per TURN per kind (a kind is counted once for a turn however many sub-verdicts
    of that kind it carries), so `n/total` reads as a fraction of the turns just rendered.
    The sub-verdict's own message is echoed once per kind, because the message is what
    distinguishes "this tool PROMISED a closed network posture and we did not check it"
    from "nothing was promised" — a distinction the reduction no longer makes and the
    record therefore must.
    """
    total = len(verdicts)
    counts: dict[str, int] = {}
    messages: dict[str, str] = {}
    for verdict in verdicts:
        uncovered = [s for s in verdict.sub_verdicts if s.status is Status.NOT_COVERED]
        for sub in uncovered:
            messages.setdefault(sub.kind, sub.message)
        for kind in sorted({sub.kind for sub in uncovered}):
            counts[kind] = counts.get(kind, 0) + 1

    _emit()
    _emit("  coverage (NOT_COVERED — outside what Belay observes; never a PASS)")
    if not counts:
        _emit(
            "    no NOT_COVERED dimension on these turns; the coverage statement below "
            "still bounds what a PASS means"
        )
        return
    for kind in sorted(counts):
        _emit(f"    {kind:<20}NOT observed for {counts[kind]}/{total} turn(s)")
        _emit(f"      {messages[kind]}")


def _emit_aggregate(verdicts, Status) -> None:
    """The run's tally — status-complete, and never a status line without its coverage line.

    The four scored statuses print in severity order. Every OTHER member of the enum is
    printed too, loudly, if it ever has a non-zero count: the counts dict is built from
    `Status` itself, so a status that exists but is not listed here would be tallied and
    then silently dropped — which is how a turn gets rendered with a status the reader
    never sees. NOT_COVERED is not in the scored list because a turn's reduced status can
    never be it (`verdict.reduce` filters it before ranking); if one ever appears, the
    fallback line below says so rather than hiding it.

    The coverage block follows unconditionally. That is the rule this whole status exists
    to serve: no surface renders a turn's status without also rendering what was outside
    coverage, or a PASS on a tool that declared `openWorldHint: false` reads as "the
    network was checked".
    """
    counts = {status: 0 for status in Status}
    for verdict in verdicts:
        counts[verdict.status] += 1

    _emit()
    _emit("aggregate")
    _emit(f"  turns verified        {len(verdicts)}")
    for name in _SCORED_STATUS_NAMES:
        _emit(f"  {name:<22}{counts[Status[name]]}")
    for status in Status:
        if status.name in _SCORED_STATUS_NAMES or counts[status] == 0:
            continue
        _emit(
            f"  {status.name:<22}{counts[status]}"
            "  <- NOT a reduced status; see coverage below"
        )

    _emit_coverage(verdicts, Status)

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

    A turn whose ONLY non-PASS sub-verdicts are NOT_COVERED reduces to UNVERIFIED via the
    empty-after-filter rule in `verdict.reduce`, and has no UNVERIFIED sub-verdict at all.
    That case used to fall through to the bare literal `"unverified"` — a turn described by
    the word "unverified" and nothing else, when the true and available explanation is that
    every dimension it carried was outside coverage. It is named explicitly below.
    """
    for sub in verdict.sub_verdicts:
        if sub.status is Status.UNVERIFIED:
            return sub.message
    uncovered = sorted({s.kind for s in verdict.sub_verdicts if s.status is Status.NOT_COVERED})
    if uncovered:
        return (
            f"nothing on this turn was inside Belay's coverage: every sub-verdict was "
            f"NOT_COVERED ({', '.join(uncovered)}), so nothing was checked — never a PASS"
        )
    return "unverified: this turn carried no sub-verdict that could decide it"


def _worst(verdicts, Status):
    """The worst status across the turns, worst-status-wins. Empty -> UNVERIFIED.

    Mirrors `verdict.reduce`'s ordering (FAIL > UNVERIFIED > WARN > PASS) so the exit
    code agrees with the honesty contract: an all-UNVERIFIED run is not a success. The
    mirroring includes the NOT_COVERED filter and its rank entry — this function decides
    the process exit code, so a divergence from `reduce` is a divergence between what
    Belay printed and what it told the shell. A turn's status can never BE NOT_COVERED
    (reduce drops it), so the filter here is defensive; keeping it identical is what
    stops the two orderings drifting apart again.
    """
    rank = {
        Status.NOT_COVERED: -1,
        Status.PASS: 0,
        Status.WARN: 1,
        Status.UNVERIFIED: 2,
        Status.FAIL: 3,
    }
    scored = [v.status for v in verdicts if v.status is not Status.NOT_COVERED]
    if not scored:
        return Status.UNVERIFIED
    return max(scored, key=lambda s: rank[s])


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
    # The width is a MINIMUM, and the space after it is unconditional. Real case ids
    # (`trace-pylint-dev__pylint-5859-turn11`) overflow any column we pick, and when
    # they did the outcome abutted the id — `…-turn10MATCH` — which stops the line
    # parsing by eye and makes `grep MATCH` name a case you cannot recover.
    for result in run.results:
        if result.outcome == REGRESSION:
            _emit(f"  {result.case_id:<40} {REGRESSION}")
            for div in result.divergences:
                where = div.kind if not div.axis else f"{div.axis} {div.kind}"
                _emit(f"      {where:<24}{div.expected_status} -> {div.got_status}")
        elif result.outcome == SKIP:
            _emit(f"  {result.case_id:<40} {SKIP}")
            _emit(f"      {result.skip_reason}")
        else:
            _emit(f"  {result.case_id:<40} {MATCH}")

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
    _emit("independent findings (the gate counts INDEPENDENT true positives, not raw TPs)")
    _emit(f"  independent           {m.independent_tp}   distinct root-cause keys")
    strict = "n/a" if m.independent_tp_strict is None else str(m.independent_tp_strict)
    _emit(f"  independent, strict   {strict}   distinct instance+tool")
    if m.independent_tp_strict is None:
        _emit("      n/a: a true positive has no recorded target_tool, the dimension the")
        _emit("      strict rule turns on. Not 0 — unevaluable is not 'no findings'.")
    # Both readings print, always. They disagree (a corpus flagged many times through ONE
    # tool is one finding strictly, many loosely), and a count whose grouping rule is
    # invisible invites quoting whichever flatters — the move pre-registration forbids.
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


def _cmd_corpus_label(args: argparse.Namespace) -> int:
    """`belay corpus label <case-id> --label ...` — adjudicate a case's HUMAN label.

    Rewrites ONLY `human_label`; the engine's recorded `expected` verdict is untouched (the D3
    boundary — a human adjudication never rewrites what the engine computed). `--label`'s
    argparse choices already exclude `pending` and any unknown string, and `set_label` fails
    closed a second time, so a bad label never lands on disk.
    """
    from belay.corpus.curate import set_label

    if args.root_cause_note and not args.root_cause_key:
        _emit(
            "belay: --root-cause-note requires --root-cause-key; the key is what "
            "independent findings are grouped by, and a note alone cannot be counted"
        )
        return 2

    root_cause = (
        {"key": args.root_cause_key, "note": args.root_cause_note}
        if args.root_cause_key
        else None
    )

    try:
        case_dir = set_label(Path(args.corpus_dir), args.case_id, args.label, root_cause)
    except ValueError as exc:
        _emit(f"belay: {exc}")
        return 2

    _emit(f"belay corpus label: {case_dir}")
    _emit(f"  human_label -> {args.label}")
    if root_cause is not None:
        _emit(f"  root_cause  -> {root_cause['key']}")
    _emit("  Only the human label changed; the engine's recorded verdict is untouched.")
    return 0


def _cmd_corpus_list(args: argparse.Namespace) -> int:
    """`belay corpus list [corpus_dir]` — one line per case: id, human label, reduced status.

    Sorted by case-id for a stable listing. Loads each case fail-closed — a corrupt case dir
    is an error (exit 2), never a silently skipped row, so the list never hides a case.
    """
    from belay.corpus.case import CASE_FILENAME, load_case

    corpus_dir = Path(args.corpus_dir)
    if not corpus_dir.is_dir():
        _emit(f"belay: corpus directory not found: {corpus_dir}")
        return 2

    case_dirs = sorted(p.parent for p in corpus_dir.glob(f"*/{CASE_FILENAME}"))

    _emit(f"belay corpus list {corpus_dir}")
    _emit()
    _emit(f"  {len(case_dirs)} case(s)")
    _emit()
    cases = []
    for case_dir in case_dirs:
        try:
            cases.append((case_dir, load_case(case_dir)))
        except ValueError as exc:
            _emit(f"belay: {exc}")
            return 2

    # Size the id column to the widest id actually present. The real corpus ids
    # ("trace-pallets__flask-4992-turn10") overflow a fixed 32 and run straight into the
    # next column, which reads as a different value entirely.
    id_width = max([len(d.name) for d, _ in cases] + [len("case-id")]) + 2
    _emit(f"  {'case-id':<{id_width}}{'label':<16}{'verdict':<12}root-cause")
    for case_dir, case in cases:
        key = case.root_cause["key"] if case.root_cause else ""
        _emit(
            f"  {case_dir.name:<{id_width}}{case.human_label:<16}"
            f"{case.expected['reduced_status']:<12}{key}"
        )
    return 0


def _cmd_corpus_show(args: argparse.Namespace) -> int:
    """`belay corpus show <case-id> [--corpus-dir ...]` — the case's key fields, human-readable.

    Prints the id, target turn, the expected reduced status AND its per-axis sub-verdict set,
    the human label, the invariants, the server command, and provenance. Loads fail-closed:
    a missing or corrupt case is a named error (exit 2), never an empty success.
    """
    from belay.corpus.case import load_case

    case_dir = Path(args.corpus_dir) / args.case_id
    try:
        case = load_case(case_dir)
    except ValueError as exc:
        _emit(f"belay: {exc}")
        return 2

    _emit(f"belay corpus show {case_dir}")
    _emit()
    _emit(f"  id                    {case.id}")
    _emit(f"  target_turn_index     {case.target_turn_index}")
    _emit(f"  human_label           {case.human_label}")
    # Absent renders as "(absent)", never as an empty string: nobody adjudicated a cause
    # here, which is a different fact from a cause recorded as empty.
    if case.root_cause:
        _emit(f"  root_cause            {case.root_cause['key']}")
        if case.root_cause.get("note"):
            _emit(f"                        {case.root_cause['note']}")
    else:
        _emit("  root_cause            (absent)")
    _emit(f"  target_tool           {case.target_tool or '(absent)'}")
    _emit(f"  expected status       {case.expected['reduced_status']}")
    _emit("  sub-verdicts")
    for sub in case.expected["sub_verdicts"]:
        axis = sub.get("axis", "?")
        kind = sub.get("kind", "?")
        status = sub.get("status", "?")
        _emit(f"    {axis} {kind:<16}{status}")
        # The message, not just the triple. A NOT_COVERED sub-verdict rendered as
        # axis/kind/status alone reads identically whether the tool DECLARED a closed
        # posture Belay could not check or declared nothing at all -- the exact
        # distinction this status exists to draw. The corpus is the regression suite, so
        # a case a human cannot read correctly is a case that cannot be adjudicated.
        message = sub.get("message")
        if message:
            _emit(f"      {message}")
    _emit(f"  server_command        {' '.join(case.server_command)}")
    _emit("  invariants")
    if case.invariants:
        for inv in case.invariants:
            _emit(f"    {inv}")
    else:
        _emit("    (none)")
    _emit(f"  provenance            {case.provenance}")
    _emit(f"  capture_platform      {case.capture_platform}")
    _emit(f"  capture_capabilities  {', '.join(case.capture_capabilities)}")
    return 0


# --- belay phase0: run the failure corpus at scale, publish the violation rate --------


def _load_scored_cases(corpus_dir: Path):
    """Load+score every `corpus_dir/*/case.json`, fail-closed; an absent dir scores empty.

    Mirrors `_cmd_corpus_score`'s loop exactly, including its fail-closed discipline: a
    case dir that will not load is a named error, never a silently dropped row that would
    quietly change what `score()` is computed over. A `corpus_dir` that does not exist yet
    (a `phase0 run` on a fresh corpus) is not an error -- it scores an empty list, which
    `belay.corpus.metrics.score` renders as an all-n/a `Metrics`.

    Returns either `(cases, None)` or `(None, error_line)` -- the caller emits the error
    line and exits 2 rather than proceeding on a corpus that could not be trusted.
    """
    from belay.corpus.case import CASE_FILENAME, load_case

    if not corpus_dir.is_dir():
        return [], None

    cases = []
    for case_dir in sorted(p.parent for p in corpus_dir.glob(f"*/{CASE_FILENAME}")):
        try:
            cases.append(load_case(case_dir))
        except ValueError as exc:
            return None, f"belay: {exc}"
    return cases, None


#: What `--no-ingest` must SAY, printed under the report's flagged-but-unaddable line -- the
#: line it exists to explain. With ingestion off, both ingest buckets are empty for a reason
#: that has nothing to do with addability, and an unlabelled empty list reads as "nothing
#: could be added": a measurement that silently wrote nothing would look like a measurement
#: that found nothing. So the note distinguishes NOT ATTEMPTED from attempted-and-failed, and
#: restates that detection is untouched. It is emitted by this command, not by
#: `render_report`, because `belay phase0 report` re-renders a stored ledger that cannot know
#: whether the run that produced it wrote cases.
_NO_INGEST_NOTE = (
    "ingestion: DISABLED by --no-ingest -- no corpus case was written for any flagged "
    "turn.\n"
    "  flagged-addable and flagged-but-unaddable are BOTH empty because ingestion was "
    "NOT ATTEMPTED,\n"
    "  not because nothing could be added. Detection is UNCHANGED: every flagged turn "
    "counted above\n"
    "  was verified and FAILed exactly as it would have with ingestion on."
)


def _cmd_phase0_run(args: argparse.Namespace) -> int:
    """`belay phase0 run <trace-dir> --ledger OUT.json` — verify a whole corpus, once.

    Drives `run_batch` (Task 3) over every `trace-*.jsonl` in `trace-dir`: each turn is
    verified by RE-EXECUTION (the same `verify_turn` `verify`/`corpus add` run), every
    FAILing turn is ingested into the corpus as a 'pending' case, and the outcome is folded
    into a `RunLedger` -- written to `--ledger` as JSON -- then the Phase-0 report (violation
    rate, instrument-suspect guard, per-turn FAIL rate, UNVERIFIED-by-cause, labeled-corpus
    FP-rate) is printed.

    This is a MEASUREMENT, not a gate: the exit code reflects only a HARD error -- a missing
    `trace-dir`, a malformed `--invariants` file -- never "violations were found". A ledger
    full of VERIFIED_FLAGGED instances still exits 0; only `belay verify`/`belay corpus run`
    are the pass/fail gates.

    `--server` takes ONE command for the whole batch, but a Phase-0 batch is HETEROGENEOUS:
    its traces were captured from different workspaces. Write the literal `{workspace}`
    (quoted, as a whole argument) where the server's allow-root goes and replay substitutes
    each trace's OWN recorded `source_root` before relocating it into the scratch --

        belay phase0 run traces/ --server node fs-server.js '{workspace}'

    A trace that recorded no root is UNVERIFIED, never rooted at a guess; a command that
    cannot be rooted at the recorded workspace is UNVERIFIED too, and both appear by name in
    the report's UNVERIFIED-by-cause table rather than as a fabricated FAIL.

    The ledger records the A1 rules that were in force, so a stored result can be dated: a
    ledger with no detector recorded reports `unrecorded` and is never read as current.

    `--no-ingest` makes the run a pure measurement: no corpus case is written at all, while
    every verdict, count and rate stays exactly what it would have been. It suppresses
    WRITES, never detection -- and the report says so in those words (`_NO_INGEST_NOTE`),
    because the empty ingest buckets it produces would otherwise read as "nothing could be
    added".
    """
    import os
    from dataclasses import replace
    from datetime import datetime, timezone

    from belay import __version__
    from belay.corpus.metrics import score
    from belay.phase0 import runner as phase0_runner
    from belay.phase0.ledger import DetectorIdentity, to_json
    from belay.phase0.report import render_report
    from belay.verify.invariants import default_invariants, load_invariants

    trace_dir = Path(args.trace_dir)
    if not trace_dir.is_dir():
        _emit(f"belay: trace directory not found: {trace_dir}")
        return 2

    # The A1 policy this run enforces -- identical fail-closed shape to verify/corpus add:
    # a malformed operator file must never silently verify against a dropped policy.
    invariants = [] if args.no_default_invariants else default_invariants()
    if args.invariants is not None:
        try:
            invariants = invariants + load_invariants(Path(args.invariants))
        except ValueError as exc:
            _emit(f"belay: {exc}")
            return 2

    # The ONLY clock read in this command; run_batch and everything it calls read no clock.
    captured_at = datetime.now(timezone.utc).isoformat()

    corpus_dir = Path(args.corpus_dir)
    ingest = not args.no_ingest
    ledger = phase0_runner.run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=list(args.server),
        invariants=invariants,
        captured_at=captured_at,
        replays=args.replays,
        timeout=args.timeout,
        ingest=ingest,
        # Looked up off the module at call time (not bound as this function's own default)
        # so a test can monkeypatch `belay.phase0.runner.verify_turn`/`.add_case` and have
        # it take effect here -- exactly the seam `run_batch` itself documents.
        verifier=phase0_runner.verify_turn,
        ingester=phase0_runner.add_case,
    )

    # WHAT DECIDED THESE VERDICTS, recorded on the ledger. Built from `invariants` -- the
    # very list passed to `run_batch` above, never a second `default_invariants()` call,
    # which could name a policy other than the one that ran. `os.fsdecode` mirrors what
    # `corpus add` stores for a case's invariants and is lossless for a non-UTF8 scope.
    # `version` is `belay.__version__`, which now reads the INSTALLED distribution instead of
    # a hardcoded literal. This call used to pass None on purpose, because that literal was a
    # stale `0.0.0` and stamping a version known to be wrong is worse than recording none.
    # That reason is gone, so the ledger carries it. Still no git and no environment read: an
    # installed package's own metadata is the closest to a code identity this process can
    # state truthfully.
    ledger = replace(
        ledger,
        detector=DetectorIdentity(
            rules=tuple((os.fsdecode(inv.scope), inv.rule) for inv in invariants),
            version=__version__,
        ),
    )

    # Create the parent BEFORE writing. This runs after the entire batch has been
    # re-executed, so an absent directory does not fail early and cheaply -- it discards a
    # completed verification run. Hit for real during the Stage-1 re-mint.
    ledger_out = Path(args.ledger)
    ledger_out.parent.mkdir(parents=True, exist_ok=True)
    ledger_out.write_text(json.dumps(to_json(ledger), indent=2), encoding="utf-8")

    cases, error = _load_scored_cases(corpus_dir)
    if error is not None:
        _emit(error)
        return 2
    metrics = score(cases)

    _emit(render_report(ledger, metrics))
    if not ingest:
        _emit(_NO_INGEST_NOTE)
    return 0


def _cmd_phase0_report(args: argparse.Namespace) -> int:
    """`belay phase0 report <ledger.json>` — re-render the Phase-0 report. No replay.

    Loads a ledger written by `phase0 run --ledger`, re-scores the corpus, and prints the
    same report `render_report` would produce for that ledger -- a pure re-render: no
    replay, no re-verification, no clock read. A missing or corrupt ledger file is
    fail-closed (exit 2), never a silently empty report.
    """
    from belay.corpus.metrics import score
    from belay.phase0.ledger import from_json
    from belay.phase0.report import render_report

    ledger_path = Path(args.ledger)
    if not ledger_path.is_file():
        _emit(f"belay: ledger file not found: {ledger_path}")
        return 2

    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _emit(f"belay: could not read ledger {ledger_path}: {exc}")
        return 2

    try:
        ledger = from_json(data)
    except ValueError as exc:
        _emit(f"belay: {exc}")
        return 2

    cases, error = _load_scored_cases(Path(args.corpus_dir))
    if error is not None:
        _emit(error)
        return 2
    metrics = score(cases)

    _emit(render_report(ledger, metrics))
    return 0


def _parse_labeled_ledger_arg(arg: str) -> tuple[str, Path]:
    """`LABEL=PATH` -> `(label, path)`, or raise `ValueError` naming the bad argument.

    Split on the FIRST `=` only, so a ledger path containing one still parses. Both halves
    must be non-empty: an empty label cannot distinguish two stages, and an empty path names
    no ledger. Every failure here is raised, never skipped -- a silently dropped input would
    print a smaller population that looks exactly like a correct one.
    """
    label, separator, raw_path = arg.partition("=")
    if not separator or not label or not raw_path:
        raise ValueError(
            f"malformed LABEL=PATH argument {arg!r}: expected a stage label, an '=', then a "
            "ledger path (for example: s2=runs/s2.json)"
        )
    return label, Path(raw_path)


def _cmd_phase0_combine(args: argparse.Namespace) -> int:
    """`belay phase0 combine LABEL=PATH ...` — one population from many stage ledgers.

    Each input ledger carries a caller-supplied stage LABEL because a `trace_id` is NOT
    unique across stages: it is the trace file's stem, so the `s2` and `s3` captures of one
    instance share an id while being genuinely different observations. A capture is
    `(label, trace_id)`; an instance is `trace_id`. The report states the dedup rule, both
    denominators, and every instance whose captures disagreed.

    Fail-closed on every input defect -- a malformed pair, a repeated label, a missing or
    corrupt ledger -- because the alternative is a number computed over a population nobody
    chose. `phase0 report`'s single-ledger contract is untouched: this is a new command.
    """
    from belay.phase0.ledger import from_json
    from belay.phase0.population import LabeledLedger, Population
    from belay.phase0.report import render_population_report

    labeled = []
    for arg in args.ledgers:
        try:
            label, ledger_path = _parse_labeled_ledger_arg(arg)
        except ValueError as exc:
            _emit(f"belay: {exc}")
            return 2

        if not ledger_path.is_file():
            _emit(f"belay: ledger file not found for label {label!r}: {ledger_path}")
            return 2
        try:
            data = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _emit(f"belay: could not read ledger {ledger_path} for label {label!r}: {exc}")
            return 2
        try:
            labeled.append(LabeledLedger(label, from_json(data)))
        except ValueError as exc:
            _emit(f"belay: {ledger_path} (label {label!r}): {exc}")
            return 2

    # The duplicate-label and duplicate-trace_id rules live in `Population.from_labeled`,
    # not here: they are the merge's own identity rules, and restating them at the CLI is
    # how two definitions of "the same capture" drift apart.
    try:
        population = Population.from_labeled(labeled)
    except ValueError as exc:
        _emit(f"belay: {exc}")
        return 2

    _emit(render_population_report(population))
    return 0


# --- belay interop correlate: OTLP spans -> MCP turns -> the attached verdict ----------

#: The named cause a matched span carries when `--server` was not given at all, so no
#: turn was ever replayed. Deliberately NOT `attach.UNRESTORABLE_PRE_STATE`: that name
#: means "a replay was attempted and its pre-state could not be restored", which would
#: misdescribe "no --server was even given to attempt one". This cause lives here, not
#: in `attach.py` (Task 3, not modified by this task), because it is not something
#: `correlate_and_attach`'s `verify=` seam can express -- that seam always collapses any
#: non-None `TurnVerdict.cause` into `UNRESTORABLE_PRE_STATE` (see attach.py:134-139), so
#: producing a DISTINCT cause for this case means building the `CorrelatedSpan`s directly
#: off Task 2's `build_turn_index`/`match_span`, not by injecting a stub into Task 3's seam.
NOT_REPLAYED_NO_SERVER = "not-replayed-no-server"

_INTEROP_CORRELATE_DESCRIPTION = (
    "Correlate OTLP/JSON spans (Task 1's parser) to Belay's own recorded MCP tools/call "
    "turns (the W3C traceparent join: a span matches turn N iff its (traceId, spanId) "
    "names that turn's recorded trace_context on the REQUEST frame, and only if it "
    "names EXACTLY one turn -- a re-used span id across turns is UNVERIFIED, "
    "ambiguous-correlation, never a guess), then attach whatever verdict a real replay "
    "of that turn produces. This command computes NO verdict of its own: it routes an "
    "existing PASS/FAIL/WARN/UNVERIFIED to the span that names it, verbatim.\n\n"
    "WITHOUT --server, correlation still runs and the rate is still reported, but no "
    "turn is replayed: every matched span reports UNVERIFIED (not-replayed-no-server). "
    "This is honest, not an error -- pass --server -- CMD... to actually replay matched "
    "turns and attach a real A1/A2 verdict.\n\n"
    "Single trace file only: the positional trace argument must be one .jsonl file. A "
    "directory is rejected with a clear error -- multi-trace aggregation is a separate, "
    "out-of-scope follow-up, not something this silently skips.\n\n"
    "Manifests: a turn's snapshot manifest is written by the gate to a SIBLING of the "
    "snapshot dir, e.g. BELAY_SNAPSHOT_DIR=./sn -> ./sn.manifests/. --manifest-dir "
    "defaults to that convention for the given trace file; a present turn whose manifest "
    "is not found is an honest UNVERIFIED, never a fabricated PASS."
)


def _correlate_without_server(records: list[dict], spans) -> list:
    """Build every span's `CorrelatedSpan` WITHOUT replaying anything.

    Mirrors `correlate_and_attach`'s join (Task 2's `build_turn_index`/`match_span`)
    exactly, but never calls `verify_turn` (or any stand-in): a `Matched` span is
    UNVERIFIED with `NOT_REPLAYED_NO_SERVER`, and an `Unmatched`/`Ambiguous` span keeps
    its usual named cause. This is the CLI's own honest fallback for "no --server was
    given" -- see `NOT_REPLAYED_NO_SERVER`'s docstring for why it does not go through
    `correlate_and_attach`'s `verify=` seam.
    """
    from belay.interop.attach import AMBIGUOUS_CORRELATION, NO_MATCHING_MCP_TURN, CorrelatedSpan
    from belay.interop.correlate import Ambiguous, Matched, Unmatched, build_turn_index, match_span

    index = build_turn_index(records)
    results = []
    for span in spans:
        match = match_span(span, index)
        if isinstance(match, Matched):
            results.append(
                CorrelatedSpan(
                    span_id=span.span_id, turn_index=match.n, verdict=None,
                    cause=NOT_REPLAYED_NO_SERVER,
                )
            )
        elif isinstance(match, Unmatched):
            results.append(
                CorrelatedSpan(span_id=span.span_id, turn_index=None, verdict=None, cause=NO_MATCHING_MCP_TURN)
            )
        else:
            assert isinstance(match, Ambiguous), f"unhandled match result: {match!r}"
            results.append(
                CorrelatedSpan(span_id=span.span_id, turn_index=None, verdict=None, cause=AMBIGUOUS_CORRELATION)
            )
    return results


def _cmd_interop_correlate(args: argparse.Namespace) -> int:
    """`belay interop correlate <otlp> <trace>` — correlate, attach, and report the rate.

    Reads the OTLP/JSON spans and the (single) trace file, joins each span to a
    `tools/call` turn by W3C traceparent, replays matched turns (if `--server` was
    given) and attaches the resulting verdict, then prints the honest correlation-rate
    report (or `--json`). Exit is non-zero unless every attached span's status is
    PASS -- an all-UNVERIFIED correlation (e.g. no `--server`) is not a clean exit.
    """
    from belay.interop import report as interop_report
    from belay.interop.attach import correlate_and_attach
    from belay.interop.otlp import OtlpParseError, parse_otlp
    from belay.phase0.runner import default_manifest_dir_for
    from belay.replay.reader import TraceCorrupt, read_trace
    from belay.verify.verdict import Status

    trace_path = Path(args.trace)
    otlp_path = Path(args.otlp)

    if trace_path.is_dir():
        _emit(
            f"belay: {trace_path} is a directory; pass a single trace file -- "
            "directory aggregation is not yet supported"
        )
        return 2
    if not trace_path.exists():
        _emit(f"belay: trace not found: {trace_path}")
        return 2
    if not otlp_path.exists():
        _emit(f"belay: OTLP spans file not found: {otlp_path}")
        return 2

    try:
        read = read_trace(trace_path)
    except TraceCorrupt as exc:
        _emit(f"belay: {exc}")
        return 2

    try:
        spans = parse_otlp(otlp_path.read_text(encoding="utf-8"))
    except OtlpParseError as exc:
        _emit(f"belay: {exc}")
        return 2

    records = list(read.records)
    manifest_dir = (
        Path(args.manifest_dir) if args.manifest_dir is not None else default_manifest_dir_for(trace_path)
    )

    if args.server:
        results = correlate_and_attach(
            records, spans,
            server_command=args.server, manifest_dir=manifest_dir,
            replays=args.replays, timeout=args.timeout,
        )
    else:
        results = _correlate_without_server(records, spans)

    if args.json:
        payload = {"trace": str(trace_path), **interop_report.to_json(results)}
        _emit(json.dumps(payload))
    else:
        _emit(f"belay interop correlate {trace_path}")
        _emit(f"  otlp spans            {otlp_path}")
        _emit(f"  manifest-dir          {manifest_dir}")
        if not args.server:
            _emit()
            _emit("  no --server given: correlation ran, but no turn was replayed --")
            _emit("  every matched span reports UNVERIFIED, never a guessed PASS.")
        _emit()
        _emit(interop_report.render(results))

    worst = _worst(results, Status)
    return 0 if worst is Status.PASS else 1


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
        help=(
            "do not apply the built-in default invariants (no-assertion-weakening "
            "under the tests and testing path segments)"
        ),
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
        default="corpus/local",
        help="the corpus directory the case is written under (default: ./corpus/local, which is gitignored so cases never get committed)",
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
        help=(
            "do not apply the built-in default invariants (no-assertion-weakening "
            "under the tests and testing path segments)"
        ),
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
        default="corpus/local",
        help="the corpus directory of case dirs to re-verify (default: ./corpus/local, which is gitignored so cases never get committed)",
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
        default="corpus/local",
        help="the corpus directory of case dirs to score (default: ./corpus/local, which is gitignored so cases never get committed)",
    )
    corpus_score.set_defaults(func=_cmd_corpus_score)

    corpus_label = corpus.add_parser(
        "label",
        help="adjudicate a case's HUMAN ground-truth label (never touches the engine verdict)",
        description=(
            "Set a case's HUMAN ground-truth label — the adjudication step between `corpus add` "
            "(which stores a case 'pending') and `corpus score` (which measures the engine's "
            "verdicts against these labels). Choose one of the three real adjudications; "
            "re-labeling is allowed, so a human can correct an earlier call.\n\n"
            "This rewrites ONLY `human_label`. The engine's recorded `expected` verdict is left "
            "byte-identical — a human adjudication NEVER edits what the engine computed. That "
            "separation is what lets `corpus score` measure the engine against the labels "
            "without measuring it against itself."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    corpus_label.add_argument("case_id", help="the case directory name under the corpus dir")
    corpus_label.add_argument(
        "--label",
        required=True,
        choices=["true-positive", "false-positive", "unverifiable"],
        help="the HUMAN adjudication for this case (not 'pending' — that is the un-adjudicated default)",
    )
    corpus_label.add_argument(
        "--root-cause-key",
        help=(
            "the kebab-case grouping key for this case's root cause. REQUIRED for "
            "--label true-positive: the gate criteria count INDEPENDENT true positives by "
            "distinct root cause, so a TP without one cannot be evaluated"
        ),
    )
    corpus_label.add_argument(
        "--root-cause-note",
        default="",
        help=(
            "free-text reasoning recorded beside the key (evidence, upstream commit, etc). "
            "Nothing groups on this; it is what a human reads. Requires --root-cause-key"
        ),
    )
    corpus_label.add_argument(
        "--corpus-dir",
        default="corpus/local",
        help="the corpus directory the case lives under (default: ./corpus/local, which is gitignored so cases never get committed)",
    )
    corpus_label.set_defaults(func=_cmd_corpus_label)

    corpus_list = corpus.add_parser(
        "list",
        help="list every case: id, human label, reduced status (sorted by id)",
        description=(
            "List every case in the corpus, one line each: case-id, human label, and the "
            "recorded expected reduced status. Sorted by case-id for a stable listing. A corrupt "
            "case is a fail-closed error, never a silently dropped row."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    corpus_list.add_argument(
        "corpus_dir",
        nargs="?",
        default="corpus/local",
        help="the corpus directory of case dirs to list (default: ./corpus/local, which is gitignored so cases never get committed)",
    )
    corpus_list.set_defaults(func=_cmd_corpus_list)

    corpus_show = corpus.add_parser(
        "show",
        help="show one case's key fields: verdict, sub-verdict set, label, invariants, provenance",
        description=(
            "Show one case's key fields without reading its case.json by hand: id, target turn, "
            "the expected reduced status AND its per-axis sub-verdict set, the human label, the "
            "invariants, the server command, and provenance. A missing or corrupt case is a "
            "fail-closed error."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    corpus_show.add_argument("case_id", help="the case directory name under the corpus dir")
    corpus_show.add_argument(
        "--corpus-dir",
        default="corpus/local",
        help="the corpus directory the case lives under (default: ./corpus/local, which is gitignored so cases never get committed)",
    )
    corpus_show.set_defaults(func=_cmd_corpus_show)

    phase0 = subcommands.add_parser(
        "phase0", help="run the failure corpus at scale and publish the violation-rate number"
    ).add_subparsers(dest="action", required=True)

    phase0_run = phase0.add_parser(
        "run",
        help="verify every trace in a directory, ingest FAILs into the corpus, and report",
        description=(
            "Verify every trace-*.jsonl in TRACE-DIR by RE-EXECUTION (the same verify_turn "
            "`verify`/`corpus add` run), ingest each FAILing turn into the corpus as a "
            "'pending' case, write the run ledger to --ledger, and print the Phase-0 report: "
            "the violation rate with its disciplined denominator, the instrument-suspect "
            "guard, the per-turn FAIL rate, the UNVERIFIED rate by named cause, and the "
            "labeled-corpus FP-rate.\n\n"
            "This is a MEASUREMENT, not a gate: the exit code reflects only a HARD error -- "
            "a missing trace-dir, a malformed --invariants file -- never 'violations were "
            "found'. A ledger full of flagged instances still exits 0."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    phase0_run.add_argument("trace_dir", help="directory of trace-*.jsonl files to verify")
    phase0_run.add_argument(
        "--ledger", required=True, metavar="path", help="path to write the run ledger as JSON"
    )
    phase0_run.add_argument(
        "--corpus-dir",
        default="corpus/local",
        help=(
            "the corpus directory FAILing turns are ingested into and scored from "
            "(default: ./corpus/local, which is gitignored so cases never get committed)"
        ),
    )
    phase0_run.add_argument(
        "--no-ingest",
        action="store_true",
        help=(
            "measure without writing: suppress every corpus WRITE, not detection. Turns are "
            "still verified and every FAIL is still counted in the report; no case is added, "
            "so flagged-addable and flagged-but-unaddable are both empty, and the report says "
            "ingestion was NOT ATTEMPTED rather than leaving that empty pair to read as "
            "'nothing could be added'"
        ),
    )
    phase0_run.add_argument(
        "--invariants",
        default=None,
        metavar="path",
        help=(
            "an operator-declared invariant file (JSON) to enforce as A1, on top of the "
            "defaults; a malformed file is a fail-closed error, never a silent skip"
        ),
    )
    phase0_run.add_argument(
        "--no-default-invariants",
        action="store_true",
        help=(
            "do not apply the built-in default invariants (no-assertion-weakening "
            "under the tests and testing path segments)"
        ),
    )
    phase0_run.add_argument(
        "--replays",
        type=_verify_replays,
        default=3,
        help="on a DIVERGED reply, re-invoke this many times to classify determinism (default: 3, minimum: 3)",
    )
    phase0_run.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"per-replay timeout in seconds (default: {DEFAULT_TIMEOUT:g})",
    )
    phase0_run.add_argument(
        "--server",
        nargs=argparse.REMAINDER,
        default=[],
        metavar="cmd ...",
        help=(
            "the MCP server to replay against; everything after --server is its command. "
            "A whole argument equal to the literal {workspace} is replaced, per trace, with "
            "that trace's own recorded workspace root -- so ONE command verifies a batch "
            "captured from many workspaces (quote it: '{workspace}')"
        ),
    )
    phase0_run.set_defaults(func=_cmd_phase0_run)

    phase0_report = phase0.add_parser(
        "report",
        help="re-render the Phase-0 report from a saved ledger -- no replay, no re-run",
        description=(
            "Load a run ledger written by `phase0 run --ledger` and re-render the same "
            "Phase-0 report for it: a pure re-render, no replay, no re-verification, no "
            "clock read. A missing or corrupt ledger file is a fail-closed error."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    phase0_report.add_argument(
        "ledger", help="the ledger JSON file to re-render (written by `phase0 run --ledger`)"
    )
    phase0_report.add_argument(
        "--corpus-dir",
        default="corpus/local",
        help=(
            "the corpus directory to score against (default: ./corpus/local, which is "
            "gitignored so cases never get committed)"
        ),
    )
    phase0_report.set_defaults(func=_cmd_phase0_report)

    phase0_combine = phase0.add_parser(
        "combine",
        help="merge several labeled stage ledgers into one population and report the number",
        description=(
            "Merge N run ledgers into ONE population, given as LABEL=PATH pairs, and print "
            "the population report: the dedup rule in words, BOTH denominators (instances "
            "as the headline, captures alongside), and every instance whose captures "
            "disagreed.\n\n"
            "The LABEL is mandatory and is the ledger's stage (s1, s2, s3...). A trace_id "
            "is NOT unique across stages -- it is the trace file's stem, so two stages of "
            "one instance share it while being genuinely different observations. A CAPTURE "
            "is (label, trace_id); an INSTANCE is a trace_id. Without labels the population "
            "would silently collapse two real observations into one.\n\n"
            "Dedup: an instance is VIOLATING iff ANY of its captures flagged "
            "(worst-verdict-wins), and is IN THE DENOMINATOR iff ANY of its captures is "
            "VERIFIED_CLEAN or VERIFIED_FLAGGED -- a capture that ERRORED is not evidence "
            "of a violation.\n\n"
            "Fail-closed on every input defect: a malformed pair, a repeated label, a "
            "missing or corrupt ledger is a named error, never a silent skip."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    phase0_combine.add_argument(
        "ledgers",
        nargs="+",
        metavar="LABEL=PATH",
        help=(
            "a stage label and the ledger JSON file it names, e.g. s2=runs/s2.json; "
            "repeat for each stage"
        ),
    )
    phase0_combine.set_defaults(func=_cmd_phase0_combine)

    interop = subcommands.add_parser(
        "interop", help="observability interop: correlate OTLP spans to MCP turns and attach the verdict"
    ).add_subparsers(dest="action", required=True)

    interop_correlate = interop.add_parser(
        "correlate",
        help="correlate OTLP/JSON spans to a trace's MCP turns and report the correlation rate",
        description=_INTEROP_CORRELATE_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    interop_correlate.add_argument("otlp", help="the OTLP/JSON spans document to correlate")
    interop_correlate.add_argument(
        "trace", help="the trace file (.jsonl) to correlate against -- a single file, not a directory"
    )
    interop_correlate.add_argument(
        "--manifest-dir",
        default=None,
        help=(
            "where the gate persisted this run's snapshot manifests; default: the "
            "trace's <stem>.manifests sibling (the mint convention C2/C3 already use)"
        ),
    )
    interop_correlate.add_argument(
        "--replays",
        type=_verify_replays,
        default=3,
        help="on a DIVERGED reply, re-invoke this many times to classify determinism (default: 3, minimum: 3)",
    )
    interop_correlate.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"per-replay timeout in seconds (default: {DEFAULT_TIMEOUT:g})",
    )
    interop_correlate.add_argument(
        "--server",
        nargs=argparse.REMAINDER,
        default=[],
        metavar="cmd ...",
        help=(
            "the MCP server to REPLAY matched turns against; everything after --server "
            "is its command. Without --server, correlation still runs but nothing is "
            "replayed and every matched span reports UNVERIFIED (not-replayed-no-server)"
        ),
    )
    interop_correlate.add_argument(
        "--json",
        action="store_true",
        help="emit the machine-readable result (trace/correlation/spans) to stdout instead of the human report",
    )
    interop_correlate.set_defaults(func=_cmd_interop_correlate)

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
