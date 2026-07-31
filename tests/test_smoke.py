from belay import __version__


def test_version_is_nonempty_string():
    assert isinstance(__version__, str)
    assert __version__


def test_version_matches_the_installed_distribution():
    """`belay.__version__` must be the version actually installed, not a placeholder.

    It was hardcoded `"0.0.0"` while `pyproject.toml` said `0.10.0`, and the existing
    `test_version_is_nonempty_string` above passed against that the whole time -- a
    non-empty string is not the same claim as a TRUE one. The drift is not cosmetic: the
    Phase-0 ledger wants to record the code identity that produced a verdict, and
    `_cmd_phase0_run` deliberately recorded `version=None` rather than stamp a value it
    knew was wrong. An honestly unrecorded version beats a confidently wrong one -- but a
    correct one beats both, and that is what this pins.
    """
    from importlib.metadata import version as dist_version

    from belay import __version__

    assert __version__ != "0.0.0"
    assert __version__ == dist_version("belay-harness")
