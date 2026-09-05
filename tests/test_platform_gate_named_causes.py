"""Every platform gate in the sandbox/replay area names its cause (A4 spec criterion 2).

The gating split (user-confirmed reading of "no platform skips") is stated in
README's platform coverage section: substrate-independent tests run on BOTH
platforms, substrate-specific tests have Linux analogues (written in A2/A3),
and everything that stays behind a platform gate carries a NAMED CAUSE. This
test makes the "named cause" half a checked fact:

- The scan area is the sandbox/replay/verify/corpus/snapshot test surface —
  every test file that gates on `sys.platform`, except the eval-only
  minting-driver smokes (`test_minting_driver_*`, `test_eval_*`: `manual`-
  marked, never run in CI).
- Every `skipif` / `pytest.skip` in that area must carry a reason string that
  begins with `{cause-id}:` where the cause id appears in README's platform
  coverage table. A skip without a reason, or with a reason that names no
  listed cause, fails here — on BOTH platforms.
- The guard that keeps the area honest: a test file OUTSIDE the scan set that
  gates on `sys.platform` fails this test with the file named — a new platform
  gate anywhere is noticed, and either joins the area (with a named cause) or
  is eval-only by name.

The check is pure text over the repo (AST-parsed, no execution), so it runs
identically on macOS and Linux — the CI skip-report step would duplicate it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
README = ROOT / "README.md"

#: Files whose platform gates the named-cause rule covers. The rule for the
#: list: a file belongs here when it exercises the sandbox/snapshot/replay/
#: verify/corpus surface AND gates on `sys.platform` (or carries a platform
#: capability skip such as the Landlock/reflink probes). Kept explicit so a
#: new file with a platform gate is noticed by `test_every_platform_gate_in_tests_is_accounted_for`
#: below, which demands the file either join this list or be eval-only by name.
SCAN_AREA: frozenset[str] = frozenset(
    {
        "test_bth1.py",
        "test_a3_corrupt_success_fixture.py",
        "test_containment.py",
        "test_corpus_add.py",
        "test_corpus_claim_ingest.py",
        "test_corpus_claim_run.py",
        "test_corpus_claim_show.py",
        "test_corpus_recorded_miss.py",
        "test_corpus_roundtrip.py",
        "test_corpus_task_prestate.py",
        "test_corpus_trajectory_run.py",
        "test_corpus_trajectory_show.py",
        "test_default_scope.py",
        "test_demo_capture.py",
        "test_determinism.py",
        "test_docker_image.py",
        "test_docker_compose.py",
        "test_docker_inimage.py",
        "test_interop_attach.py",
        "test_interop_cli.py",
        "test_interop_export_cli.py",
        "test_launch_demo.py",
        "test_launch.py",
        "test_linux_containment.py",
        "test_linux_probe.py",
        "test_linux_snapshot.py",
        "test_phase0_e2e.py",
        "test_phase0_claim.py",
        "test_proxy_containment.py",
        "test_replay_cli.py",
        "test_replay_client.py",
        "test_replay_engine.py",
        "test_replay_probe.py",
        "test_replay_relocation_e2e.py",
        "test_replay_relocation_shell_e2e.py",
        "test_refutation_no_claim_axis.py",
        "test_sandbox_check.py",
        "test_sbpl_limits.py",
        "test_seam_dispatch.py",
        "test_snapshot.py",
        "test_snapshot_mutations.py",
        "test_source_root_gate.py",
        "test_substrate.py",
        "test_trace_claim.py",
        "test_turn_gate.py",
        "test_verify_claims_sandbox.py",
        "test_verify_cli_invariants.py",
        "test_verify_cli.py",
        "test_verify_dual_server.py",
        "test_verify_tool_not_offered.py",
        "test_verify_exposure_cli.py",
        "test_verify_json.py",
        "test_verify_pass_on_cheat.py",
        "test_verify_result.py",
        "test_verify_shell_server_cli.py",
    }
)

#: Eval-only files (the minting-driver smokes): `manual`-marked, never in CI,
#: gated on real spend + npx + platform; their gates are outside the rule the
#: CI surface is held to. A file matching this prefix is exempt by name.
_EVAL_PREFIXES = ("test_minting_driver_", "test_eval_")


def _readme_causes() -> set[str]:
    """The cause ids listed in README's platform coverage table.

    The table rows carry the id in backticks as the first cell
    (``| `seatbelt-only` | ... |``). Extracting them from the README makes
    the README the source of truth — a gate that names a cause the README
    never listed, and a README cause no gate uses, both fail here.
    """
    text = README.read_text(encoding="utf-8")
    section = text.split("### Platform coverage: macOS and Linux, both measured", 1)
    if len(section) != 2:
        pytest.fail(
            "README's platform coverage section ('### Platform coverage: macOS "
            "and Linux, both measured') is missing — the named-cause table is "
            "the rule this test enforces"
        )
    table = section[1].split("### ", 1)[0]
    ids = set(re.findall(r"^\| `([a-z0-9-]+)` \|", table, flags=re.MULTILINE))
    assert ids, "README's platform coverage table lists no cause ids"
    return ids


def _reason_string(node: ast.AST) -> str | None:
    """The literal reason of a skipif/skip call: constant, or joined constants."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
        return "".join(parts) if parts else None
    return None


def _gates(tree: ast.AST) -> list[tuple[int, str]]:
    """Every (line, reason) platform gate in a test module.

    Two shapes are caught: `pytest.mark.skipif(..., reason=...)` calls
    (decorators or `marks=` arguments) and runtime `pytest.skip(reason)`
    calls. A skipif WITHOUT a reason is itself a violation — a silent skip
    has no cause to name.
    """
    gates: list[tuple[int, str]] = []

    class _Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "skipif":
                reason = None
                for kw in node.keywords:
                    if kw.arg == "reason":
                        reason = _reason_string(kw.value)
                if reason is None:
                    gates.append((node.lineno, "<no reason>"))
                else:
                    gates.append((node.lineno, reason))
            elif name == "skip":
                reason = None
                if node.args:
                    reason = _reason_string(node.args[0])
                for kw in node.keywords:
                    if kw.arg == "reason":
                        reason = _reason_string(kw.value)
                if reason is None:
                    gates.append((node.lineno, "<no reason>"))
                else:
                    gates.append((node.lineno, reason))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return gates


def _scan_files() -> list[tuple[Path, list[tuple[int, str]]]]:
    scanned: list[tuple[Path, list[tuple[int, str]]]] = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name not in SCAN_AREA:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        gates = _gates(tree)
        if gates:
            scanned.append((path, gates))
    return scanned


def test_every_platform_gate_in_tests_is_accounted_for() -> None:
    """A platform-gated test file outside the scan area is a new gate to decide.

    Either it belongs to the sandbox/replay surface and joins SCAN_AREA (where
    its gates must carry named causes), or it is eval-only by name. A file that
    is neither breaks the build with its name — the "no silent skips" rule is
    a checked fact, not a promise.
    """
    unaccounted = [
        path.name
        for path in sorted(TESTS.glob("test_*.py"))
        if "sys.platform" in path.read_text(encoding="utf-8")
        and path.name not in SCAN_AREA
        # The checker is not the checked: this module's own text necessarily
        # names `sys.platform` (it scans for it).
        and path.name != "test_platform_gate_named_causes.py"
        and not path.name.startswith(_EVAL_PREFIXES)
    ]
    assert not unaccounted, (
        "platform-gated test files outside the named-cause scan area: "
        f"{sorted(unaccounted)}. Add each to SCAN_AREA (its gates then need "
        "named causes from README's platform coverage table) or it is eval-only."
    )


def test_every_gate_in_the_scan_area_names_a_readme_cause() -> None:
    """The rule (A4 spec criterion 2): each gate's reason begins `{cause-id}:`.

    The ids come from README's platform coverage table, so the README and the
    tests cannot drift: a reason that names an id the README never listed is a
    failure, and the assertion below that every listed id is used keeps the
    table honest in the other direction (a dead cause row is a cause nobody
    cites, i.e. a gate that lost its documentation).
    """
    causes = _readme_causes()
    violations: list[str] = []
    used: set[str] = set()
    for path, gates in _scan_files():
        for line, reason in gates:
            matched = next((cid for cid in causes if f"{cid}:" in reason), None)
            if matched is None:
                violations.append(
                    f"{path.name}:{line}: reason {reason!r} names no cause id "
                    f"from README's platform coverage table"
                )
            else:
                used.add(matched)
    assert not violations, "platform gates without a named cause:\n" + "\n".join(
        violations
    )

    unused = causes - used
    assert not unused, (
        "README cause ids no gate uses (dead documentation, or a gate lost its "
        f"cause): {sorted(unused)}"
    )
