"""Run a subprocess inside a macOS Seatbelt profile, and record what it was refused.

This module is the containment half of C2. It is also, per `CLAUDE.md`, a verdict
axis: A1 catches *corrupt success* — the right end-state reached through a path
that violated a declared boundary — and the boundary that contains an action is
the same machinery that later judges it.

**The rule this module is written against: never claim a boundary we do not
enforce.** A sandbox that says it restricts something it does not is worse than
no sandbox at all, because someone will trust it. That rule is why the network
vocabulary is a closed enum that *raises* on a hostname (see `NetworkPolicy`)
rather than accepting one and quietly not enforcing it, why `UnsupportedPlatform`
is raised off Darwin instead of returning a cheerful no-op, and why every denial
record below states that it was inferred.

**What the profile is, and why it is not editable from memory.** Every line was
measured on macOS 26.5.2 / arm64, not recalled from documentation:

- `(allow mach-lookup)` is REQUIRED, and the reason is narrower than it looks.
  Measured by removing the line and re-running everything: `/bin/sh`, Homebrew
  python and node all keep working, and every containment vector stays green.
  The one thing that breaks is the stock `/usr/bin/python3` shim, which exits
  **72** — unable to reach the bootstrap server to resolve
  `DARWIN_USER_TEMP_DIR` via `confstr` — *before it runs a line of its own code*.
  Since `python3 -m some_mcp_server` is exactly the shape we ship in front of,
  the line stays, and `test_the_stock_python3_shim_survives_the_profile` is what
  holds it there. The trap is that a profile broken this way looks perfect to a
  suite built on `/bin/sh`.
  (The planning brief predicted `/bin/sh` would die at rc=134/SIGABRT without
  this line. It does not, on macOS 26.5.2/arm64 — noted so the next person does
  not go looking for a symptom that is not there.)
- `(deny network*)` then a narrower `allow` works because SBPL is last-match-wins.
- Per-host allowlists are a COMPILE error (`host must be * or localhost in
  network address`), which is what makes `NetworkPolicy` a closed enum rather
  than a preference.

`os.path.realpath` on the scope is load-bearing, not hygiene: `/tmp` is a symlink
to `private/tmp`, and a profile granting `(subpath "/tmp/x")` grants *nothing* —
measured: the write to the supposedly-allowed directory returns `Operation not
permitted`. Unresolved, Belay would hand a user a policy that silently denies
their own work while reading correctly on the page.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from belay.snapshot.bth1 import UnsupportedPlatform
from belay.trace import TraceWriter

__all__ = [
    "NETWORK_MODES",
    "Denial",
    "NetworkPolicy",
    "SandboxResult",
    "UnsupportedPlatform",
    "build_profile",
    "record_denials",
    "run",
]

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

# A CLOSED enum, and a guardrail rather than a preference. Anything Seatbelt
# cannot express must be impossible to ask for, because the alternative is
# accepting a policy we do not apply.
NETWORK_MODES = ("deny-all", "allow-all", "allow-ports")

# Seatbelt reports a policy violation to the child as EPERM. EACCES ("Permission
# denied") is deliberately NOT in this list: that is ordinary filesystem
# permissions, and claiming it as a sandbox denial would attribute the user's own
# chmod to Belay's boundary.
_DENIAL_MARKER = "Operation not permitted"

# A path as a child process prints it: absolute, or relative via ./ or ../ .
_PATH_TOKEN = re.compile(r"(?:\.{1,2}/|/)\S*")


def _quote(path: str) -> str:
    """Escape a path for an SBPL string literal.

    The scope is data being pasted into the policy language that enforces the
    policy. An unescaped `"` would close the literal early and let the remainder
    of a path be parsed as SBPL — a policy injection into the sandbox itself.
    """
    return path.replace("\\", "\\\\").replace('"', '\\"')


@dataclass(frozen=True)
class NetworkPolicy:
    """What the sandboxed process may reach on the network. A closed enum.

    `allow-ports` means *outbound to loopback, on these ports*. It cannot mean
    anything else: Seatbelt rejects a per-host allowlist at compile time, so the
    only axis left to scope is the port. Both halves are measured — an allowed
    port connects, and a port outside the list is refused *while a listener is
    live on it*, so the refusal is the sandbox and not an absent server.

    Outbound only, never `network-inbound`: the spike measured that
    `(local ip "localhost:*")` does **not** confine the bind address — a process
    granted inbound can bind `0.0.0.0`. Belay's sandboxed side is always the
    client dialing a trusted host-side socket, so it is never granted the thing
    whose confinement does not hold.
    """

    mode: str
    ports: tuple[int, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.mode not in NETWORK_MODES:
            raise ValueError(
                f"unknown network mode {self.mode!r}; the vocabulary is a closed enum: "
                f"{', '.join(NETWORK_MODES)}. It is closed because Seatbelt can only "
                f"express these, and accepting a mode we cannot compile would mean "
                f"claiming a boundary we do not enforce."
            )
        if self.ports and self.mode != "allow-ports":
            raise ValueError(f"ports are only meaningful for mode 'allow-ports', not {self.mode!r}")

    @classmethod
    def deny_all(cls) -> "NetworkPolicy":
        return cls(mode="deny-all")

    @classmethod
    def allow_all(cls) -> "NetworkPolicy":
        return cls(mode="allow-all")

    @classmethod
    def allow_ports(cls, ports: Iterable[int]) -> "NetworkPolicy":
        """Outbound to loopback on `ports`. Anything host-shaped is REJECTED here.

        Rejecting at the API is the whole point. `(remote ip "1.1.1.1:*")` does
        not compile — `host must be * or localhost in network address` — so a
        hostname could only ever be accepted and dropped. The user would then
        believe their traffic was confined to an allowlist while it was confined
        to nothing, which is precisely the failure this project exists to catch.
        """
        checked: list[int] = []
        for port in ports:
            if isinstance(port, bool) or not isinstance(port, int):
                raise ValueError(
                    f"{port!r} is not a port. Seatbelt cannot express a host allowlist: "
                    f"a per-host rule is a COMPILE error ('host must be * or localhost in "
                    f"network address'), so Belay will not accept a host and silently fail "
                    f"to enforce it. allow-ports means: outbound to loopback, on these ports."
                )
            if not 1 <= port <= 65535:
                raise ValueError(f"port {port} is outside 1-65535")
            checked.append(port)
        if not checked:
            raise ValueError(
                "allow-ports with no ports grants nothing; say deny_all() if that is the intent"
            )
        return cls(mode="allow-ports", ports=tuple(checked))

    def rules(self) -> list[str]:
        if self.mode == "deny-all":
            return []
        if self.mode == "allow-all":
            return ["(allow network*)"]
        return [f'(allow network-outbound (remote ip "localhost:{port}"))' for port in self.ports]


@dataclass(frozen=True)
class Denial:
    """One line on which the child said it was refused. See `_denials_from_stderr`."""

    op: str
    path: Optional[str]
    detail: str


@dataclass(frozen=True)
class SandboxResult:
    rc: int
    stdout: bytes
    stderr: bytes
    profile: str
    denials: tuple[Denial, ...]


def _resolved_scope(scope: Path | str) -> str:
    """The scope as the kernel sees it, or an error.

    `realpath` only resolves components that exist, so a scope that does not
    exist cannot be resolved — and a profile built from an unresolved path is the
    silent-deny failure above, arriving without a word.
    """
    resolved = os.path.realpath(str(scope))
    if not os.path.isdir(resolved):
        raise ValueError(
            f"sandbox scope {str(scope)!r} does not exist (resolved to {resolved!r}). "
            f"It must exist before the profile is built: realpath() cannot resolve a "
            f"path that is not there, and an unresolved subpath silently grants nothing."
        )
    return resolved


def _write_scopes(scope: Path | str | Sequence[Path | str]) -> list[str]:
    """Resolve `scope` to the subpaths the profile will grant, in the order given.

    One path or several. Several, because the write scope is genuinely plural: a
    server needs its workspace *and* a temp directory, and those are two trees in
    two places (`belay.sandbox.scope`). Duplicates are dropped rather than emitted
    twice — a profile listing one subpath twice grants exactly what it granted
    once, and reads like a mistake.
    """
    paths: Sequence[Path | str]
    if isinstance(scope, (str, Path)):
        paths = [scope]
    else:
        paths = list(scope)
        if not paths:
            raise ValueError(
                "a profile with no write scope grants nothing writable at all; "
                "pass the tree the child may change"
            )
    resolved: list[str] = []
    for path in paths:
        real = _resolved_scope(path)
        if real not in resolved:
            resolved.append(real)
    return resolved


def build_profile(
    *, scope: Path | str | Sequence[Path | str], network: NetworkPolicy
) -> str:
    """The VERIFIED profile shape. Do not substitute lines from memory."""
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        # Required. Without it a real interpreter never reaches its own code.
        "(allow mach-lookup)",
        "(allow file-read*)",
        *(
            f'(allow file-write* (subpath "{_quote(root)}"))'
            for root in _write_scopes(scope)
        ),
        # `/dev/null` is a stateless discard device: writing to it persists nothing and
        # escapes no scope, yet redirecting output to it (`2>/dev/null`) is one of the
        # most common things any program does — including the stock macOS
        # `/usr/bin/python3` shim, which runs `xcodebuild ... 2>/dev/null` to resolve the
        # interpreter and exits 72 if that write is denied (surfaced by CI, where the
        # runner's python3 is exactly that shim). `file-write-data` is the tightest grant
        # that lets it through — bytes only, never create/unlink/chmod — so the write
        # scope above stays the only place real state may change. Measured, not assumed:
        # `/dev/null` is the one device CI actually denied; no other device is granted.
        '(allow file-write-data (literal "/dev/null"))',
        "(deny network*)",
        # `network*` covers UNIX domain sockets, not just IP — measured, and the
        # reason this line exists. Without it `deny-all` kills any server that
        # opens a socket in its own temp directory, and `deny-all` is what a
        # proxied run gets when nobody asks for anything else.
        #
        # Narrow, and every edge of it is measured
        # (`tests/test_containment.py`, the unix-socket group):
        #   - `network-bind`, never `network-outbound`: a contained process may
        #     LISTEN. It may not connect to a socket it did not create, which is
        #     the line between "a server may serve" and "a contained process may
        #     talk to the Docker daemon". `(allow network* (local unix-socket))`
        #     was measured permitting exactly that connect, and is why this says
        #     `network-bind`.
        #   - It does not widen the filesystem scope: binding creates a file, and
        #     WHERE one may be created is still `file-write*`'s decision. A bind
        #     outside the scope is refused.
        #   - IP egress stays denied.
        "(allow network-bind (local unix-socket))",
        # Last-match-wins: any narrower grant must follow the deny above.
        *network.rules(),
    ]
    return "\n".join(lines) + "\n"


def _denials_from_stderr(stderr: bytes) -> tuple[Denial, ...]:
    """Read the child's own complaints back as denial records.

    **Provenance, stated plainly because the record itself carries the claim:**
    what this returns is *the child reported a permission error*, NOT *the kernel
    told us it denied X*. Seatbelt reports violations to the system log, not to
    the child's stderr in any structured form. So every record is marked
    `inferred: true, source: "child-stderr"`, and `detail` carries the verbatim
    line the inference came from — the line is the ground truth, `path` and `op`
    are derived from it.

    `log stream --predicate` would give the kernel's own account, which is the
    honest upgrade; it is async and needs a subscription running before the child
    starts, so v0 takes the simple path and says so rather than dressing this one
    up as something it is not.

    **The known limits, so nobody reads more into `path` than is there.** Unix
    tools report `prog: <subject>: <error>`, so the subject is recovered by
    splitting on `": "` and taking the last path-shaped token in it — for `mv:
    rename A to B` that is the destination, which is the write that was refused.
    A path containing `": "` therefore parses wrong, and a child that reports no
    path at all leaves `path` None with `op` "unknown". None of this is a guess
    dressed as a fact: it is why `detail` exists.
    """
    denials: list[Denial] = []
    for raw_line in stderr.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if _DENIAL_MARKER not in line:
            continue
        fields = line.split(": ")
        # fields[0] is the reporting program, fields[-1] is the error text; the
        # subject of the refusal is what sits between them.
        subject = ": ".join(fields[1:-1])
        candidates = [token.rstrip(":") for token in _PATH_TOKEN.findall(subject)]
        path = candidates[-1] if candidates else None
        denials.append(
            Denial(op="file-write" if path is not None else "unknown", path=path, detail=line)
        )
    return tuple(denials)


def record_denials(trace: TraceWriter, denials: Iterable[Denial]) -> None:
    """Append one `denial` record per refusal the child reported.

    One writer for this record, shared by the run-to-completion path and the live
    proxy path, because the field that matters most is the provenance: every record
    says `inferred: true, source: "child-stderr"`. Two emitters would be two chances
    for one of them to drop that and let a *"the child said so"* read as *"the
    kernel said so"*. See `_denials_from_stderr` for why that distinction is the
    whole point of the record.
    """
    for denial in denials:
        trace.record(
            "denial",
            op=denial.op,
            path=denial.path,
            inferred=True,
            source="child-stderr",
            detail=denial.detail,
        )


def run(
    command: Sequence[str],
    *,
    scope: Path | str | Sequence[Path | str],
    network: NetworkPolicy,
    trace: TraceWriter | None = None,
    cwd: Path | str | None = None,
    timeout: float | None = 30.0,
) -> SandboxResult:
    """Run `command` under Seatbelt, contained to `scope`, recording every refusal.

    `trace` is a `belay.trace.TraceWriter` or None. Containment does not depend
    on it: the boundary is the kernel's, and it holds whether or not anyone is
    writing it down. The records appended are FACTS — `network_policy` says which
    policy was applied, `denial` says the child reported a refusal. Neither is
    verdict-shaped: C2 does not decide replayability, C4 does.

    The scope grants writes — one tree or several, since a real child needs its
    workspace *and* a temp directory. Reads are NOT scoped (`file-read*` is allowed
    wholesale), which is a real limit of what this profile claims: it contains
    what the child can *change*, not what it can *see*.

    **This function is run-to-completion.** It blocks until the child exits and
    unlinks the profile on the way out, which is right for a probe and wrong for a
    proxied server: that one is long-lived and streams over live pipes. That case
    composes the same profile onto an argv instead — see `belay.sandbox.launch`.
    """
    if sys.platform != "darwin":
        raise UnsupportedPlatform(
            f"the Seatbelt sandbox is macOS-only and cannot contain anything on "
            f"{sys.platform!r}. Raising rather than running the command unsandboxed: a "
            f"no-op that returned success would be Belay claiming a containment boundary "
            f"that does not exist on this platform."
        )

    profile = build_profile(scope=scope, network=network)

    if trace is not None:
        # A fact, recorded before the child runs: what was applied, not whether
        # it was enough.
        trace.record(
            "network_policy",
            policy=network.mode,
            ports=list(network.ports),
        )

    handle, profile_path = tempfile.mkstemp(prefix="belay-sandbox-", suffix=".sb")
    try:
        with os.fdopen(handle, "w") as fh:
            fh.write(profile)
        completed = subprocess.run(
            [SANDBOX_EXEC, "-f", profile_path, *command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout,
        )
    finally:
        os.unlink(profile_path)

    denials = _denials_from_stderr(completed.stderr)

    if trace is not None:
        record_denials(trace, denials)

    return SandboxResult(
        rc=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        profile=profile,
        denials=denials,
    )
