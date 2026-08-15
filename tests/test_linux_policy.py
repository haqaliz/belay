"""The Linux policy machinery, unit-tested without a kernel.

`belay.sandbox.linux` enforces the boundary with two kernel mechanisms —
Landlock for the filesystem write scope, seccomp for network deny-all — applied
by a launcher subprocess. Everything this file tests is the *policy logic* that
runs before and inside the launcher: the Landlock access-right masks per ABI,
the seccomp BPF filter bytes, the denial-line classification, and the closed
network vocabulary. None of it needs a Linux kernel, so it runs on every
platform (and on the macOS CI job); the containment suite
(`tests/test_linux_containment.py`) proves the same bytes contain on a real box.

**The seccomp decision, pinned here and proven there.** The filter denies
`socket()` for any domain other than AF_UNIX (so no IP socket can exist at
all — client or server), allows `socketpair()` (a launcher/child staple), and
denies `connect`/`sendto`/`sendmsg`/`sendmmsg` unconditionally — the "no
outbound on any socket" half of the macOS `(deny network*)` boundary, which
also denies unix-socket connects. Everything else is allowed. An architecture
other than the one the filter was built for reads ENOSYS — fail closed, never a
silent bypass. This is exactly the shape `tests/test_linux_containment.py`
proves on ubuntu-24.04.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay import sandbox
from belay.sandbox import linux
from belay.sandbox.seatbelt import NetworkPolicy
from belay.snapshot.bth1 import UnsupportedPlatform
from belay.trace import TraceWriter

from conftest import read_trace

# --- seccomp simulation (the filter is executed against synthetic syscalls) --

#: seccomp return values (linux/seccomp.h).
_SECCOMP_RET_ALLOW = 0x7FFF0000
_SECCOMP_RET_ERRNO = 0x00050000
_EPERM = 1
_ENOSYS = 38

#: BPF instruction codes used by the filter (linux/filter.h).
_LD_W_ABS = 0x20
_JEQ_K = 0x15
_RET_K = 0x06


def _simulate(program, nr: int, arch: int, args: tuple[int, ...]) -> int:
    """Execute a classic-BPF seccomp filter over synthetic `seccomp_data`.

    The kernel's seccomp interpreter is deterministic over (nr, arch, args);
    this is a faithful simulator for the subset of BPF the filter uses
    (load-abs, jump-eq, return), so the DECISIONS are testable everywhere the
    kernel itself is not.
    """
    data = {0: nr, 4: arch}
    for i, value in enumerate(args):
        data[16 + 8 * i] = value
    a = 0
    pc = 0
    while True:
        code, jt, jf, k = program[pc]
        if code == _LD_W_ABS:
            a = data[k]
            pc += 1
        elif code == _JEQ_K:
            pc += 1 + (jt if a == k else jf)
        elif code == _RET_K:
            return k
        else:
            raise AssertionError(f"unhandled BPF instruction {code:#x} at {pc}")


# --- Landlock access-right masks (per ABI) ----------------------------------


def test_landlock_write_access_mask_is_abi_scoped() -> None:
    """ABI 1 has no REFER (rename/link) or TRUNCATE rights; the mask must
    reflect the kernel it will be handed to, or `create_ruleset` rejects the
    ruleset as EINVAL on an older kernel."""
    abi1 = linux.fs_write_access(1)
    assert abi1 & linux.FS_WRITE_FILE
    assert not abi1 & linux.FS_REFER
    assert not abi1 & linux.FS_TRUNCATE

    abi2 = linux.fs_write_access(2)
    assert abi2 & linux.FS_REFER
    assert not abi2 & linux.FS_TRUNCATE

    abi3 = linux.fs_write_access(3)
    assert abi3 & linux.FS_REFER
    assert abi3 & linux.FS_TRUNCATE

    # Everything ABI 3+ can express (4+ adds the net domain, which this backend
    # deliberately does not handle) — the mask is stable from 3 up.
    assert linux.fs_write_access(7) == linux.fs_write_access(3)

    # The mask is exactly the write half of `(allow file-write* (subpath ...))`:
    # create, write, remove, rename/link, truncate — never read or execute,
    # which stay unhandled and therefore unrestricted (mirroring the macOS
    # profile's wholesale `(allow file-read*)`).
    assert not abi1 & linux.FS_EXECUTE
    assert not abi1 & linux.FS_READ_FILE
    assert not abi1 & linux.FS_READ_DIR


# --- the policy artifact (the Linux `profile`) ------------------------------


def test_policy_text_is_the_json_ruleset_description(tmp_path: Path) -> None:
    scope = tmp_path / "workspace"
    scope.mkdir()

    text = linux.policy_text(scope=scope, network=NetworkPolicy.deny_all())

    policy = json.loads(text)
    assert policy["version"] == 1
    assert policy["write_roots"] == [str(scope.resolve())]
    assert policy["network"] == "deny-all"


def test_policy_text_records_multiple_write_roots_in_order(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()

    policy = json.loads(linux.policy_text(scope=[first, second], network=NetworkPolicy.allow_all()))

    assert policy["write_roots"] == [str(first.resolve()), str(second.resolve())]
    assert policy["network"] == "allow-all"


def test_policy_text_refuses_a_write_scope_that_does_not_exist(tmp_path: Path) -> None:
    """Same rule as the macOS profile: realpath cannot resolve a path that is
    not there, and an unresolved subpath would grant nothing — arriving
    silently."""
    with pytest.raises(ValueError, match="does not exist"):
        linux.policy_text(scope=tmp_path / "nope", network=NetworkPolicy.deny_all())


def test_allow_ports_is_a_named_cause_refusal_on_linux(tmp_path: Path) -> None:
    """M7: the closed vocabulary means the same thing on both platforms, and
    `allow-ports` cannot mean it here — Landlock's net domain scopes TCP by
    PORT only, with no address scope, so a port grant would be a LOOSER
    boundary than the vocabulary claims. Refused with a name, never widened."""
    scope = tmp_path / "workspace"
    scope.mkdir()

    with pytest.raises(linux.NetworkPolicyUnsupported, match="port"):
        linux.policy_text(scope=scope, network=NetworkPolicy.allow_ports([8080]))

    # And it is a ValueError, so the proxy's setup-refusal path (which catches
    # (ValueError, UnsupportedPlatform)) surfaces it as a clean exit-2 refusal.
    assert issubclass(linux.NetworkPolicyUnsupported, ValueError)


# --- the seccomp filter -----------------------------------------------------


def test_seccomp_program_is_deterministic() -> None:
    assert linux.seccomp_program("x86_64") == linux.seccomp_program("x86_64")
    assert linux.seccomp_program("aarch64") == linux.seccomp_program("aarch64")


def test_seccomp_program_denies_ip_sockets_but_allows_unix() -> None:
    """The decision, pinned: the filter gates `socket()` on the domain — deny
    every domain except AF_UNIX — so no IP socket can exist at all (client or
    server), while unix sockets (a server's own listener) still work."""
    prog = linux.seccomp_program("x86_64")
    arch = linux.SECCOMP_ARCH_X86_64

    assert _simulate(prog, 41, arch, (2,)) == _SECCOMP_RET_ERRNO | _EPERM  # AF_INET
    assert _simulate(prog, 41, arch, (10,)) == _SECCOMP_RET_ERRNO | _EPERM  # AF_INET6
    assert _simulate(prog, 41, arch, (16,)) == _SECCOMP_RET_ERRNO | _EPERM  # AF_NETLINK
    assert _simulate(prog, 41, arch, (1,)) == _SECCOMP_RET_ALLOW  # AF_UNIX
    # Only the domain decides; the socket type/protocol arguments are not
    # consulted (a datagram unix socket is still a unix socket).
    assert _simulate(prog, 41, arch, (1, 2, 0)) == _SECCOMP_RET_ALLOW


def test_seccomp_program_denies_outbound_syscalls_unconditionally() -> None:
    """The "no outbound on any socket" half of `(deny network*)` — including
    unix-socket connects, which the macOS profile also refuses (`network-bind`
    is granted, `network-outbound` is not)."""
    prog = linux.seccomp_program("aarch64")
    arch = linux.SECCOMP_ARCH_AARCH64

    # connect (203), sendto (206), sendmsg (211), sendmmsg (269) on aarch64.
    for nr in (203, 206, 211, 269):
        assert _simulate(prog, nr, arch, (1, 0, 0, 0, 0, 0)) == _SECCOMP_RET_ERRNO | _EPERM

    # socketpair (199) is allowed: Python's subprocess/asyncio plumbing uses it.
    assert _simulate(prog, 199, arch, (1, 1, 0, 0, 0, 0)) == _SECCOMP_RET_ALLOW


def test_seccomp_program_lets_ordinary_syscalls_through() -> None:
    prog = linux.seccomp_program("x86_64")
    arch = linux.SECCOMP_ARCH_X86_64

    for nr in (0, 1, 2, 3, 39, 56, 59, 157, 257, 293):  # read..openat/execve/prctl
        assert _simulate(prog, nr, arch, ()) == _SECCOMP_RET_ALLOW


def test_seccomp_program_fails_closed_on_an_unknown_arch() -> None:
    """A 32-bit (or x32) child under a 64-bit filter must not slip through the
    decisions: the arch gate returns ENOSYS on every syscall — fail closed."""
    prog = linux.seccomp_program("x86_64")
    # AUDIT_ARCH_I386 — a 32-bit binary's syscalls would carry this arch.
    assert _simulate(prog, 41, 0x40000003, (1,)) == _SECCOMP_RET_ERRNO | _ENOSYS


def test_seccomp_program_refuses_architectures_without_a_table() -> None:
    with pytest.raises(UnsupportedPlatform, match="seccomp"):
        linux.seccomp_program("riscv64")


def test_seccomp_program_has_the_pinned_length() -> None:
    """20 instructions: arch gate, socket/domain decision, socketpair,
    the four denied outbound syscalls, and the allow fallthrough. The length
    is pinned so a silent edit to the decision shows up as a diff here."""
    assert len(linux.seccomp_program("x86_64")) == 20
    assert len(linux.seccomp_program("aarch64")) == 20


# --- denial classification (EACCES / EPERM, both inferred) -------------------


def test_an_eacces_filesystem_line_is_a_denial_naming_the_path() -> None:
    denials = linux._denials_from_stderr(
        b"sh: cannot create /tmp/out/x.txt: Permission denied\n"
    )
    assert len(denials) == 1
    assert denials[0].op == "file-write"
    assert denials[0].path == "/tmp/out/x.txt"
    assert "Permission denied" in denials[0].detail


def test_an_eperm_network_line_is_a_denial_with_a_network_op() -> None:
    denials = linux._denials_from_stderr(
        b"Traceback (most recent call last):\n"
        b'  File "x", line 1, in <module>\n'
        b"PermissionError: [Errno 1] Operation not permitted\n"
    )
    assert len(denials) == 1
    assert denials[0].op == "network"
    assert denials[0].path is None
    assert "Operation not permitted" in denials[0].detail


def test_an_eacces_line_without_a_path_reports_unknown_op() -> None:
    denials = linux._denials_from_stderr(b"ls: cannot open directory 'x': Permission denied\n")
    assert len(denials) == 1
    assert denials[0].op == "unknown"
    assert denials[0].path is None


def test_clean_stderr_records_no_denial() -> None:
    assert linux._denials_from_stderr(b"hello\nworld\n") == ()


def test_an_ordinary_non_denial_error_records_no_denial() -> None:
    assert linux._denials_from_stderr(b"sh: 1: command not found: nope\n") == ()


def test_denial_lines_keep_the_verbatim_line_as_detail() -> None:
    line = "sh: cannot create /etc/pwned: Permission denied"
    denials = linux._denials_from_stderr(line.encode() + b"\n")
    assert denials[0].detail == line


# --- the denial record shape is platform-stable ------------------------------


def test_denial_records_have_the_platform_stable_shape(tmp_path: Path) -> None:
    """Field-for-field what macOS writes: same kind, same provenance
    (`inferred: true, source: "child-stderr"`), same derived `path`. Only the
    marker text in `detail` differs — the ambiguity is documented in linux.py's
    module docstring, and the record says it is inferred either way."""
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        denials = linux._denials_from_stderr(b"sh: cannot create /tmp/out/x.txt: Permission denied\n")
        linux.record_denials(writer, denials)
    finally:
        writer.close()

    records = [r for r in read_trace(tmp_path / "trace") if r.get("kind") == "denial"]
    assert len(records) == 1
    record = records[0]
    assert record["op"] == "file-write"
    assert record["path"] == "/tmp/out/x.txt"
    assert record["inferred"] is True
    assert record["source"] == "child-stderr"


def test_network_policy_is_recorded_as_a_fact_on_linux(tmp_path: Path) -> None:
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        writer.record("network_policy", policy="deny-all", ports=[])
    finally:
        writer.close()

    policies = [r for r in read_trace(tmp_path / "trace") if r.get("kind") == "network_policy"]
    assert len(policies) == 1
    assert policies[0]["policy"] == "deny-all"


# --- the launcher argv ------------------------------------------------------


def test_launcher_argv_shape() -> None:
    """`python -m belay.sandbox.linux <policy> -- <command>` — the launcher
    installs the filters and execs the command, so the argv Popen spawns IS the
    contained process."""
    argv = linux.launcher_argv(["srv", "--flag"], policy_path="/tmp/policy.json")

    assert argv[:3] == [sys.executable, "-m", "belay.sandbox.linux"]
    assert argv[3] == "/tmp/policy.json"
    assert argv[4] == "--"
    assert argv[5:] == ["srv", "--flag"]


def test_launcher_argv_needs_a_command() -> None:
    with pytest.raises(ValueError, match="command"):
        linux.launcher_argv([], policy_path="/tmp/policy.json")


# --- availability: never a silent downgrade ----------------------------------


def test_landlock_unavailable_raises_with_a_named_cause(monkeypatch) -> None:
    monkeypatch.setattr(linux, "landlock_abi", lambda: None)
    with pytest.raises(UnsupportedPlatform, match="[Ll]andlock"):
        linux.ensure_available()


def test_the_backend_is_reachable_through_the_seam() -> None:
    assert sandbox.backend_for("linux") is linux
