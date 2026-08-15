"""The platform seam: one dispatch, and a raise wherever no implementation exists.

The three old raise points (`seatbelt.run`, `launch.contained`, `clone.py`) were
three opinions about the same fact. `backend_for()` is that fact stated once:
darwin gets Seatbelt, linux gets the Landlock+seccomp backend, and every other
platform gets `UnsupportedPlatform` — a raise, never a cheerful no-op, because a
no-op would be Belay claiming a containment boundary that does not exist on that
platform.

Platform-neutral by design: every case in this file resolves a module or raises,
which needs no kernel at all. The containment the resolved backends enforce is
proven by `tests/test_containment.py` (darwin) and `tests/test_linux_containment.py`
(linux).
"""

from __future__ import annotations

import sys

import pytest

from belay.sandbox import backend_for
from belay.snapshot.bth1 import UnsupportedPlatform


def test_dispatch_resolves_darwin_to_seatbelt() -> None:
    from belay.sandbox import seatbelt

    assert backend_for("darwin") is seatbelt


def test_dispatch_resolves_linux_to_the_linux_backend() -> None:
    from belay.sandbox import linux

    assert backend_for("linux") is linux
    # sys.platform's Linux spelling has been "linux" for every supported
    # Python; the startswith form also covers the legacy "linux2" value.
    assert backend_for("linux2") is linux


@pytest.mark.parametrize("platform", ["win32", "cygwin", "freebsd", "emscripten", "java"])
def test_a_platform_with_no_implementation_raises(platform: str) -> None:
    """The honest re-scope: `unsupported` means "no implementation exists here",
    never "unsandboxed". A platform with no backend must raise, and the message
    must say it is refusing rather than running bare."""
    with pytest.raises(UnsupportedPlatform, match="Refusing rather than"):
        backend_for(platform)


def test_dispatch_resolves_this_machine_to_its_own_platform() -> None:
    assert backend_for() is backend_for(sys.platform)


def test_backend_for_is_importable_from_the_package_root() -> None:
    """The seam is part of `belay.sandbox`'s public surface, not a private helper."""
    from belay import sandbox

    assert sandbox.backend_for is backend_for
