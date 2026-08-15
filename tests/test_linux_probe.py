"""Unit tests for the Linux containment probe's pure helpers.

The probe (`eval/linux_probe/probe.py`) measures, on a pinned GitHub runner
image, which containment mechanisms can enforce Belay's boundary (aspect A1 of
the `linux-sandbox` slice). The whole point of the measurement is that it is
**measured**: a CI failure on the `spike-linux` job must mean the substrate
changed, not that the probe has a bug. So the *logic* parts of the probe are
pinned here, on every platform — the denial-text classification, the env-dict
shape, the schema the artifact must satisfy, the kernel-release parsing, and
the offline `allow-ports` feasibility analysis.

The live syscall probes (`probe_unshare_userns`, `probe_bwrap`,
`probe_landlock`) are Linux-only by nature and are *not* exercised here: they
run on the `spike-linux` CI job itself. Three smoke tests call them, skipif'd
to Linux, so a developer ON Linux can run them — and on macOS (and the macOS
CI job) they are skipped, keeping the suite green.
"""

from __future__ import annotations

import sys

import pytest

from eval.linux_probe.probe import (
    STATUS_VOCABULARY,
    classify_denial_marker,
    kernel_supports_landlock,
    leading_mechanism,
    parse_kernel_release,
    probe_allow_ports_mapping,
    probe_bwrap,
    probe_landlock,
    probe_unshare_userns,
    run_probes,
    shape_env,
    validate_result,
)

# --- denial-marker classification -------------------------------------------


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("Operation not permitted", "EPERM"),
        ("mv: cannot move '/etc/x' to '/tmp/y': Operation not permitted", "EPERM"),
        ("Permission denied", "EACCES"),
        ("sh: 1: cannot create /etc/belay-probe-denied.txt: Permission denied", "EACCES"),
        ("ls: cannot open directory 'x': Permission denied", "EACCES"),
        ("Read-only file system", "EROFS"),
        ("sh: 1: cannot create /etc/belay-probe-denied.txt: Read-only file system", "EROFS"),
        ("", "unknown"),
        ("No such file or directory", "unknown"),
    ],
)
def test_classify_denial_marker_recognizes_each_errno_family(stderr, expected):
    """Each errno family maps to exactly one marker, including the empty text.

    `unknown` for text that is not a refusal is deliberate: a classification
    that guessed would dress an ordinary error up as a denial, which is the
    exact conflation `seatbelt.py`'s `_DENIAL_MARKER` discipline exists to
    prevent.
    """
    assert classify_denial_marker(stderr) == expected


def test_classify_denial_marker_prefers_eperm_then_eacces():
    """When a child reports several markers, the order is stated, not random.

    EPERM first because "Operation not permitted" is the recognized sandbox
    marker (`seatbelt._DENIAL_MARKER`): if the sandbox is among the denials,
    the classification is the sandbox's. EACCES before EROFS for the same
    reason the plan draws the EPERM/EACCES line first.
    """
    assert (
        classify_denial_marker("prog: Operation not permitted; prog: Permission denied")
        == "EPERM"
    )
    assert classify_denial_marker("prog: Permission denied; prog: Read-only file system") == "EACCES"


def test_classify_denial_marker_is_case_sensitive_like_the_kernel():
    """The kernel's errno text is fixed; a lowercase variant is a different
    message and must not be claimed as a marker."""
    assert classify_denial_marker("operation not permitted") == "unknown"


# --- kernel-release parsing -------------------------------------------------


@pytest.mark.parametrize(
    ("release", "expected"),
    [
        ("6.8.0-1021-azure", (6, 8)),
        ("5.13.0-51-generic", (5, 13)),
        ("5.13", (5, 13)),
        ("6.6.0-rc3", (6, 6)),
        ("4.19.0-1", (4, 19)),
        ("garbage", None),
        ("", None),
        ("6", None),
    ],
)
def test_parse_kernel_release(release, expected):
    """`os.uname().release` is "MAJOR.MINOR..." on every Linux; anything that
    does not parse to two ints is reported as None — never guessed."""
    assert parse_kernel_release(release) == expected


@pytest.mark.parametrize(
    ("parsed", "expected"),
    [
        ((6, 8), True),
        ((5, 13), True),
        ((5, 12), False),
        ((4, 19), False),
        (None, False),
    ],
)
def test_kernel_supports_landlock_boundary_is_5_13(parsed, expected):
    """Landlock landed in Linux 5.13. The boundary is a hint for the artifact,
    never the verdict — the probe measures the syscall directly — and an
    unparseable release reads False, never a silent skip."""
    assert kernel_supports_landlock(parsed) is expected


# --- env-dict shaping -------------------------------------------------------


def test_shape_env_records_absent_runner_variables_as_null():
    """A local run has no GitHub runner variables; the artifact must say so
    explicitly (null), because a decision citing the artifact must be able to
    tell "no image" apart from a value that just was not written."""
    env = shape_env(
        platform_str="p",
        release="r",
        version="v",
        machine="m",
        python_version="3.12.0",
        runner_os=None,
        runner_image=None,
    )
    assert env["RUNNER_OS"] is None
    assert env["GITHUB_RUNNER_IMAGE"] is None


def test_shape_env_records_present_variables_and_is_deterministic():
    """Same inputs -> same dict, and the key set is exactly the seven the
    artifact promises: adding a key here is a schema change and must be
    deliberate."""
    kwargs = dict(
        platform_str="Linux-6.8.0-1021-azure-x86_64-with-glibc2.39",
        release="6.8.0-1021-azure",
        version="v",
        machine="x86_64",
        python_version="3.12.4",
        runner_os="Linux",
        runner_image="ubuntu-24.04:20240808.1",
    )
    first = shape_env(**kwargs)
    assert first["RUNNER_OS"] == "Linux"
    assert first["GITHUB_RUNNER_IMAGE"] == "ubuntu-24.04:20240808.1"
    assert shape_env(**kwargs) == first
    assert set(first) == {
        "platform",
        "release",
        "version",
        "machine",
        "python",
        "RUNNER_OS",
        "GITHUB_RUNNER_IMAGE",
    }


# --- artifact schema --------------------------------------------------------


def _valid_result() -> dict:
    return {
        "env": {
            "platform": "p",
            "release": "r",
            "version": "v",
            "machine": "m",
            "python": "3.12.0",
            "RUNNER_OS": None,
            "GITHUB_RUNNER_IMAGE": None,
        },
        "probes": {
            "unshare_userns": {"status": "ok"},
            "bwrap": {"status": "absent", "reason": "no 'bwrap' on PATH"},
            "landlock": {"status": "ok"},
            "allow_ports_mapping": {
                "status": "not-expressible",
                "reason": "no address scope in landlock's net domain",
            },
            "denial_marker": {"status": "unavailable", "reason": "nothing ran"},
        },
    }


def test_validate_result_accepts_a_complete_result():
    assert validate_result(_valid_result()) == []


def test_validate_result_accepts_an_all_unavailable_result():
    """The honest-unavailable shape is VALID — this is the load-bearing rule:
    the spike job must never fail because mechanisms are unavailable, because
    that IS the measurement. Validation exists to catch probe bugs, not to
    police the substrate."""
    result = _valid_result()
    for probe in result["probes"].values():
        probe.clear()
        probe["status"] = "unavailable"
        probe["reason"] = "Linux-only probe; not measured on this platform"
    assert validate_result(result) == []


def test_validate_result_rejects_a_status_outside_the_closed_vocabulary():
    result = _valid_result()
    result["probes"]["landlock"]["status"] = "probably-fine"
    violations = validate_result(result)
    assert any("landlock" in v and "status" in v for v in violations)


def test_validate_result_requires_a_reason_when_status_is_not_ok():
    result = _valid_result()
    del result["probes"]["bwrap"]["reason"]
    violations = validate_result(result)
    assert any("bwrap" in v and "reason" in v for v in violations)


def test_validate_result_rejects_an_unknown_probe_name():
    """The probe set is closed: a probe added to the artifact must be added to
    this validator (and its tests) — otherwise a new probe could ship without
    a schema, which is exactly how an artifact quietly loses its shape."""
    result = _valid_result()
    result["probes"]["side_channel"] = {"status": "ok"}
    violations = validate_result(result)
    assert any("side_channel" in v for v in violations)


def test_validate_result_requires_every_probe_key():
    result = _valid_result()
    del result["probes"]["landlock"]
    violations = validate_result(result)
    assert any("landlock" in v and "missing" in v for v in violations)


def test_validate_result_requires_env_and_probes_at_the_top_level():
    result = _valid_result()
    del result["env"]
    violations = validate_result(result)
    assert any("env" in v for v in violations)


# --- allow-ports feasibility (offline analysis) -----------------------------


def test_allow_ports_for_bwrap_is_not_expressible_without_netns_tools():
    """bwrap's --unshare-net is deny-all with no per-port granularity; the
    closed vocabulary needs netfilter (root + external tools). Reported with
    its measured basis, never as a bare verdict."""
    result = probe_allow_ports_mapping("bwrap")
    assert result["status"] == "not-expressible-without-netns-tools"
    assert result["leading_mechanism"] == "bwrap"
    assert isinstance(result["reason"], str) and result["reason"]
    assert isinstance(result.get("basis"), str) and result["basis"]


def test_allow_ports_for_landlock_is_not_expressible():
    """Landlock's net domain (measured in the landlock probe) scopes TCP by
    PORT only — a granted port is reachable on any address. Loopback-only is
    the half the closed vocabulary cannot give up, so it degrades to
    UNVERIFIED-with-cause rather than widening silently."""
    result = probe_allow_ports_mapping("landlock")
    assert result["status"] == "not-expressible"
    assert result["leading_mechanism"] == "landlock"
    assert isinstance(result["reason"], str) and result["reason"]
    assert isinstance(result.get("basis"), str) and result["basis"]


def test_allow_ports_with_no_mechanism_reports_none():
    result = probe_allow_ports_mapping("none")
    assert result["status"] == "not-expressible"
    assert result["leading_mechanism"] == "none"
    assert isinstance(result["reason"], str) and result["reason"]


def test_leading_mechanism_prefers_a_running_bwrap_then_landlock():
    """The mapping question is asked of the mechanism A2 could actually build
    on: bwrap only when it runs, then landlock, then an honest 'none'."""
    assert leading_mechanism({"status": "ok"}, {"status": "ok"}) == "bwrap"
    assert leading_mechanism({"status": "absent"}, {"status": "ok"}) == "landlock"
    assert leading_mechanism({"status": "unavailable"}, {"status": "ok"}) == "landlock"
    assert leading_mechanism({"status": "ok"}, {"status": "unavailable"}) == "bwrap"
    assert leading_mechanism({"status": "absent"}, {"status": "unavailable"}) == "none"


# --- whole-probe determinism -------------------------------------------------


def test_run_probes_is_deterministic_on_same_inputs():
    """Two runs on the same machine produce the same dict. On macOS every probe
    honestly reports unavailable; on Linux the syscall measurements are the
    same twice because the substrate is the same twice. This is the unit-level
    half of the CI double-run diff (spec criterion 3)."""
    assert run_probes() == run_probes()


# --- live syscall probes (Linux only) ---------------------------------------


def _assert_probe_shape(probe: dict) -> None:
    """Every probe dict satisfies the closed contract: a known status, and a
    non-empty reason whenever the status is not ok."""
    assert probe["status"] in STATUS_VOCABULARY
    if probe["status"] != "ok":
        assert isinstance(probe.get("reason"), str) and probe["reason"]


@pytest.mark.skipif(sys.platform != "linux", reason="live syscall probe; Linux only")
def test_live_probe_unshare_userns_returns_a_schema_shaped_dict():
    _assert_probe_shape(probe_unshare_userns())


@pytest.mark.skipif(sys.platform != "linux", reason="live subprocess probe; Linux only")
def test_live_probe_bwrap_returns_a_schema_shaped_dict():
    _assert_probe_shape(probe_bwrap())


@pytest.mark.skipif(sys.platform != "linux", reason="live syscall probe; Linux only")
def test_live_probe_landlock_returns_a_schema_shaped_dict():
    _assert_probe_shape(probe_landlock())
