"""Execution boundaries: the agent acts inside enforced limits, or not at all.

This package is the seam the rest of Belay calls. `backend_for(platform)` is
the dispatch: it resolves the containment implementation for a platform —
`seatbelt` (macOS Seatbelt profiles) on darwin, `linux` (Landlock + seccomp,
zero runtime dependencies) on Linux — and RAISES `UnsupportedPlatform` for any
platform with no implementation. "No implementation here" must never read as
"unsandboxed": `launch.contained` and `seatbelt.run` refuse rather than run
bare, because a run that quietly dropped the boundary would report exactly like
a contained one.

The backend modules each own their platform's mechanism and denial parsing;
what they share — the closed `NetworkPolicy` vocabulary, the `Denial`/denial
record shape, and the provenance floor `inferred: true, source: "child-stderr"`
— lives in `seatbelt.py` and is imported by the Linux backend rather than
re-implemented, so the record cannot drift between platforms.
"""

from __future__ import annotations

import sys

from belay.snapshot.bth1 import UnsupportedPlatform

__all__ = ["UnsupportedPlatform", "backend_for"]


def backend_for(platform: str | None = None):
    """Resolve the containment backend module for `platform` (default: this machine).

    - `darwin` -> `belay.sandbox.seatbelt` (Seatbelt profiles via `sandbox-exec`)
    - `linux` -> `belay.sandbox.linux` (Landlock filesystem scope + seccomp network)
    - anything else -> raises `UnsupportedPlatform`

    The raise is the product decision, stated once: a platform with no
    implementation cannot be silently downgraded to an unsandboxed run. The
    message is shaped so `launch.contained`'s refusal reads the same as it
    always has — "cannot contain anything on <platform> … Refusing rather than".
    """
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        from belay.sandbox import seatbelt

        return seatbelt
    if platform.startswith("linux"):
        from belay.sandbox import linux

        return linux
    raise UnsupportedPlatform(
        f"a sandbox was requested, and Belay cannot contain anything on "
        f"{platform!r}: no sandbox implementation exists for this platform. "
        f"Refusing rather than spawning the server unsandboxed — a run that "
        f"quietly dropped the boundary would report exactly like a contained one."
    )
