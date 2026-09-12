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

from fixtures.cheat_test_runner_server import REAL_ASSERTION
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


# --- layer 2: per-entry corrupt-success fixtures at the CLI ------------------------------
#
# Hand-built `TraceWriter` traces over REAL snapshots (house pattern
# `tests/test_verify_cli_invariants.py:42-108`), replayed through `belay verify
# --invariant-library <entry> --json`. The violating turn must FAIL at the exact turn,
# naming the invariant and the path, with A2 replay + A2 effect PASS on that SAME turn —
# the axes non-redundancy proven per entry on the CLI surface.


STRONG_TEST = f"def test_rejects_wrong_password():\n    {REAL_ASSERTION}\n"

#: One entry's fixture shape: the library name, the server it replays against, the tool the
#: trace records, the pre-state seed (what the snapshot tree contains BEFORE the turn), the
#: server's fixed reply text, the A1 rule the entry resolves to, and the violating path.
#: `source-read-only` reuses the existing `scope_free_editor_server.py` (it writes
#: `src/app.py` — verified, no sibling needed); `tests-read-only` reuses the weakening
#: editor, which proves the flag path end-to-end on the library preset, complementing
#: aspect 2's CLI test with the exact-turn + A2-PASS assertions.
ENTRIES = [
    (
        "no-create",
        CREATE_CMD,
        "create_file",
        lambda work: None,  # empty tree: nothing holds `generated/`, the server creates it
        CREATE_REPLY,
        "no-create",
        "generated/new_file.txt",
    ),
    (
        "no-delete",
        DELETE_CMD,
        "delete_file",
        lambda work: (work / "docs").mkdir() or (work / "docs" / "todo.txt").write_text(
            "todo: ship belay\n", encoding="utf-8"
        ),
        DELETE_REPLY,
        "no-delete",
        "docs/todo.txt",
    ),
    (
        "tests-read-only",
        EDITOR_CMD,
        "edit_file",
        lambda work: (work / "tests").mkdir() or (work / "tests" / "test_auth.py").write_text(
            STRONG_TEST, encoding="utf-8"
        ),
        TESTS_REPLY,
        "read-only",
        "tests/test_auth.py",
    ),
    (
        "source-read-only",
        SRC_EDITOR_CMD,
        "edit_file",
        lambda work: (work / "src").mkdir() or (work / "src" / "app.py").write_text(
            "def handler():\n    return 1\n", encoding="utf-8"
        ),
        SRC_REPLY,
        "read-only",
        "src/app.py",
    ),
]


def _snapshot(tmp_path: Path, seed, manifest_dir: Path):
    """Snapshot a real seeded workspace and persist its manifest (house pattern)."""
    work = tmp_path / "work"
    work.mkdir()
    seed(work)
    snap = take_snapshot(work, tmp_path / "snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    return present_handle(snap)


def _tools_list(tool: str) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [{"name": tool, "annotations": {"readOnlyHint": False}}]
            },
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call(tool: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {}},
        }
    ).encode()


def _reply(reply_text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [{"type": "text", "text": reply_text}],
                "isError": False,
            },
        }
    ).encode()


def _trace(tmp_path: Path, frames: list[tuple]) -> Path:
    trace_dir = tmp_path / "trace"
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return writer.path


def _entry_trace(tmp_path: Path, *, cmd, tool, seed, reply_text) -> tuple[Path, Path]:
    """One violating trace: a snapshot seeded per entry, then one recorded `tools/call`.

    The recorded reply is the server's fixed reply text, so result-equivalence reproduces
    byte-for-byte and the turn's only divergence is the A1 invariant.
    """
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    handle = _snapshot(tmp_path, seed, manifest_dir)
    trace_path = _trace(
        tmp_path,
        _tools_list(tool) + [("c2s", _call(tool), handle), ("s2c", _reply(reply_text), None)],
    )
    return trace_path, manifest_dir


@pytest.mark.parametrize(
    "entry,cmd,tool,seed,reply_text,expected_rule,violating_path",
    ENTRIES,
    ids=[e[0] for e in ENTRIES],
)
def test_library_entry_fails_at_the_exact_turn_with_a2_pass(
    tmp_path,
    capsys,
    entry,
    cmd,
    tool,
    seed,
    reply_text,
    expected_rule,
    violating_path,
) -> None:
    """`belay verify --invariant-library <entry>` FAILs the violating turn, A2 PASS.

    The corrupt-success shape, per entry: the turn reduces to FAIL driven SOLELY by A1 — the
    JSON names the invariant rule and the violating path, the turn is the exact recorded one
    (ordinal 0), and both A2 sub-verdicts (replay + effect) stay PASS on that same turn. If
    A2 ever FAILed here, the fixture would be testing trace infidelity, not the entry.
    """
    trace_path, manifest_dir = _entry_trace(
        tmp_path, cmd=cmd, tool=tool, seed=seed, reply_text=reply_text
    )

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--no-default-invariants", "--invariant-library", entry,
         "--json", "--server", *cmd]
    )
    doc = json.loads(capsys.readouterr().out)

    assert rc == 1, doc
    assert len(doc["turns"]) == 1, doc
    turn = doc["turns"][0]
    assert turn["ordinal"] == 0, turn
    assert turn["status"] == "FAIL", turn

    by_key = {(s["axis"], s["kind"]): s for s in turn["sub_verdicts"]}
    a1 = by_key[("A1", "invariant")]
    assert a1["status"] == "FAIL", a1
    assert a1["rule"] == expected_rule, a1
    assert violating_path in a1["message"], a1
    for kind in ("replay", "effect"):
        assert by_key[("A2", kind)]["status"] == "PASS", by_key[("A2", kind)]