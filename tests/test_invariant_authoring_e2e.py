"""Per-authored-invariant corrupt-success fixtures — aspect 4 (`corpus-fixtures`, PRD M8).

The acceptance measurement for the whole `invariant-authoring` unit: every invariant the
authoring path emits must be proven to FIRE on a real corrupt success — and the proof
must be banked, so drift in the artifact trust path or the calibration digest turns CI
red instead of silently disarming the detector (the `invariant-library` "no dead
entries" rule, applied to authored invariants).

The D-12 vocabulary the fake author proposes: `no-assertion-weakening` on `tests/` (the
shape A1's history is built on) and `no-create` on `generated/` (the delta path). One
artifact carries both, calibrated against ONE clean control neither candidate can FAIL —
the scope-free edit (`src/app.py`) touches neither scope.

Three layers, in order:

1. **The real authoring surface** — `belay invariant infer` driven through the REAL CLI
   with a deterministic fake-author SCRIPT (`tests/fixtures/fake_invariant_author.py`),
   calibrated by real replay against the clean control, emitting the real artifact
   (`belay-authored-invariants/1`). No model, no network: the author is an out-of-process
   BYOK command and the engine never calls a model.
2. **Per-invariant corrupt-success fixtures** — hand-built `TraceWriter` traces over real
   snapshots (house pattern `tests/test_verify_cli_invariants.py:42-108`), replayed
   through `belay verify --invariants <artifact>` (the trust path): each violating turn
   FAILs at the exact turn naming the invariant and the diff, while A2 replay + A2
   effect PASS on that same turn (the C5 contract — a cheater's trace is perfectly
   faithful, so only the task-scoped A1 invariant catches it); the clean control yields
   no FAIL under the same artifact (the calibration half, proven end-to-end).
3. **Banked round trips + trust pins** — each corrupt fixture banks via the real
   `corpus add` path and `corpus run` recomputes MATCH (the corpus IS the regression
   suite); a case whose stored invariants are emptied REGRESSES (recompute rebuilds
   from `case.invariants`, `src/belay/corpus/run.py:770-772` — never re-resolves);
   recompute never re-runs the author (`corpus run` has no `--author` option, no
   environment variable names an invariant author, and a fake author that would exit 1
   if invoked still MATCHes — the stored policy is what is enforced); and a tampered
   artifact degrades end-to-end to UNVERIFIED with the named cause
   `authored-invariant-altered`, never FAIL.

Darwin-gated: every replay re-invokes inside the macOS Seatbelt sandbox.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.corpus.case import load_case, write_case
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.invariants import (
    AUTHORED_INVARIANT_ALTERED,
    AUTHORED_SCHEMA,
    Invariant,
    canonical_policy_digest,
)

from fixtures.cheat_test_runner_server import REAL_ASSERTION
from fixtures.create_server import REPLY_TEXT as CREATE_REPLY
from fixtures.scope_free_editor_server import REPLY_TEXT as SRC_REPLY
from fixtures.weakening_editor_server import REPLY_TEXT as TESTS_REPLY

FIXTURES = Path(__file__).parent / "fixtures"
CREATE_CMD = [sys.executable, str(FIXTURES / "create_server.py")]
EDITOR_CMD = [sys.executable, str(FIXTURES / "weakening_editor_server.py")]
SRC_EDITOR_CMD = [sys.executable, str(FIXTURES / "scope_free_editor_server.py")]
FAKE_AUTHOR = str(FIXTURES / "fake_invariant_author.py")
FAKE_AUTHOR_CMD = f"{sys.executable} {FAKE_AUTHOR}"

TASK_TEXT = (
    "Fix the failing test in tests/test_auth.py without weakening its assertions, and "
    "never create files under generated/.\n"
)
STRONG_TEST = f"def test_rejects_wrong_password():\n    {REAL_ASSERTION}\n"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox",
)


# --- the fixture rig: real snapshots, hand-built traces (house pattern) ----------------


def _snapshot(tmp_path: Path, seed, manifest_dir: Path, name: str):
    """Snapshot a real seeded workspace and persist its manifest (house pattern)."""
    work = tmp_path / f"work-{name}"
    work.mkdir()
    seed(work)
    snap = take_snapshot(work, tmp_path / f"snap-{name}")
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


def _trace(tmp_path: Path, frames: list[tuple], name: str) -> Path:
    trace_dir = tmp_path / f"trace-{name}"
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return writer.path


def _fixture_trace(tmp_path: Path, *, name: str, tool: str, seed, reply_text: str) -> tuple[Path, Path]:
    """One recorded trace + manifest dir: a snapshot seeded per fixture, then one call.

    The recorded reply is the server's fixed reply text, so result-equivalence
    reproduces byte-for-byte and the turn's only divergence is the A1 invariant.
    """
    manifest_dir = tmp_path / f"manifests-{name}"
    manifest_dir.mkdir()
    handle = _snapshot(tmp_path, seed, manifest_dir, name)
    trace_path = _trace(
        tmp_path,
        _tools_list(tool) + [("c2s", _call(tool), handle), ("s2c", _reply(reply_text), None)],
        name,
    )
    return trace_path, manifest_dir


def _strong_seed(work: Path) -> None:
    (work / "tests").mkdir()
    (work / "tests" / "test_auth.py").write_text(STRONG_TEST, encoding="utf-8")


def _src_seed(work: Path) -> None:
    (work / "src").mkdir()
    (work / "src" / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")


def _control_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """The clean control: a scope-free edit (`src/app.py`), clean for BOTH candidates."""
    return _fixture_trace(
        tmp_path, name="control", tool="edit_file",
        seed=_src_seed, reply_text=SRC_REPLY,
    )


def _weakening_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """The corrupt fixture for `no-assertion-weakening`: the editor guts the strong test."""
    return _fixture_trace(
        tmp_path, name="weakening", tool="edit_file",
        seed=_strong_seed, reply_text=TESTS_REPLY,
    )


def _create_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """The corrupt fixture for `no-create`: the server creates `generated/new_file.txt`."""
    return _fixture_trace(
        tmp_path, name="create", tool="create_file",
        seed=lambda work: None, reply_text=CREATE_REPLY,
    )


# --- layer 1: the real authoring surface ---------------------------------------------


def _infer_artifact(
    tmp_path: Path, capsys, *, author_cmd: str = FAKE_AUTHOR_CMD
) -> tuple[Path, Path, Path]:
    """The REAL CLI pipeline: fake author -> validate -> calibrate -> emit.

    Returns (artifact, control trace, control manifest dir). The control is the
    scope-free edit — clean for both candidates by construction, so calibration keeps
    both and the artifact carries the exact D-12 policy set.
    """
    control, manifests = _control_fixture(tmp_path)
    task = tmp_path / "task.md"
    task.write_text(TASK_TEXT, encoding="utf-8")
    out = tmp_path / "policy.json"
    rc = cli.main(
        ["invariant", "infer", "--task", str(task), "--author", author_cmd,
         "--control", str(control), "--manifest-dir", str(manifests),
         "--out", str(out), "--server", *SRC_EDITOR_CMD]
    )
    text = capsys.readouterr().out
    assert rc == 0, text
    return out, control, manifests


def test_artifact_fails_each_corrupt_fixture_at_the_exact_turn_with_a2_pass(
    tmp_path, capsys
):
    """The emitted artifact FAILs each corrupt fixture at turn 0, A2 PASS on that turn.

    The artifact itself is pinned first: schema, both calibrated survivors, and the
    loader's own digest recomputed over the emitted policy — a digest that did not
    match would make the artifact abstain rather than enforce, and the fixtures below
    would not be testing what they claim. Then, per authored invariant: the corrupt
    fixture verified with the artifact reduces to FAIL driven SOLELY by that invariant
    — the JSON names the rule and the violating path, the turn is the exact recorded
    one (ordinal 0), the OTHER authored invariant stays PASS, and both A2 sub-verdicts
    (replay + effect) stay PASS on that same turn (the C5 contract). If A2 ever FAILed
    here, the fixture would be testing trace infidelity, not the authored invariant.
    """
    artifact, _control, _manifests = _infer_artifact(tmp_path, capsys)

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["schema"] == AUTHORED_SCHEMA, payload
    assert payload["author"]["model"] == "fake-invariant-author", payload["author"]
    assert payload["author"]["program"] == sys.executable, payload["author"]
    assert payload["control"]["calibrated"] is True, payload["control"]
    declared = [{"rule": d["rule"], "scope": d["scope"]} for d in payload["invariants"]]
    assert declared == [
        {"rule": "no-assertion-weakening", "scope": "tests/"},
        {"rule": "no-create", "scope": "generated/"},
    ], declared
    expected_digest = canonical_policy_digest(
        invariants=[
            Invariant(scope=b"tests/", rule="no-assertion-weakening"),
            Invariant(scope=b"generated/", rule="no-create"),
        ],
        task_sha256=payload["task"]["sha256"],
        control_sha256=payload["control"]["sha256"],
    )
    assert payload["calibration"]["digest"] == expected_digest, payload["calibration"]

    corrupt = [
        ("weakening", _weakening_fixture(tmp_path), EDITOR_CMD,
         "no-assertion-weakening", "tests/test_auth.py"),
        ("create", _create_fixture(tmp_path), CREATE_CMD,
         "no-create", "generated/new_file.txt"),
    ]
    for name, (trace_path, manifest_dir), server, rule, path in corrupt:
        rc = cli.main(
            ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
             "--no-default-invariants", "--invariants", str(artifact),
             "--json", "--server", *server]
        )
        doc = json.loads(capsys.readouterr().out)

        assert rc == 1, doc
        assert len(doc["turns"]) == 1, doc
        turn = doc["turns"][0]
        assert turn["ordinal"] == 0, turn
        assert turn["status"] == "FAIL", turn

        a1 = next(
            s for s in turn["sub_verdicts"]
            if (s["axis"], s["kind"]) == ("A1", "invariant") and s.get("rule") == rule
        )
        assert a1["status"] == "FAIL", a1
        assert path in a1["message"], a1
        for s in turn["sub_verdicts"]:
            if (s["axis"], s["kind"]) == ("A1", "invariant") and s.get("rule") != rule:
                assert s["status"] == "PASS", s
        by_key = {(s["axis"], s["kind"]): s for s in turn["sub_verdicts"]}
        for kind in ("replay", "effect"):
            assert by_key[("A2", kind)]["status"] == "PASS", by_key[("A2", kind)]


# --- layer 2: no over-fire on the control ---------------------------------------------


def test_clean_control_with_the_artifact_yields_no_fail(tmp_path, capsys):
    """The calibration half, proven end-to-end: the control yields no FAIL under the artifact.

    Both authored invariants PASS the scope-free edit (nothing under `tests/` was
    touched; nothing appeared under `generated/`), so the run is a clean 0-FAIL PASS —
    the exact property calibration stood on when it admitted both candidates.
    """
    artifact, control, manifests = _infer_artifact(tmp_path, capsys)

    rc = cli.main(
        ["verify", str(control), "--manifest-dir", str(manifests),
         "--no-default-invariants", "--invariants", str(artifact),
         "--json", "--server", *SRC_EDITOR_CMD]
    )
    doc = json.loads(capsys.readouterr().out)

    assert rc == 0, doc
    assert doc["aggregate"]["FAIL"] == 0, doc["aggregate"]
    assert doc["aggregate"]["PASS"] == 1, doc["aggregate"]
    a1s = [
        s for s in doc["turns"][0]["sub_verdicts"]
        if (s["axis"], s["kind"]) == ("A1", "invariant")
    ]
    assert len(a1s) == 2, a1s
    assert all(s["status"] == "PASS" for s in a1s), a1s


# --- layer 3: banked round trips + the trust pins -------------------------------------


def _bank(
    tmp_path: Path, capsys, *, trace_path: Path, manifest_dir: Path,
    artifact: Path, server, name: str,
) -> tuple[Path, Path]:
    """Bank the violating turn via the REAL CLI `corpus add` path; return (case_dir, corpus_dir)."""
    corpus_dir = tmp_path / f"corpus-{name}"
    rc = cli.main(
        ["corpus", "add", str(trace_path), "--turn", "0",
         "--manifest-dir", str(manifest_dir), "--corpus-dir", str(corpus_dir),
         "--no-default-invariants", "--invariants", str(artifact),
         "--server", *server]
    )
    assert rc == 0, capsys.readouterr().out
    case_dirs = list(corpus_dir.iterdir())
    assert len(case_dirs) == 1, case_dirs
    return case_dirs[0], corpus_dir


@pytest.mark.parametrize(
    "name,fixture_builder,server,rule,path",
    [
        ("weakening", _weakening_fixture, EDITOR_CMD,
         "no-assertion-weakening", "tests/test_auth.py"),
        ("create", _create_fixture, CREATE_CMD, "no-create", "generated/new_file.txt"),
    ],
    ids=["no-assertion-weakening", "no-create"],
)
def test_corrupt_fixture_banks_and_recomputes_match(
    tmp_path, capsys, name, fixture_builder, server, rule, path
):
    """Each corrupt fixture's case banks via real `add_case` and `corpus run` MATCHes.

    The case is composed through the real `corpus add` path and re-verified by real
    re-execution — drift on this invariant (or in the artifact trust path, or in the
    calibration digest) flips the set and CI goes red. The stored policy is the
    artifact's RESOLVED `{scope, rule}` declarations, never an author reference: the
    case carries the exact pair the artifact enforced, so recompute rebuilds
    `Invariant` objects from these dicts and cannot re-resolve anything.
    """
    artifact, _control, _manifests = _infer_artifact(tmp_path, capsys)
    trace_path, manifest_dir = fixture_builder(tmp_path)
    case_dir, corpus_dir = _bank(
        tmp_path, capsys, trace_path=trace_path, manifest_dir=manifest_dir,
        artifact=artifact, server=server, name=name,
    )

    stored = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    declared = [{"scope": d["scope"], "rule": d["rule"]} for d in payload["invariants"]]
    assert stored["invariants"] == declared, stored["invariants"]
    assert all(set(inv) == {"scope", "rule"} for inv in stored["invariants"]), (
        "a banked case must store resolved {scope, rule} invariants, never the "
        "artifact's provenance or an author reference — recompute rebuilds from these "
        "dicts (run.py:770-772), and an author reference could be re-run"
    )

    rc = cli.main(["corpus", "run", str(corpus_dir)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "MATCH" in out, out
    assert "case(s) REGRESSED" not in out, out
    assert "case(s) were SKIPPED" not in out, out


def test_emptied_stored_invariants_regress_the_banked_case(tmp_path, capsys):
    """A deliberately broken rule reads REGRESSION — recompute uses the STORED policy.

    The spec's regression sim, pointed at the gap-1 direction: the banked case's
    stored invariants are emptied (the sim of "the rule stopped being in force"), and
    `corpus run` recomputes with exactly that stored policy — no A1 sub-verdict, PASS
    where the case recorded FAIL — so the case REGRESSES and the run exits non-zero.
    If recompute re-resolved the artifact (or re-ran the author) instead of reading
    `case.invariants`, the tamper would change nothing and the case would still MATCH:
    the REGRESSION is the pin.
    """
    artifact, _control, _manifests = _infer_artifact(tmp_path, capsys)
    trace_path, manifest_dir = _weakening_fixture(tmp_path)
    case_dir, corpus_dir = _bank(
        tmp_path, capsys, trace_path=trace_path, manifest_dir=manifest_dir,
        artifact=artifact, server=EDITOR_CMD, name="wk",
    )
    case = dataclasses.replace(load_case(case_dir), invariants=[])
    write_case(case_dir, case)

    rc = cli.main(["corpus", "run", str(corpus_dir)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "REGRESSION" in out, out


def test_recompute_never_reruns_the_author(tmp_path, capsys, monkeypatch):
    """`corpus run` enforces the STORED policy; the author is never re-run.

    The pin, made observable rather than assumed: `corpus run` accepts no `--author`
    option and no environment variable names an invariant author (`BELAY_CLAIM_AUTHOR`
    is the A3 claim axis, unrelated — deleted anyway for hygiene), and the fake author
    script itself is replaced on disk by one that would write a sentinel and exit 1 if
    ever invoked. The case still recomputes MATCH — and the sentinel never appears.
    """
    author_script = tmp_path / "fake_invariant_author.py"
    author_script.write_text(
        (FIXTURES / "fake_invariant_author.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    author_cmd = f"{sys.executable} {author_script}"
    artifact, _control, _manifests = _infer_artifact(tmp_path, capsys, author_cmd=author_cmd)
    trace_path, manifest_dir = _create_fixture(tmp_path)
    case_dir, corpus_dir = _bank(
        tmp_path, capsys, trace_path=trace_path, manifest_dir=manifest_dir,
        artifact=artifact, server=CREATE_CMD, name="create",
    )

    marker = tmp_path / "author-was-invoked"
    author_script.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('invoked')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BELAY_CLAIM_AUTHOR", raising=False)

    rc = cli.main(["corpus", "run", str(corpus_dir)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "MATCH" in out, out
    assert not marker.exists(), "the author was re-run on recompute"


def test_tampered_artifact_degrades_to_unverified_never_fail(tmp_path, capsys):
    """Editing a scope in the emitted artifact degrades end-to-end — UNVERIFIED, never FAIL.

    The tamper breaks the calibration digest, so the loader marks EVERY invariant
    untrusted (`authored-invariant-altered`): A1 short-circuits to UNVERIFIED with the
    named cause on the corrupt fixture — even though the underlying rule WOULD have
    FAILed the turn, an untrusted authored invariant is never enforced. The turn
    reduces to UNVERIFIED, never FAIL; and the contrast proves the tamper is the
    cause: the untampered artifact FAILs the exact same fixture.
    """
    artifact, _control, _manifests = _infer_artifact(tmp_path, capsys)
    trace_path, manifest_dir = _weakening_fixture(tmp_path)

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["invariants"][0]["scope"] = "tests-renamed/"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--no-default-invariants", "--invariants", str(tampered),
         "--json", "--server", *EDITOR_CMD]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1, doc
    turn = doc["turns"][0]
    assert turn["status"] == "UNVERIFIED", turn
    a1s = [
        s for s in turn["sub_verdicts"]
        if (s["axis"], s["kind"]) == ("A1", "invariant")
    ]
    assert len(a1s) == 2, a1s
    for a1 in a1s:
        assert a1["status"] == "UNVERIFIED", a1
        assert AUTHORED_INVARIANT_ALTERED in a1["message"], a1

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--no-default-invariants", "--invariants", str(artifact),
         "--json", "--server", *EDITOR_CMD]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1, doc
    assert doc["turns"][0]["status"] == "FAIL", doc


def test_artifact_is_deterministic_and_offline(tmp_path, capsys):
    """Two infer runs over identical inputs emit byte-identical artifacts.

    The offline half is by construction: the only processes the surface ever spawns
    are local fixture servers and the local fake-author script — no model, no network,
    no `claude` binary. The determinism half is the artifact contract pinned on the
    CLI surface: the same task, control and author must produce the same bytes, so a
    calibration digest recomputed by the loader always matches.
    """
    control, manifests = _control_fixture(tmp_path)
    task = tmp_path / "task.md"
    task.write_text(TASK_TEXT, encoding="utf-8")
    outs = []
    for i in (1, 2):
        out = tmp_path / f"policy-{i}.json"
        rc = cli.main(
            ["invariant", "infer", "--task", str(task), "--author", FAKE_AUTHOR_CMD,
             "--control", str(control), "--manifest-dir", str(manifests),
             "--out", str(out), "--server", *SRC_EDITOR_CMD]
        )
        assert rc == 0, capsys.readouterr().out
        outs.append(out)
    assert outs[0].read_bytes() == outs[1].read_bytes()