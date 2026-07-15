"""Spawn a LONG-LIVED server inside the sandbox: the seam `seatbelt.run` cannot be.

This module is the join C2 exists for. `seatbelt.py` can contain a process and
`gate.py` can snapshot a turn's pre-state; until this module existed, a server
started by `python -m belay.proxy` got the second and not the first, and
`BELAY_SANDBOX_SCOPE` named a boundary nothing enforced. Per `CLAUDE.md` the
sandbox is not only containment, it is the A1 verdict axis — and an axis that is
not on the path grounds nothing.

## Why `seatbelt.run` could not be reused

`seatbelt.run` is **run-to-completion**: it blocks on `subprocess.run`, reads the
child's output after it exits, and unlinks the profile in a `finally`. All three
are wrong for a proxied server, which is long-lived and streams over live pipes
that the proxy owns. So this module supplies what the threat model said was
missing: *"a 'give me the argv, keep the profile alive' seam"*.

The composition is deliberately boring — build the profile, write it down, and put
`sandbox-exec -f <profile>` in front of the argv. `proxy.run`'s `Popen` is then
**exactly the one C1 shipped**, spawning a command it has no opinion about. Nothing
was added to the forwarding path to be wrong, and an unsandboxed run does not go
near this module.

## Denials, for a child that has not exited

The other thing the threat model named as missing: *"denials are inferred from the
child's stderr after it exits… a long-lived proxied server never reaches that
point"*. `DenialCapture` reads the child's stderr **as it is forwarded**, on a
bounded copy that cannot touch the bytes going to the operator's terminal, and
appends a `denial` record per refusal through `seatbelt.record_denials` — the same
writer as the batch path, so the provenance (`inferred: true, source:
"child-stderr"`) cannot drift between the two.

**Two limits, stated rather than discovered:** this sees a refusal only if the
child complains about it in the expected words (`seatbelt._denials_from_stderr`
explains why that is all Belay ever gets), and a final line the child leaves
without a terminating newline is named as a capture error rather than parsed. With
no `BELAY_TRACE_DIR` there is nothing to record into and stderr is not watched at
all — the containment is the kernel's either way and does not depend on anyone
writing it down.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence

from belay.sandbox import seatbelt
from belay.sandbox.scope import DefaultScope, default_scope
from belay.snapshot.bth1 import UnsupportedPlatform

__all__ = [
    "NETWORK_ENV",
    "Contained",
    "DenialCapture",
    "contained",
    "network_policy",
]

#: How the operator picks a network policy. Read the default's reasoning in
#: `network_policy` before changing it.
NETWORK_ENV = "BELAY_SANDBOX_NETWORK"

_ALLOW_PORTS = "allow-ports:"


def network_policy(spec: Optional[str]) -> seatbelt.NetworkPolicy:
    """The network policy for a proxied run. **Defaults to `deny-all`.**

    The threat model called this "an unmade product decision". This is the making
    of it, and the argument is the one the rest of this project is built on.

    `allow-all` was the tempting default, because it never breaks a server. It is
    also the one this repo already refuses to hand out: `seatbelt.run` has no
    default at all, and `test_allow_all_is_not_the_default_and_must_be_asked_for`
    is the reason. A run under `BELAY_SANDBOX_SCOPE` whose network was uncontained
    by default would be a boundary claimed by the variable's name and enforced on
    one axis only.

    So: deny, and let the failure be loud. A server denied a network fails in the
    operator's face, `belay sandbox check` names the refusal, and
    `BELAY_SANDBOX_NETWORK=allow-all` is one variable away — a widening the
    operator *chose*, which is the whole difference. A server silently permitted
    to reach the internet fails nobody's face and is discovered later by somebody
    else.

    What makes `deny-all` affordable rather than merely principled is the
    unix-socket line in `seatbelt.build_profile`: `network*` covers unix sockets
    too, so before it, `deny-all` killed any server that opened one in its own
    temp directory. It does not any more, and the four measured edges of that grant
    are in `tests/test_containment.py`.
    """
    if spec is None or spec == "":
        return seatbelt.NetworkPolicy.deny_all()
    spec = spec.strip()
    if spec.startswith(_ALLOW_PORTS):
        ports = [p for p in spec[len(_ALLOW_PORTS) :].split(",") if p.strip()]
        try:
            return seatbelt.NetworkPolicy.allow_ports(int(p) for p in ports)
        except ValueError as exc:
            raise ValueError(f"{NETWORK_ENV}={spec!r}: {exc}") from exc
    if spec == "allow-ports":
        raise ValueError(
            f"{NETWORK_ENV}=allow-ports needs the ports it allows, as "
            f"'allow-ports:8080,9000'. It means: outbound to loopback, on these "
            f"ports — Seatbelt cannot express a per-host rule at all."
        )
    if spec not in seatbelt.NETWORK_MODES:
        raise ValueError(
            f"{NETWORK_ENV}={spec!r} is not a network mode. The vocabulary is a "
            f"closed enum — {', '.join(seatbelt.NETWORK_MODES)} — because Seatbelt "
            f"can only express these, and accepting one we cannot compile would "
            f"mean claiming a boundary we do not enforce."
        )
    return seatbelt.NetworkPolicy(mode=spec)


class DenialCapture:
    """A `proxy.CaptureSink` over the server's stderr, recording refusals as they land.

    Shaped as a sink rather than a bare callback so the proxy's own machinery does
    the work: the copy is bounded, the observation is gated shut before the trace
    writer closes, and a stream that ends mid-line is **named** instead of silently
    dropped. Diagnostics never reach the trace — only denials do — because stderr
    is the child's, not the protocol's.
    """

    def __init__(self, trace: Any) -> None:
        self._trace = trace

    def observer(self, direction: str) -> Callable[[bytes, bool], None]:
        def observe(line: bytes, truncated: bool) -> None:
            # Total, deliberately. This runs on the stderr pump; an exception here
            # would kill the operator's view of their own server's output, and no
            # denial record is worth that. The proxy is not able to guard it: it
            # hands a peek nothing but bytes.
            try:
                seatbelt.record_denials(self._trace, seatbelt._denials_from_stderr(line))
            except Exception as exc:  # noqa: BLE001
                self.capture_error(direction, exc)

        return observe

    def capture_error(self, direction: str, cause: BaseException) -> None:
        # To stderr, not to the trace: the failure is in *our* reading of the
        # child's stderr, and a `capture_error` record claims a frame direction
        # went dark. This one did not — the bytes reached the operator either way.
        print(
            f"belay: denial capture on the server's stderr degraded "
            f"({type(cause).__name__}: {cause}); a refusal in this run may not be "
            f"recorded. Containment is unaffected: the boundary is the kernel's.",
            file=sys.stderr,
        )


@dataclass(frozen=True)
class Contained:
    """A command, wrapped so that spawning it normally spawns it contained."""

    #: What to hand to `proxy.run`. `sandbox-exec -f <profile> env TMPDIR=… <cmd>`.
    argv: list[str]

    #: The scope the argv was built for. `snapshot_root` is what the gate clones;
    #: it is NOT the same as what the profile grants (`write_roots`).
    scope: DefaultScope

    #: The profile text, as compiled. Carried so a caller can record or print what
    #: was applied without rebuilding it and risking a different answer.
    profile: str

    profile_path: str


@contextmanager
def contained(
    command: Sequence[str],
    *,
    workspace: Path | str,
    network: seatbelt.NetworkPolicy,
) -> Iterator[Contained]:
    """`command`, wrapped to run under a profile that lives as long as the block.

    The profile file is the policy. It is created owner-only by `mkstemp` and
    unlinked on the way out: a profile a child could write to is a policy the child
    can rewrite, and one left on disk afterwards is a policy nothing owns. The mode
    is asserted rather than assumed — this is the one file in Belay whose
    permissions are a security boundary rather than hygiene.

    Raises `UnsupportedPlatform` off macOS rather than yielding the bare command.
    Running unsandboxed here would be Belay silently withdrawing a boundary the
    operator asked for by name, which is the failure this project exists to catch,
    committed by us.
    """
    if sys.platform != "darwin":
        raise UnsupportedPlatform(
            f"a sandbox was requested, and Belay cannot contain anything on "
            f"{sys.platform!r}: Seatbelt is macOS-only. Refusing rather than "
            f"spawning the server unsandboxed — a run that quietly dropped the "
            f"boundary would report exactly like a contained one."
        )

    scope = default_scope(workspace)
    profile = seatbelt.build_profile(scope=scope.write_roots, network=network)

    handle, profile_path = tempfile.mkstemp(prefix="belay-sandbox-", suffix=".sb")
    try:
        with os.fdopen(handle, "w") as fh:
            fh.write(profile)
        mode = stat.S_IMODE(os.stat(profile_path).st_mode)
        if mode != 0o600:
            raise OSError(
                f"the sandbox profile {profile_path!r} is mode {mode:o}, not 600: "
                f"refusing to apply a policy the contained process could rewrite"
            )
        yield Contained(
            argv=[seatbelt.SANDBOX_EXEC, "-f", profile_path, *scope.wrap(command)],
            scope=scope,
            profile=profile,
            profile_path=profile_path,
        )
    finally:
        # `missing_ok`: the profile going missing is not a reason to fail a run
        # that has already finished, and the alternative is masking the child's
        # own exception with a cleanup one.
        Path(profile_path).unlink(missing_ok=True)
