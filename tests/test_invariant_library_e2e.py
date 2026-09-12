"""Per-entry corrupt-success fixtures for the invariant library — aspect 3 (`entry-fixtures`, PRD M6).

Each grounded library entry is proven to FIRE on a real replay, at the exact turn, with A2
staying PASS on the same turn (axes non-redundant: a cheater's trace is perfectly faithful,
so A2 structurally cannot catch it — only the task-scoped A1 invariant can, mirroring
`test_inferred_invariants.py:145-181`), and each entry's fixture case banks via the real
`add_case` path and recomputes MATCH through `corpus run` (the corpus IS the regression
suite). The `network-egress` entry is the honesty fixture: UNVERIFIED with the named cause on
every turn, never PASS on any surface.

Three layers, in order:

1. **Fixture guards** — the new cheat servers really cheat: `create_server.py` really creates
   `generated/new_file.txt` and `delete_server.py` really deletes `docs/todo.txt`, so a green
   A1 verdict on their turns would be a false PASS (anti-vacuity pattern
   `tests/test_fixture_guard.py`).
2. **Per-entry CLI fixtures** — hand-built `TraceWriter` traces over real snapshots, replayed
   through `belay verify --invariant-library <entry>` (house pattern
   `tests/test_verify_cli_invariants.py:42-108`): each violating turn FAILs at the exact turn
   naming the invariant and the path, with A2 replay + A2 effect PASS on that same turn.
3. **Banked round trips + egress** — each grounded entry's case banks via the real `add_case`
   path (the CLI `corpus add`) and `corpus run` recomputes MATCH; a tampered case reads
   REGRESSION; and `--invariant-library network-egress` renders every turn UNVERIFIED with
   the named cause `network-egress-unobservable`, never PASS.

The PRD's self-critique gap 1 is pinned here: `add_case` stores the RESOLVED `Invariant`
objects on the case and `corpus run` recomputes with the case's OWN stored invariants —
`src/belay/corpus/run.py:770-772` rebuilds `Invariant` objects from `case.invariants` (the
library name is never stored, so recompute cannot and does not re-resolve it; an entry's
declarations changing later must not silently re-judge a banked case). The regression-sim
test proves the direction: a case whose stored invariants are emptied REGRESSES — if
recompute re-resolved the library name, the tamper would change nothing and the case would
still MATCH.

Darwin-gated: every replay re-invokes inside the macOS Seatbelt sandbox.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.corpus.case import load_case, write_case
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.invariants import EGRESS_UNOBSERVABLE, LIBRARY

from fixtures.create_server import CREATED_CONTENT, REPLY_TEXT as CREATE_REPLY
from fixtures.delete_server import REPLY_TEXT as DELETE_REPLY
from fixtures.scope_free_editor_server import REPLY_TEXT as SRC_REPLY
from fixtures.weakening_editor_server import REPLY_TEXT as TESTS_REPLY

FIXTURES = Path(__file__).parent / "fixtures"
CREATE_CMD = [sys.executable, str(FIXTURES / "create_server.py")]
DELETE_CMD = [sys.executable, str(FIXTURES / "delete_server.py")]
EDITOR_CMD = [sys.executable, str(FIXTURES / "weakening_editor_server.py")]
SRC_EDITOR_CMD = [sys.executable, str(FIXTURES / "scope_free_editor_server.py")]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox",
)


# --- layer 1: the cheat guards -----------------------------------------------------------
#
# The guard is the anti-vacuity contract of the fixtures below: a differential test that
# proves a cheat server produces a FAIL proves nothing if the server does not actually cheat.
# These two guards drive the servers over REAL stdio pipes and assert on the filesystem
# effect — a green A1 verdict on either turn would be a false PASS.


def _drive_server(cmd: list[str], cwd: Path, requests: list[dict]) -> list[dict]:
    """Spawn `cmd` with `cwd` as its workspace and feed it the JSON-RPC requests.

    The servers are line-delimited stdio servers (the house pattern): each request gets one
    response, and the process exits when stdin closes. Returns the parsed responses, in
    request order.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
    )
    payload = b"\n".join(json.dumps(req).encode("utf-8") for req in requests) + b"\n"
    stdout, stderr = proc.communicate(payload, timeout=15.0)
    if proc.returncode != 0:
        raise RuntimeError(
            f"server {cmd!r} exited {proc.returncode}\nstderr:\n{stderr.decode(errors='replace')}"
        )
    return [json.loads(line) for line in stdout.split(b"\n") if line]


def test_create_server_really_creates_the_target_file(tmp_path: Path) -> None:
    """`create_server.py` really creates `generated/new_file.txt` on `tools/call`.

    If this guard ever fails, every `no-create` fixture below proves nothing: the turn would
    replay a no-op, A1 would PASS, and the corrupt-success fixture would be a false FAIL.
    """
    work = tmp_path / "work"
    work.mkdir()
    responses = _drive_server(
        CREATE_CMD,
        work,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "create_file", "arguments": {}},
            },
        ],
    )
    assert len(responses) == 3, responses
    assert responses[-1]["result"]["isError"] is False, responses[-1]

    target = work / "generated" / "new_file.txt"
    assert target.is_file(), (
        "create_server.py did not create generated/new_file.txt — the no-create fixtures "
        "would pass vacuously (a turn that creates nothing cannot violate no-create)"
    )
    assert target.read_text(encoding="utf-8") == CREATED_CONTENT


def test_delete_server_really_deletes_the_target_file(tmp_path: Path) -> None:
    """`delete_server.py` really deletes `docs/todo.txt` on `tools/call`.

    The pre-state MUST contain the file (this is exactly the false-PASS edge the plan names:
    a delete turn whose pre-state lacks the file replays a no-op and A1 would PASS). The
    guard seeds the file, so the deletion below is a real observed effect.
    """
    work = tmp_path / "work"
    (work / "docs").mkdir(parents=True)
    target = work / "docs" / "todo.txt"
    target.write_text("todo: ship belay\n", encoding="utf-8")

    responses = _drive_server(
        DELETE_CMD,
        work,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "delete_file", "arguments": {}},
            },
        ],
    )
    assert len(responses) == 3, responses
    assert responses[-1]["result"]["isError"] is False, responses[-1]

    assert not target.exists(), (
        "delete_server.py did not delete docs/todo.txt — the no-delete fixtures would pass "
        "vacuously (a turn that deletes nothing cannot violate no-delete)"
    )