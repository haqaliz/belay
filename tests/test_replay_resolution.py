"""AC-7: the `{workspace}` argv resolution is ONE exported site, not two copies.

`WORKSPACE_PLACEHOLDER` substitution was inlined inside `engine.replay_turn` and the
resolved argv was never returned, so a second caller (the boundary probe) could only
have re-implemented it. Two copies of a rooting rule drift silently, and the drift is
invisible: both would still produce *a* verdict, just not the same one. This file pins
the extracted helper's contract and then pins that the literal token is consumed in
exactly one place under `src/belay/`.

This is a REFACTOR guard, not a behavior change: every case below states what the
INLINED code did, and `test_rootless_placeholder_still_unverified_end_to_end` pins that
`replay_turn`'s `ROOTLESS_RELOCATION` verdict is unchanged — the helper signals "cannot
resolve" to its caller and never swallows that abstention.

Pure logic: no re-execution, no sandbox, no clock, no network — so it runs identically
on macOS and Linux, carries NO platform gate of any kind, and is therefore deliberately
absent from `tests/test_platform_gate_named_causes.py::SCAN_AREA`.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from belay.replay import engine
from belay.replay.engine import (
    ROOTLESS_RELOCATION,
    UNVERIFIED,
    WORKSPACE_PLACEHOLDER,
    resolve_server_argv,
)
from belay.snapshot.substrate import ClonefileBackend, FIDELITY_GAPS
from belay.trace import TraceWriter


SRC = Path(__file__).resolve().parents[1] / "src" / "belay"


# --- 1. Identity: a command with no placeholder is returned unchanged ---------


def test_command_without_placeholder_is_returned_unchanged() -> None:
    """No placeholder token -> the argv is passed through, with no cause.

    The overwhelmingly common case (a hand-written rooted command). The inlined code
    guarded on `WORKSPACE_PLACEHOLDER in server_command` and did nothing when absent;
    the helper must preserve that byte-for-byte, root recorded or not.
    """
    argv = ["node", "/srv/fs.js", "/root/proj"]

    resolved, cause = resolve_server_argv(argv, "/root/proj")

    assert cause is None
    assert resolved == ["node", "/srv/fs.js", "/root/proj"]


def test_command_without_placeholder_is_unchanged_even_rootless() -> None:
    """No placeholder + no recorded root -> still unchanged, still no cause.

    The rootless signal belongs to the placeholder alone. A cwd-relative command on a
    pre-`source_root` capture must NOT be diverted into `ROOTLESS_RELOCATION` here —
    that decision is `_relocation_decision`'s, downstream, on the turn's arguments.
    """
    resolved, cause = resolve_server_argv(["python", "srv.py"], None)

    assert cause is None
    assert resolved == ["python", "srv.py"]


def test_resolution_never_mutates_the_caller_s_argv() -> None:
    """The helper returns a NEW list; the caller's sequence is untouched.

    `replay_turn` rebinds `server_command` and later hands `list(server_command)` to the
    client. A helper that mutated its input in place would leak the substitution back
    into a caller reusing one argv across a whole batch of traces — which is precisely
    the batch case `{workspace}` exists to serve.
    """
    argv = ["node", "/srv/fs.js", WORKSPACE_PLACEHOLDER]

    resolved, cause = resolve_server_argv(argv, "/root/proj")

    assert cause is None
    assert resolved is not argv
    assert argv == ["node", "/srv/fs.js", WORKSPACE_PLACEHOLDER], "input must be untouched"
    assert resolved == ["node", "/srv/fs.js", "/root/proj"]


# --- 2. Whole-token substitution, and ONLY whole-token -----------------------


def test_whole_token_placeholder_becomes_the_recorded_root() -> None:
    """A token EQUAL to the placeholder becomes `source_root`; every other token stands."""
    argv = ["node", "/srv/fs.js", WORKSPACE_PLACEHOLDER, "--readonly"]

    resolved, cause = resolve_server_argv(argv, "/some/abs/workspace")

    assert cause is None
    assert resolved == ["node", "/srv/fs.js", "/some/abs/workspace", "--readonly"]


def test_every_whole_token_placeholder_is_substituted() -> None:
    """Repeats substitute too — the inlined comprehension replaced every equal token.

    A server taking two allow-roots (`... {workspace} {workspace}`) must not end up
    half-resolved, which would spawn a server rooted partly at a literal `{workspace}`
    directory that does not exist.
    """
    argv = [WORKSPACE_PLACEHOLDER, "x", WORKSPACE_PLACEHOLDER]

    resolved, cause = resolve_server_argv(argv, "/r")

    assert cause is None
    assert resolved == ["/r", "x", "/r"]


def test_embedded_placeholder_is_NOT_substituted() -> None:
    """`--root={workspace}` is NOT a whole token, so it is left exactly as written.

    Documented semantics (`WORKSPACE_PLACEHOLDER`'s own docstring): whole-token only, so
    an embedded placeholder is *not* half-handled here and instead reads downstream as
    `UNROOTABLE_SERVER_COMMAND`. Pinned because a substring `str.replace` is the obvious
    "simplification" a later refactor would reach for, and it would silently change the
    boundary this abstention protects.
    """
    argv = ["node", "/srv/fs.js", f"--root={WORKSPACE_PLACEHOLDER}"]

    resolved, cause = resolve_server_argv(argv, "/root/proj")

    assert cause is None
    assert resolved == ["node", "/srv/fs.js", f"--root={WORKSPACE_PLACEHOLDER}"]


def test_embedded_placeholder_rootless_is_not_a_rootless_abstention() -> None:
    """The mirror: an embedded placeholder with NO root is still not `ROOTLESS_RELOCATION`.

    Membership was tested against whole tokens, so the rootless branch was unreachable
    for an embedded placeholder. Preserved exactly — widening it here would newly abstain
    on traces that replay fine today.
    """
    resolved, cause = resolve_server_argv(["node", f"--root={WORKSPACE_PLACEHOLDER}"], None)

    assert cause is None
    assert resolved == ["node", f"--root={WORKSPACE_PLACEHOLDER}"]


# --- 3. Rootless: the helper SIGNALS, and never swallows, the abstention ------


def test_placeholder_without_recorded_root_signals_rootless_relocation() -> None:
    """A placeholder with `source_root is None` -> no argv, and the named cause.

    No root is ever guessed. The helper returns `(None, ROOTLESS_RELOCATION)` — the same
    `(value, cause)` shape `_relocation_decision` already uses — so the caller decides the
    verdict and this function never renders one.
    """
    resolved, cause = resolve_server_argv(["node", "/srv/fs.js", WORKSPACE_PLACEHOLDER], None)

    assert resolved is None, "a half-resolved argv must never be handed back"
    assert cause == ROOTLESS_RELOCATION


# --- 4. End-to-end: `replay_turn`'s verdict is byte-identical ----------------


def _rootless_manifest(manifest_dir: Path, handle: str) -> Path:
    """A persisted manifest with NO `source_root` key (an old, pre-field capture).

    Hand-built (not `take_snapshot`) so the placeholder gate is exercised cross-platform:
    the engine returns the honest `UNVERIFIED` BEFORE any restore, so no macOS Seatbelt
    machinery is touched.
    """
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "handle": handle,
        "tree_path": str(manifest_dir / "tree"),
        "backend": ClonefileBackend.name,
        "capabilities": sorted(ClonefileBackend.capabilities()),
        "fidelity_gaps": [gap.value for gap in FIDELITY_GAPS],
        "sidecar": {"link_groups": [], "special_modes": [], "dir_times": []},
    }
    (manifest_dir / "m.json").write_text(json.dumps(payload), encoding="utf-8")
    return manifest_dir


def _records(tmp_path: Path, name: str, frames: list[tuple]) -> list[dict]:
    """Build a real trace via `TraceWriter` and read its records back (cross-platform)."""
    trace_dir = tmp_path / name
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    path = sorted(trace_dir.glob("*.jsonl"))[0]
    return [json.loads(line) for line in path.read_bytes().split(b"\n") if line]


def test_rootless_placeholder_still_unverified_end_to_end(tmp_path) -> None:
    """`replay_turn` still returns UNVERIFIED / `ROOTLESS_RELOCATION`, un-reinvoked.

    The extraction must not swallow the abstention into a bare `(None, cause)` the caller
    ignores. The turn's own argument here is CWD-RELATIVE, so the placeholder is the only
    thing that can produce this cause — isolating the extracted branch rather than
    re-testing `_relocation_decision`.
    """
    manifest_dir = _rootless_manifest(tmp_path / "mans", "h1")
    call = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "read_rel", "arguments": {"path": "src/a.py"}},
        }
    ).encode()
    present = {"status": "present", "handle": "h1"}
    records = _records(tmp_path, "rootless-placeholder", [("c2s", call, present)])

    out = engine.replay_turn(
        records,
        0,
        server_command=["python", "srv.py", WORKSPACE_PLACEHOLDER],
        manifest_dir=manifest_dir,
        timeout=1.0,
    )

    assert out.status == UNVERIFIED, out
    assert out.cause == ROOTLESS_RELOCATION
    assert out.reinvoked is False, "the honest fallback must NOT re-invoke the server"
    assert out.replayed_reply is None


# --- 5. The anti-duplication guard: exactly ONE substitution site ------------


def _python_sources() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_the_placeholder_literal_appears_once_in_src() -> None:
    """The string `"{workspace}"` is written exactly once under `src/belay/`: its definition.

    A second literal is a second definition of the token — the copy this phase exists to
    prevent. Compares the constant's VALUE exactly, so a docstring that merely mentions
    the placeholder is not a hit.
    """
    sites: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == WORKSPACE_PLACEHOLDER:
                sites.append(f"{path.relative_to(SRC)}:{node.lineno}")

    assert sites == ["replay/engine.py:148"] or len(sites) == 1, (
        f"the placeholder literal must be written exactly once (its definition); found {sites}"
    )


def test_the_placeholder_is_consumed_in_exactly_one_function() -> None:
    """Every *load* of `WORKSPACE_PLACEHOLDER` under `src/belay/` is inside one function.

    This is the anti-duplication guard the plan demands: the name may be exported (a
    string in `__all__` is not a load) and defined, but only ONE function may substitute
    with it. When the probe lands it must CALL that function, not grow a second reader.
    """
    consumers: set[str] = set()
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                loads_name = (
                    isinstance(node, ast.Name)
                    and node.id == "WORKSPACE_PLACEHOLDER"
                    and isinstance(node.ctx, ast.Load)
                )
                loads_attr = (
                    isinstance(node, ast.Attribute) and node.attr == "WORKSPACE_PLACEHOLDER"
                )
                if loads_name or loads_attr:
                    consumers.add(f"{path.relative_to(SRC)}::{func.name}")

    assert consumers == {"replay/engine.py::resolve_server_argv"}, (
        f"exactly one function may substitute the placeholder; found {sorted(consumers)}"
    )
