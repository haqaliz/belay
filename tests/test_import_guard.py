"""Static guards over `src/belay`'s import graph.

These are correctness guards, not lint preferences, and they exist because the
test suite alone cannot catch what they catch.

`mcp` is a **dev** dependency, so it is importable inside this venv. Nothing at
runtime would stop `import mcp` appearing in `src/belay/` — every test would go
on passing, and the wheel would ship with a missing runtime dependency that only
a user discovers. The teeth test guards the forwarding path's *behaviour*; only a
static walk of the import graph guards its *dependencies*.

Every check here parses with `ast` and never imports the module under test.
Importing to inspect would defeat the purpose twice over: it would run module
side effects, and it would report on the venv the tests happen to have rather
than on the source that actually ships.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "belay"

FIRST_PARTY = "belay"


def _modules() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert files, f"no modules found under {SRC} — this guard would pass vacuously"
    return files


def _imported_roots(path: Path) -> list[tuple[str, int]]:
    """Every top-level module name `path` imports, with the line it appears on.

    `ast.walk` rather than a scan of module-level statements: an import nested
    inside a function is still an import, and a guard that only looked at the top
    of the file would be trivially sidestepped by indenting one line.

    Relative imports (`from . import x`) are first-party by construction and
    carry no module root to check.
    """
    tree = ast.parse(path.read_bytes(), filename=str(path))
    roots: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend((alias.name.split(".")[0], node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                roots.append((node.module.split(".")[0], node.lineno))
    return roots


def test_no_mcp_import_anywhere_in_src() -> None:
    """`mcp` is a dev/test dependency and must never enter the shipped package.

    It is importable in this venv, so nothing else would catch this: the suite
    would stay green and the wheel would ship broken. The proxy forwards bytes
    and must not depend on any implementation of the protocol it forwards —
    that is what makes it able to carry a frame the SDK would reject.
    """
    offenders = [
        f"{path.relative_to(SRC)}:{lineno} imports {root!r}"
        for path in _modules()
        for root, lineno in _imported_roots(path)
        if root == "mcp"
    ]
    assert not offenders, (
        "`mcp` imported inside src/belay:\n  "
        + "\n  ".join(offenders)
        + "\n\nWHY THIS IS A FAILURE: `mcp` is a DEV dependency (pyproject's dev group),"
        " not a runtime one. It imports cleanly in this venv, so the tests would pass"
        " and the published wheel would ship with an undeclared runtime dependency"
        " that fails at the user's first import.\n"
        "Belay proxies MCP by forwarding bytes; it must not depend on an"
        " implementation of the protocol it forwards. A frame the SDK would reject"
        " must still cross the proxy verbatim (tests/fixtures/fake_server.py sends"
        " exactly such a frame on purpose). The SDK belongs in tests/ only."
    )


def test_src_imports_stdlib_and_first_party_only() -> None:
    """Runtime dependencies stay at zero. Enforced structurally, not by policy.

    `pyproject.toml` declares `dependencies = []`. That declaration is not
    checked by anything at test time — every dev dependency is importable here,
    so a third-party import inside `src/belay` passes the suite and breaks only
    for the user. This test is the thing that checks it.
    """
    offenders = [
        f"{path.relative_to(SRC)}:{lineno} imports {root!r}"
        for path in _modules()
        for root, lineno in _imported_roots(path)
        if root != FIRST_PARTY and root not in sys.stdlib_module_names
    ]
    assert not offenders, (
        "non-stdlib import inside src/belay:\n  "
        + "\n  ".join(offenders)
        + "\n\nWHY THIS IS A FAILURE: Belay declares ZERO runtime dependencies"
        " (pyproject: `dependencies = []`). Belay runs on the user's infrastructure,"
        " inside their agent's process tree, in front of their MCP servers; every"
        " dependency it adds is one it forces on them and one more thing that can"
        " break or conflict at the exact moment the harness is supposed to be the"
        " reliable part. Nothing else catches this: dev dependencies import fine in"
        " this venv, so the wheel ships broken and the suite stays green.\n"
        "If a dependency is genuinely required, it must be added to"
        " `[project].dependencies` deliberately — and this guard updated as a"
        " visible decision rather than sidestepped."
    )


def test_proxy_does_not_import_json() -> None:
    """The forwarding path must be structurally incapable of re-serialising.

    Not a style rule. See the assertion message.
    """
    proxy = SRC / "proxy.py"
    offenders = [
        f"proxy.py:{lineno} imports {root!r}"
        for root, lineno in _imported_roots(proxy)
        if root == "json"
    ]
    assert not offenders, (
        "`json` imported in src/belay/proxy.py:\n  "
        + "\n  ".join(offenders)
        + "\n\nWHY THIS IS A FAILURE: proxy.py is the forwarding path, and its"
        " byte-transparency is meant to be STRUCTURAL — it has no name for a"
        " serialiser in scope, so it cannot parse-and-re-emit even by accident.\n"
        "If the forwarding path could re-serialise, the bytes reaching the server"
        " and the trace would be what the PROXY emitted, not what the AGENT sent."
        " Key order, escaping and unknown fields would silently normalise, and the"
        " tamper-evidence this product exists to provide would be laundered away by"
        " the tool claiming to provide it. tests/test_teeth.py proves a"
        " re-serialising proxy is detectable; this guard makes it unreachable.\n"
        "The recorder needs `json` and has it: belay.trace imports it, and main()"
        " imports TraceWriter INSIDE the function for exactly this reason — main()"
        " is the composition root, and everything above it stays serialiser-free."
    )
