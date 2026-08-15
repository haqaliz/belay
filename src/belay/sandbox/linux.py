"""Run a subprocess inside a Linux containment boundary, and record what it was refused.

The Linux half of C2, mirroring `seatbelt.py`'s responsibilities for the
mechanism aspect A1 measured and decided
(`docs/planning/linux-sandbox/containment-spike/decision.md`): **Landlock** for
the filesystem write scope (kernel-native, zero runtime dependencies — the
`pyproject.toml` zero-dep contract survives by construction, since everything
below goes through `ctypes` syscalls 444/445/446) and **seccomp** for network
deny-all (EPERM to the child on refusal).

**The same rule this module is written against as `seatbelt.py`: never claim a
boundary we do not enforce.** The launcher below is the gate: if either
mechanism cannot be applied, it exits non-zero WITHOUT exec'ing the command —
"mechanism absent ⇒ refused", never a bare spawn that reads like a contained
one. `allow-ports` is refused before anything spawns, because Landlock's net
domain scopes TCP by port only and has no address scope: a port grant would be
a *looser* boundary than the closed vocabulary claims, so the mode degrades to
a named-cause `NetworkPolicyUnsupported` (surfaced by the proxy as a clean
refusal, exit 2), never a silent widening.

**How the boundary is applied.** `run()` and `launch.contained` compose the
argv `python -m belay.sandbox.linux <policy.json> -- <command>`: the launcher
reads the policy (the JSON write roots + network mode — the Linux `profile`),
sets `PR_SET_NO_NEW_PRIVS`, installs a Landlock ruleset granting WRITE-side
access only beneath the write roots, and for `deny-all` installs a seccomp
filter, then `execvp`s the command. The filters are inherited across
fork/exec, so grandchildren are contained exactly as the macOS profile
contains them. Landlock only ever *restricts* the rights its ruleset handles:
the ruleset handles the write rights and nothing else, so reads stay
unrestricted — the same honest "contains what the child can change, not what
it can see" claim `seatbelt.py` makes.

**The seccomp filter decision** (pinned byte-for-byte by
`tests/test_linux_policy.py`, proven by `tests/test_linux_containment.py`):
`socket()` is allowed ONLY for domain AF_UNIX and refused EPERM for every
other domain — no IP socket can exist at all, client or server — and
`socketpair()` is allowed (the subprocess/asyncio staple). `connect`,
`sendto`, `sendmsg`, `sendmmsg` are refused EPERM unconditionally: the
"no outbound on any socket" half of the macOS `(deny network*)` boundary,
which also refuses unix-socket connects (`network-bind` is granted,
`network-outbound` is not). Everything else is allowed, and a syscall whose
arch does not match the filter's own reads ENOSYS — fail closed, never a
silent bypass.

**Denial provenance, with the ambiguity the decision records.** Filesystem
refusals are Landlock's EACCES — *the same text an ordinary chmod produces* —
so inside this boundary an EACCES line is *consistent with* a denial but not
*proof* of one; the record keeps the identical shape (`inferred: true,
source: "child-stderr"`) and says so. Network refusals are seccomp's EPERM,
which is the macOS-style marker. The kernel-source upgrade is deferred (N1),
and is the only path to provable rather than inferred filesystem denials.

Not implemented: platforms other than Linux (this module raises
`UnsupportedPlatform` off Linux, mirroring `seatbelt.run` off darwin),
architectures without a seccomp syscall table (x86_64/aarch64 only), and
Landlock ABI 4+'s net domain (that is precisely the inexpressibility that
makes `allow-ports` refuse).
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence
from belay.sandbox.seatbelt import (
    _PATH_TOKEN,
    Denial,
    NetworkPolicy,
    SandboxResult,
    UnsupportedPlatform,
    record_denials,
)
from belay.trace import TraceWriter

__all__ = [
    "FS_EXECUTE",
    "FS_MAKE_BLOCK",
    "FS_MAKE_CHAR",
    "FS_MAKE_DIR",
    "FS_MAKE_FIFO",
    "FS_MAKE_REG",
    "FS_MAKE_SOCK",
    "FS_MAKE_SYM",
    "FS_READ_DIR",
    "FS_READ_FILE",
    "FS_REFER",
    "FS_REMOVE_DIR",
    "FS_REMOVE_FILE",
    "FS_TRUNCATE",
    "FS_WRITE_FILE",
    "NetworkPolicyUnsupported",
    "SECCOMP_ARCH_AARCH64",
    "SECCOMP_ARCH_X86_64",
    "Denial",
    "NetworkPolicy",
    "SandboxResult",
    "UnsupportedPlatform",
    "ensure_available",
    "fs_write_access",
    "landlock_abi",
    "launcher_argv",
    "main",
    "policy_text",
    "record_denials",
    "run",
    "seccomp_program",
]

#: The three Landlock syscalls. 444/445/446 on x86_64 and the generic syscall
#: table (verified against syscall_64.tbl and asm-generic/unistd.h by the A1
#: probe); landlock has never been a prctl interface in a released kernel.
_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446

_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1

#: prctl(2) constants (linux/prctl.h).
_PR_SET_NO_NEW_PRIVS = 38
_PR_SET_SECCOMP = 22
_SECCOMP_MODE_FILTER = 2

#: seccomp return values (linux/seccomp.h).
_SECCOMP_RET_ALLOW = 0x7FFF0000
_SECCOMP_RET_ERRNO = 0x00050000

#: The LINUX errno values the filter returns, spelled out because they travel
#: as bytes inside the filter program: `errno.ENOSYS` differs by host (38 on
#: Linux, 78 on macOS), and the filter must return the value the KERNEL of the
#: contained child reads, not the value the filter-building host happens to use.
_EPERM = 1
_ENOSYS = 38

#: `audit` architecture identifiers (linux/audit.h): __AUDIT_ARCH_64BIT |
#: __AUDIT_ARCH_LE | the machine's EM constant.
SECCOMP_ARCH_X86_64 = 0xC000003E  # EM_X86_64 (62)
SECCOMP_ARCH_AARCH64 = 0xC00000B7  # EM_AARCH64 (183)

#: AF_UNIX. The one socket domain a contained process may create.
_AF_UNIX = 1

#: LANDLOCK_ACCESS_FS_* bits (linux/landlock.h). Only the WRITE-side rights
#: this backend handles are listed — read/execute stay unhandled and therefore
#: unrestricted, mirroring the macOS profile's wholesale `(allow file-read*)`.
FS_EXECUTE = 1 << 0
FS_WRITE_FILE = 1 << 1
FS_READ_FILE = 1 << 2
FS_READ_DIR = 1 << 3
FS_REMOVE_DIR = 1 << 4
FS_REMOVE_FILE = 1 << 5
FS_MAKE_CHAR = 1 << 6
FS_MAKE_DIR = 1 << 7
FS_MAKE_REG = 1 << 8
FS_MAKE_SOCK = 1 << 9
FS_MAKE_FIFO = 1 << 10
FS_MAKE_BLOCK = 1 << 11
FS_MAKE_SYM = 1 << 12
FS_REFER = 1 << 13  # ABI >= 2: link/rename
FS_TRUNCATE = 1 << 14  # ABI >= 3: open(O_TRUNC) / truncate()

_FS_WRITE_BASE = (
    FS_WRITE_FILE
    | FS_REMOVE_DIR
    | FS_REMOVE_FILE
    | FS_MAKE_CHAR
    | FS_MAKE_DIR
    | FS_MAKE_REG
    | FS_MAKE_SOCK
    | FS_MAKE_FIFO
    | FS_MAKE_BLOCK
    | FS_MAKE_SYM
)

#: The seccomp syscall numbers per supported architecture. A machine without a
#: table gets a named-cause refusal, never a filter built for the wrong table.
_SYSCALLS: dict[str, dict] = {
    "x86_64": {
        "arch": SECCOMP_ARCH_X86_64,
        "socket": 41,
        "socketpair": 53,
        "connect": 42,
        "sendto": 44,
        "sendmsg": 46,
        "sendmmsg": 307,
    },
    "aarch64": {
        "arch": SECCOMP_ARCH_AARCH64,
        "socket": 198,
        "socketpair": 199,
        "connect": 203,
        "sendto": 206,
        "sendmsg": 211,
        "sendmmsg": 269,
    },
}

#: The child's own report of a refusal. Landlock answers EACCES ("Permission
#: denied") for filesystem denials and seccomp answers EPERM ("Operation not
#: permitted") for network denials; both are read as denials, and the EACCES
#: ambiguity (an ordinary chmod says the same thing) is stated in the module
#: docstring and in every record's `inferred: true` provenance.
_NETWORK_MARKER = "Operation not permitted"
_FILESYSTEM_MARKER = "Permission denied"

_libc = ctypes.CDLL(None, use_errno=True)
_libc.syscall.restype = ctypes.c_long


class NetworkPolicyUnsupported(ValueError):
    """A closed-vocabulary mode the Linux mechanism cannot express.

    A ValueError so the proxy's setup-refusal path — which catches
    `(ValueError, UnsupportedPlatform)` — surfaces it as a clean refusal
    (exit 2) before the first byte moves. See `policy_text`.
    """


class _RulesetAttr(ctypes.Structure):
    # 16 bytes: handled_access_fs + handled_access_net (ABI 4+). Passing the
    # full struct with the net half zero works on every ABI (the kernel
    # verifies the excess bytes are zero, it does not reject a larger size).
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
    ]


class _PathBeneath(ctypes.Structure):
    # Packed, exactly as the A1 probe measured it: the kernel's ABI check
    # asserts 12 bytes — allowed_access (8) + parent_fd (4), no padding.
    _pack_ = 1
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


class _SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_uint16),
        ("jt", ctypes.c_uint8),
        ("jf", ctypes.c_uint8),
        ("k", ctypes.c_uint32),
    ]


class _SockFprog(ctypes.Structure):
    _fields_ = [
        ("len", ctypes.c_uint16),
        ("filter", ctypes.POINTER(_SockFilter)),
    ]


def fs_write_access(abi: int) -> int:
    """The LANDLOCK_ACCESS_FS_* bits this backend handles, for the given ABI.

    Only write-side rights are handled; REFER (link/rename, ABI >= 2) and
    TRUNCATE (ABI >= 3) are added when the kernel can express them. The mask is
    what the ruleset declares as `handled_access_fs`, and every path-beneath
    rule grants exactly it — so the boundary is "these write rights, beneath
    these roots", and nothing else is restricted at all.
    """
    access = _FS_WRITE_BASE
    if abi >= 2:
        access |= FS_REFER
    if abi >= 3:
        access |= FS_TRUNCATE
    return access


def _syscall(number: int, *args) -> int:
    return _libc.syscall(number, *args)


def landlock_abi() -> Optional[int]:
    """The kernel's Landlock ABI (an int >= 1), or None when unavailable.

    The version probe — `landlock_create_ruleset(NULL, 0,
    LANDLOCK_CREATE_RULESET_VERSION)` — returns the ABI number on kernels with
    Landlock enabled (>= 5.13 with the LSM loaded), and fails on every kernel
    without it: ENOSYS (no Landlock syscall), EOPNOTSUPP (the LSM is compiled
    out), or — off Linux, where syscall 444 is some OTHER syscall — whatever
    that syscall does with these arguments. Every failure reads the same:
    "no usable Landlock ABI could be determined here", which is sufficient
    ground for the named-cause refusal `ensure_available` raises. Nothing is
    guessed from an errno that may not even be Linux's.
    """
    rc = _syscall(_LANDLOCK_CREATE_RULESET, 0, 0, _LANDLOCK_CREATE_RULESET_VERSION)
    if rc < 0:
        return None
    return int(rc)


def ensure_available() -> None:
    """Raise `UnsupportedPlatform` (named cause) when Landlock cannot contain here.

    Called before anything spawns: a kernel without Landlock must refuse the
    sandbox with a name, never run the command bare. The launcher repeats this
    check at the point of exec, so the gate holds even if a caller forgets.
    """
    if landlock_abi() is None:
        raise UnsupportedPlatform(
            "Landlock is unavailable on this kernel: the ABI probe did not "
            "answer (no Landlock syscall, or the LSM is disabled), so Belay "
            "cannot contain filesystem writes here. Refusing rather than "
            "running the command unsandboxed — a no-op that returned success "
            "would be Belay claiming a containment boundary that does not "
            "exist on this platform."
        )


def _resolved_scope(scope: Path | str) -> str:
    """The scope as the kernel sees it, or an error. Mirrors `seatbelt`."""
    resolved = os.path.realpath(str(scope))
    if not os.path.isdir(resolved):
        raise ValueError(
            f"sandbox scope {str(scope)!r} does not exist (resolved to {resolved!r}). "
            f"It must exist before the policy is built: realpath() cannot resolve a "
            f"path that is not there, and an unresolved subpath silently grants nothing."
        )
    return resolved


def _write_scopes(scope: Path | str | Sequence[Path | str]) -> list[str]:
    """Resolve `scope` to the write-root paths, in the order given. Mirrors
    `seatbelt._write_scopes` (one tree or several; duplicates dropped)."""
    paths: Sequence[Path | str]
    if isinstance(scope, (str, Path)):
        paths = [scope]
    else:
        paths = list(scope)
        if not paths:
            raise ValueError(
                "a policy with no write scope grants nothing writable at all; "
                "pass the tree the child may change"
            )
    resolved: list[str] = []
    for path in paths:
        real = _resolved_scope(path)
        if real not in resolved:
            resolved.append(real)
    return resolved


def policy_text(*, scope: Path | str | Sequence[Path | str], network: NetworkPolicy) -> str:
    """The policy artifact as JSON: the write roots and the network mode.

    This is the Linux `profile` — what `Contained.profile` and
    `SandboxResult.profile` carry, and the instruction file the launcher reads.
    `allow-ports` is refused HERE, before anything spawns, with the decision's
    reason: Landlock's net domain scopes TCP by port only and has no address
    scope, so a port grant would be a looser boundary than the closed
    vocabulary claims. `deny-all` and `allow-all` encode directly.
    """
    if network.mode == "allow-ports":
        raise NetworkPolicyUnsupported(
            f"network policy {network.mode!r} with ports {network.ports} cannot be "
            f"expressed on Linux: Landlock's net domain restricts TCP by PORT only "
            f"and has no address scope, so a port grant would be a looser boundary "
            f"than the closed vocabulary claims. Refusing rather than silently "
            f"widening — use deny-all (the default) or allow-all."
        )
    roots = _write_scopes(scope)
    return json.dumps({"version": 1, "write_roots": roots, "network": network.mode})


def seccomp_program(machine: str) -> tuple[tuple[int, int, int, int], ...]:
    """The network deny-all BPF filter, as (code, jt, jf, k) instructions.

    See the module docstring for the decision. The program is pure data —
    deterministic, testable on any platform — and `_apply_seccomp` loads it
    into the kernel. A machine with no syscall table is refused with a cause:
    a filter built for the wrong table would be a boundary that never fires.
    """
    table = _SYSCALLS.get(machine)
    if table is None:
        raise UnsupportedPlatform(
            f"the seccomp network filter has a syscall table for x86_64 and "
            f"aarch64, not for {machine!r}. Refusing rather than running "
            f"unsandboxed: a filter built for the wrong table is a boundary "
            f"that never fires."
        )
    arch = table["arch"]
    allow = _SECCOMP_RET_ALLOW
    eperm = _SECCOMP_RET_ERRNO | _EPERM
    enosys = _SECCOMP_RET_ERRNO | _ENOSYS
    ld, jeq, ret = 0x20, 0x15, 0x06
    return (
        (ld, 0, 0, 4),  # 0  A = arch (seccomp_data offset 4)
        (jeq, 1, 0, arch),  # 1  arch matches -> skip the ENOSYS gate
        (ret, 0, 0, enosys),  # 2  wrong arch: every syscall reads ENOSYS
        (ld, 0, 0, 0),  # 3  A = nr (seccomp_data offset 0)
        (jeq, 0, 4, table["socket"]),  # 4  socket -> 5; else skip to 9
        (ld, 0, 0, 16),  # 5  A = args[0] (the domain)
        (jeq, 0, 1, _AF_UNIX),  # 6  AF_UNIX -> 7; else 8
        (ret, 0, 0, allow),  # 7  unix socket: allow
        (ret, 0, 0, eperm),  # 8  any other domain: EPERM
        (jeq, 0, 1, table["socketpair"]),  # 9  socketpair -> 10; else 11
        (ret, 0, 0, allow),  # 10
        (jeq, 0, 1, table["connect"]),  # 11 connect -> 12; else 13
        (ret, 0, 0, eperm),  # 12
        (jeq, 0, 1, table["sendto"]),  # 13
        (ret, 0, 0, eperm),  # 14
        (jeq, 0, 1, table["sendmsg"]),  # 15
        (ret, 0, 0, eperm),  # 16
        (jeq, 0, 1, table["sendmmsg"]),  # 17
        (ret, 0, 0, eperm),  # 18
        (ret, 0, 0, allow),  # 19  everything else
    )


def launcher_argv(command: Sequence[str], *, policy_path: str) -> list[str]:
    """`command`, prefixed so spawning the argv runs it CONTAINED.

    The launcher is the Linux equivalent of `sandbox-exec -f <profile>`: it
    installs the filters and execs the command, so the argv a `Popen` spawns
    IS the contained process. `policy_path` names the JSON the launcher reads
    (the `profile` written beside it).
    """
    if not command:
        raise ValueError("launcher_argv needs a command to wrap")
    return [sys.executable, "-m", "belay.sandbox.linux", policy_path, "--", *command]


def _apply_landlock(write_roots: Sequence[str]) -> None:
    """Install the Landlock ruleset: write rights beneath each root, then
    `restrict_self`. Runs in the launcher, before exec."""
    abi = landlock_abi()
    if abi is None:
        raise OSError(
            _ENOSYS,
            "Landlock unavailable: the ABI probe did not answer",
            "landlock_create_ruleset(version)",
        )
    handled = fs_write_access(abi)
    attr = _RulesetAttr(handled_access_fs=handled, handled_access_net=0)
    ruleset = _syscall(_LANDLOCK_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if ruleset < 0:
        raise OSError(
            ctypes.get_errno(), os.strerror(ctypes.get_errno()), "landlock_create_ruleset"
        )
    try:
        for root in write_roots:
            parent = os.open(root, os.O_RDONLY | os.O_CLOEXEC)
            try:
                rule = _PathBeneath(allowed_access=handled, parent_fd=parent)
                if (
                    _syscall(
                        _LANDLOCK_ADD_RULE, ruleset, _LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(rule), 0
                    )
                    < 0
                ):
                    raise OSError(
                        ctypes.get_errno(),
                        os.strerror(ctypes.get_errno()),
                        f"landlock_add_rule({root})",
                    )
            finally:
                os.close(parent)
        if _syscall(_LANDLOCK_RESTRICT_SELF, ruleset, 0) < 0:
            raise OSError(
                ctypes.get_errno(), os.strerror(ctypes.get_errno()), "landlock_restrict_self"
            )
    finally:
        os.close(ruleset)


def _apply_seccomp(machine: str) -> None:
    """Install the network deny-all filter via prctl(PR_SET_SECCOMP). Runs in
    the launcher, after Landlock, before exec. (no_new_privs is set first by
    the caller, which is what makes the filter persist across the exec.)"""
    program = seccomp_program(machine)
    filters = (_SockFilter * len(program))()
    for i, (code, jt, jf, k) in enumerate(program):
        filters[i].code = code
        filters[i].jt = jt
        filters[i].jf = jf
        filters[i].k = k
    fprog = _SockFprog(len(program), ctypes.cast(filters, ctypes.POINTER(_SockFilter)))
    if (
        _libc.prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.byref(fprog), 0, 0) != 0
    ):
        raise OSError(
            ctypes.get_errno(), os.strerror(ctypes.get_errno()), "prctl(PR_SET_SECCOMP)"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """The launcher: `python -m belay.sandbox.linux <policy.json> -- <command> …`.

    Reads the policy, installs the filters — no_new_privs, then Landlock, then
    (for `deny-all`) seccomp — and `execvp`s the command. Any failure along
    the way exits non-zero WITHOUT exec'ing: this is the gate that makes
    "mechanism absent ⇒ refused, never bare" true at the point of spawn, not
    just in the callers' error paths.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    usage = "usage: python -m belay.sandbox.linux <policy.json> -- <command> [args...]"
    try:
        sep = argv.index("--")
    except ValueError:
        print(usage, file=sys.stderr)
        return 2
    policy_arg, command = argv[:sep], argv[sep + 1 :]
    if len(policy_arg) != 1 or not command:
        print(usage, file=sys.stderr)
        return 2
    try:
        policy = json.loads(Path(policy_arg[0]).read_text())
    except (OSError, ValueError) as exc:
        print(f"belay: refusing to run unsandboxed: could not read the policy: {exc}", file=sys.stderr)
        return 2
    if (
        policy.get("version") != 1
        or not isinstance(policy.get("write_roots"), list)
        or policy.get("network") not in ("deny-all", "allow-all")
    ):
        print(
            "belay: refusing to run unsandboxed: malformed policy "
            f"{json.dumps(policy)[:200]}",
            file=sys.stderr,
        )
        return 2
    try:
        if _libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(
                ctypes.get_errno(), os.strerror(ctypes.get_errno()), "prctl(PR_SET_NO_NEW_PRIVS)"
            )
        _apply_landlock(policy["write_roots"])
        if policy["network"] == "deny-all":
            _apply_seccomp(platform.machine())
    except Exception as exc:  # noqa: BLE001
        print(f"belay: refusing to run unsandboxed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    try:
        os.execvp(command[0], list(command))
    except OSError as exc:
        print(f"belay: could not exec {command[0]}: {exc}", file=sys.stderr)
        return 2
    return 0


def _strip_quotes(token: str) -> str:
    """Remove the quote GNU coreutils wraps around a path in its diagnostics.

    ``mv: cannot move '/a' to '/b': Permission denied`` — the tokenizer's
    `\\S*` captures the trailing quote as part of the token. The quote is
    stripped ONLY when the token contains no other instance of that quote
    character, i.e. when the quote cannot plausibly be part of the path
    itself; a genuinely quote-terminated path keeps its quote and the record
    reports it as the child wrote it. The `detail` field keeps the verbatim
    line either way — this is the path field being cleaned, never the record
    being rewritten.
    """
    if token and token[-1] in ("'", '"') and token.count(token[-1]) == 1:
        return token[:-1]
    return token


def _denials_from_stderr(stderr: bytes) -> tuple[Denial, ...]:
    """Read the child's own complaints back as denial records.

    The Linux version of `seatbelt._denials_from_stderr`, with the decision's
    two markers: EACCES ("Permission denied") for Landlock filesystem denials
    and EPERM ("Operation not permitted") for seccomp network denials. The
    provenance claim is exactly the macOS one — the child reported a
    permission error, NOT the kernel told us it denied X — so every record is
    `inferred: true, source: "child-stderr"` with the verbatim line as
    `detail`. The EACCES ambiguity is real and documented in the module
    docstring: inside a Landlock boundary an EACCES is consistent with a
    denial but not proof of one.
    """
    denials: list[Denial] = []
    for raw_line in stderr.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        network = _NETWORK_MARKER in line
        if not network and _FILESYSTEM_MARKER not in line:
            continue
        fields = line.split(": ")
        subject = ": ".join(fields[1:-1])
        candidates = [
            _strip_quotes(token.rstrip(":"))
            for token in _PATH_TOKEN.findall(subject)
        ]
        path = candidates[-1] if candidates else None
        if network:
            op = "network"
        elif path is not None:
            op = "file-write"
        else:
            op = "unknown"
        denials.append(Denial(op=op, path=path, detail=line))
    return tuple(denials)


def run(
    command: Sequence[str],
    *,
    scope: Path | str | Sequence[Path | str],
    network: NetworkPolicy,
    trace: Optional[TraceWriter] = None,
    cwd: Path | str | None = None,
    timeout: float | None = 30.0,
) -> SandboxResult:
    """Run `command` under the Landlock+seccomp boundary, recording refusals.

    The Linux mirror of `seatbelt.run`, with the same contract: the boundary
    is the kernel's and holds whether or not anyone writes it down; the
    records appended are FACTS — `network_policy` says which policy was
    applied, `denial` says the child reported a refusal. The scope grants
    writes beneath the write roots; reads are NOT scoped (the same honest
    limit `seatbelt.py` states).

    `allow-ports` raises `NetworkPolicyUnsupported` before anything spawns,
    and a kernel without Landlock raises `UnsupportedPlatform` with the cause
    — never a bare run. This function is run-to-completion, right for a probe
    and wrong for a proxied server; the long-lived case composes the same
    policy onto an argv instead — see `belay.sandbox.launch`.
    """
    if not sys.platform.startswith("linux"):
        raise UnsupportedPlatform(
            f"the Landlock/seccomp sandbox is Linux-only and cannot contain "
            f"anything on {sys.platform!r}. Raising rather than running the "
            f"command unsandboxed: a no-op that returned success would be "
            f"Belay claiming a containment boundary that does not exist on "
            f"this platform."
        )

    ensure_available()
    profile = policy_text(scope=scope, network=network)

    if trace is not None:
        trace.record("network_policy", policy=network.mode, ports=list(network.ports))

    handle, profile_path = tempfile.mkstemp(prefix="belay-sandbox-", suffix=".json")
    try:
        with os.fdopen(handle, "w") as fh:
            fh.write(profile)
        completed = subprocess.run(
            launcher_argv(command, policy_path=profile_path),
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


if __name__ == "__main__":
    sys.exit(main())
