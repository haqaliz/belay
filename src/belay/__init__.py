"""Belay — the agent harness.

`__version__` is read from the INSTALLED distribution rather than hardcoded here. It was
hardcoded, and it drifted: it still said `0.0.0` at the 0.10.0 release, because a literal in
this file and the version in `pyproject.toml` are two places to state one fact. The fallback
below covers the only case where no true answer exists — the package not installed at all
(a bare source checkout on `sys.path`) — and it is deliberately not a plausible-looking
number, so it cannot be mistaken for a real version.

This matters beyond tidiness. The Phase-0 ledger records the code identity that produced a
verdict, and `belay phase0 run` refused to stamp one while this value was known-wrong: a
confidently wrong version is worse than an honestly unrecorded one. Making it true is what
lets the ledger carry it.
"""

from importlib.metadata import PackageNotFoundError, version as _dist_version

try:
    __version__ = _dist_version("belay-harness")
except PackageNotFoundError:  # not installed — a bare source checkout on sys.path
    __version__ = "0+unknown"

__all__ = ["__version__"]
