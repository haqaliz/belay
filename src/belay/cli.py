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
from typing import Sequence

__all__ = ["main"]

#: How long the server is given before it is assumed to be running happily. It is
#: a *sample*, not a verdict — see the module docstring. A server that idles on
#: stdin will simply be killed at the end of it, which is a clean exit for our
#: purposes and is why a timeout is not itself reported as a failure.
DEFAULT_SECONDS = 2.0

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
