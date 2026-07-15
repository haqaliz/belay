"""What the POLICY LANGUAGE itself refuses — measured against `sandbox-exec`, not recalled.

`NetworkPolicy` is a closed enum because SBPL cannot express a per-host rule. That
sentence is the entire justification for refusing a hostname at Belay's API instead
of accepting one, and until this file existed it was grounded in a docstring.

**The gap this closes.** `test_network_policy_rejects_a_hostname_allowlist` proves
*our Python raises*. It does not prove *SBPL rejects the profile* — those are
different claims, and only the second one justifies the first. If a future macOS
gained per-host syntax, every existing test would still pass while the stated
reason for the restriction had quietly become false. This file is what would
notice.

These tests drive `/usr/bin/sandbox-exec` directly and deliberately do **not** go
through `seatbelt.py`: the point is to measure the substrate's own behaviour,
independent of the code whose design depends on it.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

#: The verbatim refusal, measured on macOS 26.5.2 / arm64. Quoted in
#: `docs/technical/THREAT_MODEL.md`; if this string moves, that document is wrong.
PER_HOST_REJECTION = "host must be * or localhost in network address"


#: The profile's non-network lines, matching `seatbelt.build_profile`'s verified
#: shape. They are not decoration: with a bare `(deny default)` even `/usr/bin/true`
#: dies on SIGABRT (rc 134, measured) **after** the profile compiled fine — so a
#: test keying on the exit code alone would call a perfectly good profile rejected.
#: That is why the assertions below key on the compiler's own words instead.
_PREAMBLE = (
    "(version 1)\n"
    "(deny default)\n"
    "(allow process*)\n"
    "(allow sysctl-read)\n"
    "(allow mach-lookup)\n"
    "(allow file-read*)\n"
    "(deny network*)\n"
)


def _compile(rule: str, tmp_path) -> subprocess.CompletedProcess:
    """Hand a profile to the real compiler and report what it said.

    `/usr/bin/true` is the command because we are testing whether the **profile**
    is accepted; anything that could itself fail would confound the result.
    """
    profile = tmp_path / "probe.sb"
    profile.write_text(f"{_PREAMBLE}{rule}\n")
    return subprocess.run(
        [SANDBOX_EXEC, "-f", str(profile), "/usr/bin/true"],
        capture_output=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "rule",
    [
        '(allow network-outbound (remote ip "1.1.1.1:*"))',
        '(allow network-outbound (remote ip "example.com:443"))',
    ],
    ids=["ipv4-literal", "hostname"],
)
def test_a_per_host_rule_is_a_compile_error(rule: str, tmp_path) -> None:
    """The measurement `NetworkPolicy`'s closed enum rests on.

    Both spellings are refused — the address form is not the issue; **any** host
    that is not `*` or `localhost` is. So there is no per-host allowlist to be had
    at any level of cleverness, and accepting one at our API could only ever mean
    accepting it and not enforcing it.
    """
    result = _compile(rule, tmp_path)

    stderr = result.stderr.decode(errors="replace")
    assert PER_HOST_REJECTION in stderr, (
        f"SBPL did not reject a per-host rule with the expected error; the closed "
        f"enum's stated premise may no longer hold. stderr: {stderr!r}"
    )
    assert result.returncode != 0


def test_the_localhost_rule_the_enum_does_allow_compiles(tmp_path) -> None:
    """Anti-vacuity: the harness can produce a profile that IS accepted.

    Without this, a typo in `_compile` would make the test above pass by failing to
    compile anything at all, and its conclusion would be an artifact of the harness
    rather than a fact about SBPL. This is the exact rule the closed enum *does*
    permit — `allow-ports` emits this line — so it must compile.
    """
    result = _compile('(allow network-outbound (remote ip "localhost:8080"))', tmp_path)

    assert PER_HOST_REJECTION not in result.stderr.decode(errors="replace")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
