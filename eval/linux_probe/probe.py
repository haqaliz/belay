"""The containment probe: measure what a stock GitHub runner can actually enforce.

Aspect A1 of the `linux-sandbox` slice (`docs/planning/linux-sandbox/
containment-spike/spec.md`): the Linux mechanism is **unmeasured**, and
everything downstream (A2 containment, A3 snapshot, A4 CI/docs) depends on
knowing, from an actual measurement on the CI substrate, which mechanism can
enforce the boundary there. This module is that measurement; it commits to
nothing until it runs.

**The rule this module is written against is the repo's: measured, never
assumed.** Every probe either measures a value or reports `unavailable` (or
`absent` / `restricted` / `not-expressible`) with a `reason` — no probe may be
skipped silently, and `main()` exits 0 even when every mechanism is
unavailable, because an unavailable mechanism IS a measurement. The job fails
only when the probe itself crashes or emits an artifact that fails its own
schema (`validate_result`): a malformed artifact would be worse than none,
because the decision cites it.

**Determinism is a contract, not a preference.** The artifact must be
byte-identical across two runs on the same runner image (spec criterion 3, and
the CI double-run diff asserts it). There are no timestamps; the env record
(`probe_env`) is the substrate the measurement was made on, including the
runner image tag, so a decision cannot cite a stale artifact. Scratch paths
that would leak into recorded stderr are scrubbed (`_scrub`); nothing random
or time-varying enters the JSON.

**One deliberate deviation from the implementation plan, recorded here.**
The plan (`plan_20260815.md`) directs `prctl(PR_LANDLOCK_CREATE_RULESET)`.
That is the pre-merge RFC-era interface: landlock shipped in Linux 5.13 as
dedicated syscalls (`landlock_create_ruleset` = 444, `landlock_add_rule` =
445, `landlock_restrict_self` = 446 — verified against the kernel's
`arch/x86/entry/syscalls/syscall_64.tbl` and `include/uapi/asm-generic/
unistd.h` at v5.13, v6.3 and v6.8; no released kernel ever had a prctl
interface). The probe measures the real interface; the prctl numbers would
have read `EINVAL` on the pinned image's 6.8 kernel and reported a false
"unavailable". `PR_SET_NO_NEW_PRIVS` (38) is prctl and survives — that is
still how the no_new_privs flag is set.

**What the probes measure, and why their vocabulary is closed.** Each probe
dict has a `status` from `STATUS_VOCABULARY` plus a `reason` whenever the
status is not `ok`. The vocabulary is closed because the decision reads it:
a status invented mid-probe is a status the decision cannot interpret.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback

OUTPUT_FILENAME = "probe_result.json"

# A CLOSED vocabulary, for the reason in the module docstring: the decision
# cites these, so a probe that invents a status is a probe that cannot be read.
STATUS_VOCABULARY = frozenset(
    {
        "ok",
        "unavailable",
        "absent",
        "restricted",
        "not-expressible",
        "not-expressible-without-netns-tools",
    }
)

# The five probes the spec names; the validator requires exactly this set.
PROBE_NAMES = (
    "unshare_userns",
    "bwrap",
    "landlock",
    "allow_ports_mapping",
    "denial_marker",
)

ENV_KEYS = (
    "platform",
    "release",
    "version",
    "machine",
    "python",
    "RUNNER_OS",
    "GITHUB_RUNNER_IMAGE",
)

# Kernel errno values, named so the artifact reads without a table lookup.
_ERRNO_NAMES = {
    1: "EPERM",
    2: "ENOENT",
    7: "E2BIG",
    13: "EACCES",
    14: "EFAULT",
    22: "EINVAL",
    38: "ENOSYS",
    95: "EOPNOTSUPP",
    97: "EAFNOSUPPORT",
}

# --- denial-marker classification -------------------------------------------

# The order is deliberate and mirrors `seatbelt.py`'s `_DENIAL_MARKER`
# discipline: "Operation not permitted" is the recognized sandbox-denial
# marker, so when a child reports several texts the classification is the
# sandbox's. EACCES ("Permission denied") is ordinary filesystem permissions —
# seatbelt deliberately does NOT treat it as a sandbox denial — and EROFS
# ("Read-only file system") is the marker a read-only bind mount produces
# (bwrap's boundary), which an ordinary chmod can never produce.
_MARKER_EPERM = "Operation not permitted"
_MARKER_EACCES = "Permission denied"
_MARKER_EROFS = "Read-only file system"


def classify_denial_marker(stderr: str) -> str:
    """Classify refusal text into its errno family, or "unknown".

    `unknown` is a real answer: a classification that guessed would dress an
    ordinary error up as a denial, which is the conflation this repo exists to
    avoid. Case-sensitive, like the kernel's fixed errno text.
    """
    if _MARKER_EPERM in stderr:
        return "EPERM"
    if _MARKER_EACCES in stderr:
        return "EACCES"
    if _MARKER_EROFS in stderr:
        return "EROFS"
    return "unknown"


# --- pure helpers ------------------------------------------------------------


def parse_kernel_release(release: str) -> tuple[int, int] | None:
    """`os.uname().release` like "6.8.0-1021-azure" -> (6, 8), or None.

    None is reported, never silently skipped: the release parse is context
    for the landlock probe, whose verdict comes from the syscall attempt —
    the parse can only corroborate or contradict.
    """
    parts = release.split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def kernel_supports_landlock(parsed: tuple[int, int] | None) -> bool:
    """Whether a parsed release is at or above the 5.13 landlock floor.

    A hint, never the verdict: the probe measures the syscall directly, and an
    unparseable release reads False — a boundary the artifact must show, not a
    value the probe gets to guess.
    """
    return parsed is not None and parsed >= (5, 13)


def shape_env(
    *,
    platform_str: str,
    release: str,
    version: str,
    machine: str,
    python_version: str,
    runner_os: str | None,
    runner_image: str | None,
) -> dict:
    """The env record: the substrate the measurement was made on.

    `runner_os` / `runner_image` are null when the variable was unset — null
    is JSON's explicit absence, and it stays distinguishable from a set-but-
    empty value (which records ""). Same inputs, same dict: the env record is
    deterministic on the same image.
    """
    return {
        "platform": platform_str,
        "release": release,
        "version": version,
        "machine": machine,
        "python": python_version,
        "RUNNER_OS": runner_os,
        "GITHUB_RUNNER_IMAGE": runner_image,
    }


def probe_env() -> dict:
    """Collect the env record. No timestamps: the artifact must re-run to the
    byte on the same image (spec criterion 3)."""
    uname = os.uname()
    return shape_env(
        platform_str=platform.platform(),
        release=uname.release,
        version=uname.version,
        machine=uname.machine,
        python_version=platform.python_version(),
        runner_os=os.environ.get("RUNNER_OS"),
        runner_image=os.environ.get("GITHUB_RUNNER_IMAGE"),
    )


def validate_result(result: dict) -> list[str]:
    """Every rule the artifact must satisfy, as a list of violations.

    `main()` refuses to write an artifact that fails this — the decision cites
    the artifact, so a malformed one is worse than none. The probe set is
    closed (a new probe must be added here, and to its tests, deliberately);
    every probe carries a known `status`; every non-ok status carries a
    non-empty `reason`.
    """
    violations: list[str] = []
    if not isinstance(result, dict):
        return ["result is not a dict"]
    if set(result) != {"env", "probes"}:
        violations.append(f"top-level keys must be exactly ['env', 'probes'], got {sorted(result)}")
    env = result.get("env")
    if not isinstance(env, dict):
        violations.append("'env' is missing or not a dict")
    else:
        for key in ENV_KEYS:
            if key not in env:
                violations.append(f"env is missing {key!r}")
            elif env[key] is not None and not isinstance(env[key], str):
                violations.append(
                    f"env[{key!r}] must be a string or null, got {type(env[key]).__name__}"
                )
    probes = result.get("probes")
    if not isinstance(probes, dict):
        violations.append("'probes' is missing or not a dict")
    else:
        for name in PROBE_NAMES:
            if name not in probes:
                violations.append(f"probes is missing {name!r}")
        for name, probe in probes.items():
            if name not in PROBE_NAMES:
                violations.append(f"probes has an unknown key {name!r}; the probe set is closed")
                continue
            if not isinstance(probe, dict):
                violations.append(f"probes[{name!r}] is not a dict")
                continue
            status = probe.get("status")
            if status not in STATUS_VOCABULARY:
                violations.append(
                    f"probes[{name!r}].status {status!r} is not in the closed vocabulary "
                    f"{sorted(STATUS_VOCABULARY)}"
                )
            if status != "ok" and not (isinstance(probe.get("reason"), str) and probe["reason"]):
                violations.append(f"probes[{name!r}] has status {status!r} but no non-empty 'reason'")
    return violations


def _probe(status: str, reason: str | None = None, **fields: object) -> dict:
    probe = {"status": status}
    if reason is not None:
        probe["reason"] = reason
    probe.update(fields)
    return probe


def _errno_name(errno: int | None) -> str | None:
    return _ERRNO_NAMES.get(errno) if errno is not None else None


def _truncate(text: str, limit: int = 512) -> str:
    """Cap recorded stderr at a fixed length, deterministically."""
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _scrub(text: str, path: str) -> str:
    """Replace a probe scratch path in recorded stderr with a placeholder.

    The scratch dirs are `mkdtemp`-random; recorded verbatim, they would make
    the artifact differ between runs on the same image and fail the
    determinism diff. The refusal text that matters (the /etc write) never
    contains the scratch path; this is a determinism guard, not content.
    """
    return text.replace(path, "<scratch>")


def _run_snippet(snippet: str, *args: str, timeout: float = 30.0) -> dict:
    """Run a probe snippet in a fresh interpreter and return its JSON verdict.

    Every syscall-level attempt runs in a throwaway `sys.executable` because
    the syscalls mutate process state that must never leak into the probe
    process itself (namespaces, `no_new_privs`, landlock self-restriction) or
    into the probes that run after it. A snippet that fails to print JSON is a
    probe bug, not a measurement: it raises, and `main()` exits non-zero
    rather than recording a guess.
    """
    proc = subprocess.run(
        [sys.executable, "-c", snippet, *args],
        capture_output=True,
        timeout=timeout,
    )
    return json.loads(proc.stdout.decode("utf-8", "replace"))


# --- probe snippets (run in a fresh interpreter; stdlib only) ---------------

# The snippets print one JSON document and exit 0; outcomes travel as data, so
# a snippet crash is visible as a missing document (a probe error) rather than
# being swallowed into a status.

_UNSHARE_SNIPPET = r"""
import ctypes, json, sys

CLONE_NEWUSER = 0x10000000
CLONE_NEWNS = 0x00020000

libc = ctypes.CDLL(None, use_errno=True)
out = {"combined": None, "user_only": None}


def attempt(flags):
    if libc.unshare(flags) == 0:
        return None
    return ctypes.get_errno()


out["combined"] = attempt(CLONE_NEWUSER | CLONE_NEWNS)
if out["combined"] is not None:
    # Only meaningful when the combined attempt failed: a failed unshare
    # leaves no namespace behind, so this isolates whether the user-namespace
    # half is the blocker (EPERM there is the AppArmor restriction).
    out["user_only"] = attempt(CLONE_NEWUSER)
print(json.dumps(out))
"""

_LANDLOCK_REACH_SNIPPET = r"""
import ctypes, json, os, sys

# __NR_landlock_* are 444/445/446 on x86_64 and the generic table (verified
# against syscall_64.tbl and asm-generic/unistd.h, v5.13..v6.8). Landlock has
# never been a prctl interface in a released kernel.
SYS_CREATE = 444
SYS_ADD = 445
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_NET_PORT = 2
ACCESS_FS_WRITE_FILE = 1 << 1
ACCESS_FS_MAKE_REG = 1 << 8
ACCESS_NET_BIND_TCP = 1 << 0
ACCESS_NET_CONNECT_TCP = 1 << 1


class RulesetAttr(ctypes.Structure):
    # 8 bytes on kernels without the net domain, 16 with it (v6.8 ABI 4).
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
    ]


class NetPortAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("port", ctypes.c_uint64)]


libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
out = {}

abi = libc.syscall(SYS_CREATE, 0, 0, LANDLOCK_CREATE_RULESET_VERSION)
if abi < 0:
    out["abi_errno"] = ctypes.get_errno()
else:
    out["abi_errno"] = None
    out["abi"] = int(abi)

fs_attr = RulesetAttr(handled_access_fs=ACCESS_FS_WRITE_FILE | ACCESS_FS_MAKE_REG)
fd = libc.syscall(SYS_CREATE, ctypes.byref(fs_attr), ctypes.sizeof(fs_attr), 0)
if fd < 0:
    out["create_fs_ruleset_errno"] = ctypes.get_errno()
else:
    out["create_fs_ruleset_errno"] = None
    os.close(fd)

net_attr = RulesetAttr(
    handled_access_fs=ACCESS_FS_WRITE_FILE | ACCESS_FS_MAKE_REG,
    handled_access_net=ACCESS_NET_BIND_TCP | ACCESS_NET_CONNECT_TCP,
)
fd = libc.syscall(SYS_CREATE, ctypes.byref(net_attr), ctypes.sizeof(net_attr), 0)
if fd < 0:
    out["create_net_ruleset_errno"] = ctypes.get_errno()
else:
    out["create_net_ruleset_errno"] = None
    np = NetPortAttr(allowed_access=ACCESS_NET_CONNECT_TCP, port=8080)
    if libc.syscall(SYS_ADD, fd, LANDLOCK_RULE_NET_PORT, ctypes.byref(np), 0) == 0:
        out["net_port_rule_errno"] = None
    else:
        out["net_port_rule_errno"] = ctypes.get_errno()
    os.close(fd)
print(json.dumps(out))
"""

_LANDLOCK_MARKER_SNIPPET = r"""
import ctypes, json, os, subprocess, sys

SYS_CREATE = 444
SYS_ADD = 445
SYS_RESTRICT = 446
PR_SET_NO_NEW_PRIVS = 38
LANDLOCK_RULE_PATH_BENEATH = 1
ACCESS_FS_WRITE_FILE = 1 << 1
ACCESS_FS_MAKE_REG = 1 << 8


class RulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
    ]


class PathBeneath(ctypes.Structure):
    # packed: the kernel's build_check_abi asserts exactly 12 bytes.
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


scratch = sys.argv[1]
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
out = {}

if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
    out["error"] = "prctl(PR_SET_NO_NEW_PRIVS) failed: errno %d" % ctypes.get_errno()
    print(json.dumps(out))
    sys.exit(0)

allowed = ACCESS_FS_WRITE_FILE | ACCESS_FS_MAKE_REG
attr = RulesetAttr(handled_access_fs=allowed)
fd = libc.syscall(SYS_CREATE, ctypes.byref(attr), ctypes.sizeof(attr), 0)
if fd < 0:
    out["error"] = "landlock_create_ruleset failed: errno %d" % ctypes.get_errno()
    print(json.dumps(out))
    sys.exit(0)

parent_fd = os.open(scratch, os.O_RDONLY)
pb = PathBeneath(allowed_access=allowed, parent_fd=parent_fd)
if libc.syscall(SYS_ADD, fd, LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(pb), 0) != 0:
    out["error"] = "landlock_add_rule failed: errno %d" % ctypes.get_errno()
    print(json.dumps(out))
    sys.exit(0)
if libc.syscall(SYS_RESTRICT, fd, 0) != 0:
    out["error"] = "landlock_restrict_self failed: errno %d" % ctypes.get_errno()
    print(json.dumps(out))
    sys.exit(0)
os.close(fd)
os.close(parent_fd)

denied = subprocess.run(
    ["/bin/sh", "-c", "echo x > /etc/belay-probe-denied.txt"],
    capture_output=True,
    timeout=30,
)
control = subprocess.run(
    ["/bin/sh", "-c", "echo x > %s/control.txt" % scratch],
    capture_output=True,
    timeout=30,
)
out["denied_rc"] = denied.returncode
out["denied_stderr"] = denied.stderr.decode("utf-8", "replace")
out["control_rc"] = control.returncode
out["control_stderr"] = control.stderr.decode("utf-8", "replace")
print(json.dumps(out))
"""


# --- the five probes ---------------------------------------------------------


def probe_unshare_userns() -> dict:
    """Can this process create an unprivileged user namespace?

    Two attempts, both measured: the `unshare(CLONE_NEWUSER|CLONE_NEWNS)`
    syscall via ctypes (in a subprocess — a successful unshare mutates the
    caller's namespaces), and the `unshare -Urm -- /bin/true` binary. EPERM on
    the userns attempt is the Ubuntu 23.10+ AppArmor restriction (or kernel
    policy); the AppArmor audit line goes to the kernel log, not to child
    stderr, so it is named but not captured. `restricted` is a finding, not an
    error.
    """
    if sys.platform != "linux":
        return _probe("unavailable", f"this probe is Linux-only; running on {sys.platform!r}")
    out = _run_snippet(_UNSHARE_SNIPPET)
    combined: int | None = out["combined"]
    user_only: int | None = out.get("user_only")
    binary = _probe_unshare_binary()
    ctypes_result = {
        "combined": {
            "ok": combined is None,
            "errno": combined,
            "errno_name": _errno_name(combined),
        },
        "user_only": (
            {
                "attempted": True,
                "ok": user_only is None,
                "errno": user_only,
                "errno_name": _errno_name(user_only),
            }
            if user_only is not None
            else {"attempted": False}
        ),
    }
    if combined is None or binary["ok"]:
        return _probe("ok", ctypes=ctypes_result, binary=binary)
    binary_marker = classify_denial_marker(binary.get("stderr") or "")
    if combined in (1, 13) or binary_marker in ("EPERM", "EACCES"):
        return _probe(
            "restricted",
            "unshare(CLONE_NEWUSER) was refused with EPERM/EACCES — unprivileged user "
            "namespaces are blocked on this image (Ubuntu 23.10+ AppArmor "
            "restrict_unprivileged_userns, or kernel policy). The AppArmor audit line "
            "goes to the kernel log, not to child stderr, so it is not captured here.",
            ctypes=ctypes_result,
            binary=binary,
        )
    return _probe(
        "unavailable",
        f"unshare failed with errno {combined} ({_errno_name(combined)})",
        ctypes=ctypes_result,
        binary=binary,
    )


def _probe_unshare_binary() -> dict:
    path = shutil.which("unshare")
    if path is None:
        return {"present": False, "attempted": False, "ok": None}
    try:
        proc = subprocess.run(
            [path, "-Urm", "--", "/bin/true"],
            capture_output=True,
            timeout=30.0,
        )
    except subprocess.TimeoutExpired:
        return {"present": True, "attempted": True, "ok": False, "reason": "timed out after 30s"}
    return {
        "present": True,
        "attempted": True,
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "stderr": _truncate(proc.stderr.decode("utf-8", "replace")),
    }


def probe_bwrap() -> dict:
    """Is bubblewrap installed, and does it run with a write-scope boundary?

    `absent` when not installed (a valid result — the decision then leans
    landlock). Otherwise: a minimal sandboxed run (the plan's exact argv), and
    a refused-write probe — the whole root bound read-only, a scratch dir bound
    writable, a write to `/etc` denied and its stderr recorded verbatim with a
    control write to scratch proving the sandbox is not merely broken. A
    refused write that SUCCEEDS is a finding (the boundary failed), recorded,
    never ignored.
    """
    if sys.platform != "linux":
        return _probe("unavailable", f"this probe is Linux-only; running on {sys.platform!r}")
    path = shutil.which("bwrap")
    if path is None:
        return _probe("absent", "no 'bwrap' on PATH — bubblewrap is not installed on this image")
    result = _probe("ok", bwrap_path=path)
    try:
        proc = subprocess.run(
            [
                path,
                "--ro-bind",
                "/",
                "/",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--unshare-all",
                "--",
                "/bin/true",
            ],
            capture_output=True,
            timeout=30.0,
        )
    except subprocess.TimeoutExpired:
        result["status"] = "unavailable"
        result["reason"] = "the minimal sandboxed run timed out after 30s"
        return result
    result["minimal_run"] = {
        "rc": proc.returncode,
        "stderr": _truncate(proc.stderr.decode("utf-8", "replace")),
    }
    if proc.returncode != 0:
        # Installed but unable to run — e.g. unshare-all refused when userns is
        # restricted. The stderr IS the reason, recorded verbatim.
        result["status"] = "unavailable"
        result["reason"] = (
            f"the minimal sandboxed run failed (rc={proc.returncode}): "
            f"{result['minimal_run']['stderr']}"
        )
        return result
    result["refused_write"] = _probe_bwrap_refused_write(path)
    return result


def _probe_bwrap_refused_write(bwrap_path: str) -> dict:
    scratch = tempfile.mkdtemp(prefix="belay-probe-bwrap-")
    common = [
        bwrap_path,
        "--ro-bind",
        "/",
        "/",
        "--bind",
        scratch,
        scratch,
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--unshare-all",
    ]
    try:
        denied = subprocess.run(
            [*common, "--", "/bin/sh", "-c", "echo x > /etc/belay-probe-denied.txt"],
            capture_output=True,
            timeout=30.0,
        )
        control = subprocess.run(
            [*common, "--", "/bin/sh", "-c", f"echo x > {scratch}/control.txt"],
            capture_output=True,
            timeout=30.0,
        )
    except subprocess.TimeoutExpired:
        return {"attempted": True, "measured": False, "reason": "timed out after 30s"}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    denied_stderr = _scrub(_truncate(denied.stderr.decode("utf-8", "replace")), scratch)
    control_stderr = _scrub(_truncate(control.stderr.decode("utf-8", "replace")), scratch)
    refused = denied.returncode != 0
    return {
        "attempted": True,
        "measured": refused,
        "refused": refused,
        "rc": denied.returncode,
        "marker": classify_denial_marker(denied_stderr) if refused else None,
        "stderr": denied_stderr,
        "control_rc": control.returncode,
        "control_stderr": control_stderr,
    }


def probe_landlock() -> dict:
    """Is landlock reachable, and does the kernel have its net domain?

    The verdict comes from the syscall itself: the ABI-version query
    (`landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)`).
    ENOSYS means no landlock (kernel < 5.13 or compiled out); EOPNOTSUPP means
    compiled in but disabled at boot; a returned ABI (>= 1) means reachable.
    With ABI >= 4 the net domain exists, measured by creating a ruleset that
    handles net access and adding a per-port rule — the evidence the
    allow-ports probe's basis cites. The release parse is recorded as context,
    never as the verdict.
    """
    if sys.platform != "linux":
        return _probe("unavailable", f"this probe is Linux-only; running on {sys.platform!r}")
    release = os.uname().release
    parsed = parse_kernel_release(release)
    out = _run_snippet(_LANDLOCK_REACH_SNIPPET)
    abi_errno: int | None = out.get("abi_errno")
    if abi_errno is None:
        fs_errno: int | None = out.get("create_fs_ruleset_errno")
        if fs_errno is not None:
            return _probe(
                "unavailable",
                f"ABI reachable (v{out['abi']}) but ruleset creation failed with errno "
                f"{fs_errno} ({_errno_name(fs_errno)})",
                release=release,
                release_parsed=parsed,
                abi=out["abi"],
            )
        return _probe(
            "ok",
            release=release,
            release_parsed=parsed,
            abi=out["abi"],
            net_domain=_landlock_net_shape(out),
        )
    return _probe(
        "unavailable",
        _landlock_unavailable_reason(abi_errno, release),
        release=release,
        release_parsed=parsed,
        abi_errno=abi_errno,
        abi_errno_name=_errno_name(abi_errno),
    )


def _landlock_unavailable_reason(abi_errno: int, release: str) -> str:
    if abi_errno == 38:  # ENOSYS
        return (
            f"landlock_create_ruleset returned ENOSYS on kernel {release} — no landlock "
            "(older than 5.13, or compiled out)"
        )
    if abi_errno == 95:  # EOPNOTSUPP
        return (
            f"landlock_create_ruleset returned EOPNOTSUPP on kernel {release} — landlock "
            "is compiled in but disabled at boot"
        )
    return f"landlock ABI version query failed with errno {abi_errno} ({_errno_name(abi_errno)})"


def _landlock_net_shape(out: dict) -> dict:
    errno: int | None = out.get("create_net_ruleset_errno")
    if errno is None:
        return {
            "supported": True,
            "create_errno": None,
            "net_port_rule_errno": out.get("net_port_rule_errno"),
            "net_port_rule_errno_name": _errno_name(out.get("net_port_rule_errno")),
        }
    return {
        "supported": False,
        "create_errno": errno,
        "create_errno_name": _errno_name(errno),
    }


def leading_mechanism(bwrap: dict, landlock: dict) -> str:
    """Which mechanism the allow-ports question is asked of.

    The plan says "bwrap if present else landlock"; presence is read as
    *usable* (the probe's `ok`), because a mechanism that is installed but
    cannot run is not something A2 could build on — asking the mapping
    question of it would answer for a mechanism that cannot lead.
    """
    if bwrap["status"] == "ok":
        return "bwrap"
    if landlock["status"] == "ok":
        return "landlock"
    return "none"


def probe_allow_ports_mapping(leading_mechanism_name: str) -> dict:
    """Can the closed vocabulary `allow-ports` (outbound to loopback on given
    ports) be expressed on the leading mechanism?

    The finding is a feasibility verdict with its measured basis, never a bare
    claim:

    - **bwrap**: `--unshare-net` gives deny-all with no per-port granularity;
      port-scoped/loopback filtering needs netfilter (nftables/iptables) inside
      the network namespace — root (CAP_NET_ADMIN) and external binaries, both
      outside an unprivileged, zero-dependency sandbox.
    - **landlock**: the net domain (measured in the landlock probe) restricts
      TCP by PORT only — `LANDLOCK_ACCESS_NET_CONNECT_TCP` + a
      `LANDLOCK_RULE_NET_PORT` grants the port on ANY address. The closed
      vocabulary means loopback-only, an address scope landlock does not have;
      a port grant would be a LOOSER boundary than `allow-ports` claims, so
      per OQ-2 the vocabulary degrades to UNVERIFIED-with-cause rather than
      widening silently.

    Either way `allow-ports` is not expressible as-is on the pinned image; the
    status tells the decision which half of the basis applies.
    """
    if leading_mechanism_name == "bwrap":
        return _probe(
            "not-expressible-without-netns-tools",
            "bwrap's only network control is --unshare-net (deny-all, no per-port "
            "granularity). The closed vocabulary allow-ports (outbound to loopback on "
            "given ports) would need netfilter (nftables/iptables) inside the network "
            "namespace, which requires root (CAP_NET_ADMIN) and external binaries — "
            "outside an unprivileged, zero-dependency sandbox.",
            leading_mechanism="bwrap",
            basis="bwrap --unshare-net is deny-all without per-port rules; per-port and "
            "loopback-scoped filtering is netfilter territory (root + external tools).",
        )
    if leading_mechanism_name == "landlock":
        return _probe(
            "not-expressible",
            "landlock's net domain (see the landlock probe's net_domain) restricts TCP by "
            "PORT only (LANDLOCK_ACCESS_NET_CONNECT_TCP + LANDLOCK_RULE_NET_PORT): a "
            "granted port is reachable on any address. The closed vocabulary means "
            "loopback-only — an address scope landlock does not have. A port grant would "
            "be a looser boundary than allow-ports claims, so it degrades to "
            "UNVERIFIED-with-cause rather than widening silently.",
            leading_mechanism="landlock",
            basis="measured: landlock_net_port_attr carries (allowed_access, port) and no "
            "address scope; the loopback-only half of allow-ports is not expressible.",
        )
    return _probe(
        "not-expressible",
        "no leading mechanism was measured on this platform, so no mapping exists",
        leading_mechanism="none",
        basis="the allow-ports mapping is defined only for a measured leading mechanism",
    )


def probe_denial_marker(probes: dict) -> dict:
    """For each viable mechanism, the exact stderr text of a refused write.

    This is the OQ-4 measurement: what does a refused write look like on the
    Linux boundary, and is it distinguishable from an ordinary permission
    error? The bwrap marker is measured in `probe_bwrap`'s refused-write probe
    (one sandboxed run, one measurement); the landlock marker is measured by
    actually applying a ruleset (scratch writable, everything else not) in a
    subprocess and attempting the same /etc write. The verbatim stderr is
    recorded alongside the classification because the text is the ground
    truth and the classification is derived from it — the same provenance
    discipline as `seatbelt._denials_from_stderr`.
    """
    mechanisms: dict[str, dict] = {}
    bwrap = probes.get("bwrap", {})
    if bwrap.get("status") == "ok":
        refused = bwrap.get("refused_write", {})
        if refused.get("attempted"):
            mechanisms["bwrap"] = {
                "measured": bool(refused.get("measured")),
                "refused": refused.get("refused"),
                "marker": refused.get("marker"),
                "rc": refused.get("rc"),
                "stderr": refused.get("stderr"),
            }
    landlock = probes.get("landlock", {})
    if landlock.get("status") == "ok":
        mechanisms["landlock"] = _probe_landlock_marker()
    if not any(entry.get("measured") for entry in mechanisms.values()):
        attempted = ", ".join(sorted(mechanisms)) if mechanisms else "none"
        return _probe(
            "unavailable",
            f"no mechanism produced a refusal marker to classify (attempted: {attempted})",
            mechanisms=mechanisms,
        )
    return _probe("ok", mechanisms=mechanisms)


def _probe_landlock_marker() -> dict:
    scratch = tempfile.mkdtemp(prefix="belay-probe-landlock-")
    try:
        out = _run_snippet(_LANDLOCK_MARKER_SNIPPET, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if "error" in out:
        return {
            "attempted": True,
            "measured": False,
            "reason": out["error"],
        }
    denied_stderr = _scrub(out["denied_stderr"], scratch)
    control_stderr = _scrub(out["control_stderr"], scratch)
    refused = out["denied_rc"] != 0
    return {
        "attempted": True,
        "measured": refused,
        "refused": refused,
        "rc": out["denied_rc"],
        "marker": classify_denial_marker(denied_stderr) if refused else None,
        "stderr": denied_stderr,
        "control_rc": out["control_rc"],
        "control_stderr": control_stderr,
    }


# --- orchestration -----------------------------------------------------------


def run_probes() -> dict:
    """Run all five probes and assemble the artifact dict.

    `probe_denial_marker` and `probe_allow_ports_mapping` are derived from the
    bwrap/landlock measurements, so those two run first. Every probe may
    return `unavailable`/`absent` — that IS the measurement; only a crash
    raises.
    """
    bwrap = probe_bwrap()
    landlock = probe_landlock()
    probes = {
        "unshare_userns": probe_unshare_userns(),
        "bwrap": bwrap,
        "landlock": landlock,
        "allow_ports_mapping": probe_allow_ports_mapping(leading_mechanism(bwrap, landlock)),
        "denial_marker": probe_denial_marker({"bwrap": bwrap, "landlock": landlock}),
    }
    return {"env": probe_env(), "probes": probes}


def main() -> int:
    """Run all probes, write `probe_result.json`, print a human summary.

    Exit 0 even when every mechanism is unavailable — that is the measurement.
    Exit non-zero only on a probe error: a crash (1), or an artifact that
    fails its own schema (2), which would be worse than none because the
    decision cites it.
    """
    try:
        result = run_probes()
        violations = validate_result(result)
        if violations:
            print("probe result failed schema validation; not writing an artifact:", file=sys.stderr)
            for violation in violations:
                print(f"  - {violation}", file=sys.stderr)
            return 2
        with open(OUTPUT_FILENAME, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"wrote {OUTPUT_FILENAME}")
        for name, probe in result["probes"].items():
            print(f"  {name}: {probe['status']}")
            if "reason" in probe:
                print(f"    reason: {probe['reason']}")
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
