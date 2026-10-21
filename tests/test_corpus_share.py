"""Issue #58: the shareable PATTERN CATALOG — a strict whitelist, never a raw case.

Phase 2's third goal is "the team's failure corpus as a queryable, growing asset", but a
case bundles the trace, the pre-state tree and the server command. The no-raw-data-egress
guardrail forbids moving those, so what travels is the *pattern*: the whitelisted facts
that made the case a case. This file pins that whitelist in three ways:

1. **The key set is exact.** `pattern_of` emits exactly the PRD's eight keys, and the
   sub-verdict entries carry exactly `axis`/`kind`/`status`. An extra key is a leak by
   construction, so it is a test failure, not a review question.
2. **Nothing forbidden reaches the bytes.** The serialized bundle is searched for
   sentinels planted in every non-whitelisted field (trace, manifest, pre-state, server
   command, case id, provenance, paths, arguments, content, cause strings, miss notes).
3. **Import is fail-closed.** A bundle that is not exactly this schema is refused whole,
   with a named `ValueError` — never partially merged, never silently defaulted.

And the rule the whole feature rests on: **imported patterns are NOT cases.** They are
never replayed and never scored; `patterns.json` is a file beside the case directories, and
`corpus run`/`score`/`list` are byte-identical with it present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.corpus.case import Case
from belay.corpus.share import (
    PATTERN_SCHEMA,
    build_bundle,
    parse_bundle,
    pattern_id,
    pattern_of,
)

#: The exact whitelist. If this changes, the PRD changed.
FACTS = {"label", "reduced_status", "sub_verdicts", "tools", "invariant_rules", "trajectory", "claim"}
ENTRY_KEYS = FACTS | {"pattern_id"}


def _case(
    cid: str = "case-a",
    label: str = "true-positive",
    *,
    status: str = "FAIL",
    tool: str | None = "edit_file",
    rules: tuple[str, ...] = ("read-only",),
    scope: str = "tests/",
    trajectory: dict | None = None,
    claim: dict | None = None,
) -> Case:
    """A case carrying every field, with the forbidden ones set to unique sentinels.

    The sentinels are what the leak test searches for; the whitelisted values are ordinary
    so the exact-key assertions stay readable.
    """
    return Case(
        id=cid,
        target_turn_index=7,
        expected={
            "reduced_status": status,
            "sub_verdicts": [
                {"axis": "A2", "kind": "effect", "status": "PASS"},
                {"axis": "A1", "kind": "invariant", "status": "FAIL"},
            ],
        },
        human_label=label,
        invariants=[{"scope": scope, "rule": rule} for rule in rules],
        server_command=["SECRET-SERVER-COMMAND", "editor_server.py"],
        replays=3,
        timeout=30.0,
        provenance={
            "source_trace_id": "SECRET-TRACE-ID",
            "captured_at": "SECRET-CAPTURED-AT",
        },
        capture_platform="darwin",
        capture_capabilities=["SECRET-CAPABILITY"],
        root_cause={"key": "secret-cause-key", "note": "SECRET-CAUSE-NOTE"},
        target_tool=tool,
        recorded_miss=None,
        trajectory=trajectory,
        claim=claim,
    )


# --- Task 1: the whitelist and the bundle ------------------------------------------------


def test_pattern_is_exactly_the_whitelist() -> None:
    """`pattern_of` emits the eight facts and nothing else — sub-verdicts are axis/kind/status."""
    case = _case(
        trajectory={"status": "FAIL", "cause": "SECRET-TRAJECTORY-CAUSE"},
        rules=("read-only", "no-assertion-weakening", "read-only"),
    )

    pattern = pattern_of(case)

    assert set(pattern) == FACTS
    assert pattern["label"] == "true-positive"
    assert pattern["reduced_status"] == "FAIL"
    assert pattern["tools"] == ["edit_file"]
    # The RULE NAMES only — the scope (a path) is never part of a pattern.
    assert pattern["invariant_rules"] == ["no-assertion-weakening", "read-only"]
    # Deterministic order, so two cases that saw the same pattern serialize identically.
    assert pattern["sub_verdicts"] == [
        {"axis": "A1", "kind": "invariant", "status": "FAIL"},
        {"axis": "A2", "kind": "effect", "status": "PASS"},
    ]
    # The STATUS only: a trajectory/claim cause is a string the pattern never carries.
    assert pattern["trajectory"] == "FAIL"
    assert pattern["claim"] is None


def test_pattern_of_a_plainer_case_uses_empty_lists_and_none() -> None:
    """No tool, no invariants, no instance-level verdict -> `[]`/`None`, never a default claim."""
    pattern = pattern_of(_case(tool=None, rules=()))

    assert pattern["tools"] == []
    assert pattern["invariant_rules"] == []
    assert pattern["trajectory"] is None
    assert pattern["claim"] is None


def test_pattern_id_is_stable_across_case_instances_and_label_sensitive() -> None:
    """Same facts -> same id (dedupe), a different label -> a different id (no laundering)."""
    a = pattern_of(_case(cid="case-a"))
    b = pattern_of(_case(cid="completely-different-case-name"))
    assert pattern_id(a) == pattern_id(b)

    assert pattern_id(a).startswith("sha256:")
    assert len(pattern_id(a)) == len("sha256:") + 64
    int(pattern_id(a)[len("sha256:"):], 16)  # hex, not a case id

    c = pattern_of(_case(cid="case-a", label="false-positive"))
    assert pattern_id(a) != pattern_id(c)


def test_bundle_is_sorted_deduped_and_self_describing() -> None:
    """Two identical cases collapse to one entry; entries are sorted by id."""
    bundle = build_bundle(
        [
            _case(cid="z", tool="write_file"),
            _case(cid="a", tool="edit_file"),
            _case(cid="dup-of-a", tool="edit_file"),
        ]
    )

    assert bundle["schema"] == PATTERN_SCHEMA == "belay-corpus-patterns/1"
    ids = [entry["pattern_id"] for entry in bundle["patterns"]]
    assert ids == sorted(ids)
    assert len(ids) == 2
    assert all(set(entry) == ENTRY_KEYS for entry in bundle["patterns"])


def test_empty_corpus_builds_a_valid_empty_bundle() -> None:
    """AC-6: an empty corpus exports an empty bundle that parses back to nothing."""
    bundle = build_bundle([])

    assert bundle == {"schema": PATTERN_SCHEMA, "patterns": []}
    assert parse_bundle(bundle) == []


def test_parse_bundle_round_trips_build_bundle() -> None:
    """What `build_bundle` writes, `parse_bundle` accepts and returns unchanged."""
    bundle = build_bundle([_case(cid="a"), _case(cid="b", tool="write_file")])

    assert parse_bundle(json.loads(json.dumps(bundle))) == bundle["patterns"]


def test_no_forbidden_fact_reaches_the_serialized_bundle() -> None:
    """The byte-level leak proof, for every field the whitelist excludes.

    Every sentinel is a string this feature must never move: the trace and manifest (which
    are not even fields of `Case` — the export test covers the files), the server command,
    the case id, provenance, the invariant *scope* (a path), a root-cause note, a recorded
    miss note, and every trajectory/claim cause or check source.
    """
    cases = [
        _case(cid="SECRET-CASE-ID", trajectory={"status": "UNVERIFIED", "cause": "SECRET-TRAJECTORY-CAUSE"}),
        _case(
            cid="SECRET-CASE-ID-2",
            status="PASS",
            claim={
                "status": "UNVERIFIED",
                "cause": "SECRET-CLAIM-CAUSE",
                "check": {"source": "SECRET-CHECK-SOURCE", "exit_code": 1},
            },
        ),
    ]
    cases.append(
        Case(
            **{
                **_case(cid="SECRET-CASE-ID-3").__dict__,
                "recorded_miss": {"note": "SECRET-MISS-NOTE"},
            }
        )
    )

    serialized = json.dumps(build_bundle(cases), sort_keys=True)

    for forbidden in (
        "SECRET-CASE-ID",
        "SECRET-SERVER-COMMAND",
        "SECRET-TRACE-ID",
        "SECRET-CAPTURED-AT",
        "SECRET-CAPABILITY",
        "SECRET-CAUSE-NOTE",
        "SECRET-MISS-NOTE",
        "SECRET-TRAJECTORY-CAUSE",
        "SECRET-CLAIM-CAUSE",
        "SECRET-CHECK-SOURCE",
        "tests/",  # the invariant SCOPE, a path — only the rule name travels
        "secret-cause-key",
        "provenance",
        "server_command",
        "manifest",
        "prestate",
        "trace",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "raw, needle",
    [
        ([], "object"),
        ({"patterns": []}, "schema"),
        ({"schema": "belay-corpus-patterns/2", "patterns": []}, "schema"),
        ({"schema": PATTERN_SCHEMA, "patterns": [], "extra": 1}, "unknown"),
        ({"schema": PATTERN_SCHEMA, "patterns": {}}, "list"),
        ({"schema": PATTERN_SCHEMA, "patterns": ["nope"]}, "object"),
        ({"schema": PATTERN_SCHEMA, "patterns": [{"label": "pending"}]}, "missing"),
    ],
)
def test_parse_bundle_refuses_a_malformed_bundle(raw, needle: str) -> None:
    """A bundle that is not exactly this schema is refused whole, named, never repaired."""
    with pytest.raises(ValueError) as exc:
        parse_bundle(raw)
    assert needle in str(exc.value)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p.update(label="bogus"), "label"),
        (lambda p: p.update(reduced_status="NOT_COVERED"), "reduced_status"),
        (lambda p: p.update(sub_verdicts=[{"axis": "A1", "kind": "x", "status": "MAYBE"}]), "sub_verdicts"),
        (lambda p: p.update(sub_verdicts=[{"axis": "A1", "kind": "x", "status": "FAIL", "extra": 1}]), "sub_verdicts"),
        (lambda p: p.update(tools="edit_file"), "tools"),
        (lambda p: p.update(tools=[1]), "tools"),
        (lambda p: p.update(invariant_rules="read-only"), "invariant_rules"),
        (lambda p: p.update(trajectory="NOT_COVERED"), "trajectory"),
        (lambda p: p.update(trajectory="bogus"), "trajectory"),
        (lambda p: p.update(claim="PASS"), "claim"),
        (lambda p: p.update(unknown_fact="x"), "unknown"),
        (lambda p: p.pop("claim"), "missing"),
        (lambda p: p.update(pattern_id="sha256:deadbeef"), "pattern_id"),
    ],
)
def test_parse_bundle_refuses_a_malformed_entry(mutate, needle: str) -> None:
    """Each whitelisted key is required and typed; an extra key or a bad id refuses the whole."""
    pattern = pattern_of(_case())
    pattern["claim"] = "UNVERIFIED"
    entry = {"pattern_id": pattern_id(pattern), **pattern}
    mutate(entry)

    with pytest.raises(ValueError) as exc:
        parse_bundle({"schema": PATTERN_SCHEMA, "patterns": [entry]})
    assert needle in str(exc.value)


# --- Task 2: storage and the three commands ----------------------------------------------


def _write_case(corpus: Path, case: Case) -> Path:
    """Write a real case directory, with sibling artifacts that must never leave."""
    from belay.corpus.case import write_case

    case_dir = corpus / case.id
    write_case(case_dir, case)
    (case_dir / "trace.jsonl").write_text('{"SECRET-TRACE-LINE": true}\n', encoding="utf-8")
    (case_dir / "manifest.json").write_text(
        '{"tree_path": "SECRET-MANIFEST-PATH"}', encoding="utf-8"
    )
    (case_dir / "prestate").mkdir()
    (case_dir / "prestate" / "SECRET-PRESTATE-FILE").write_text(
        "SECRET-PRESTATE-CONTENT", encoding="utf-8"
    )
    return case_dir


def test_save_and_load_patterns_round_trip_and_missing_is_empty(tmp_path: Path) -> None:
    """Missing `patterns.json` is an empty catalog; save/load round-trips; a file, not a dir."""
    from belay.corpus.share import PATTERNS_FILENAME, load_patterns, save_patterns

    corpus = tmp_path / "corpus"
    assert load_patterns(corpus) == []

    patterns = build_bundle([_case(cid="a")])["patterns"]
    save_patterns(corpus, patterns)

    assert (corpus / PATTERNS_FILENAME).is_file()
    assert load_patterns(corpus) == patterns
    assert [p.name for p in corpus.iterdir()] == [PATTERNS_FILENAME]


def test_saved_patterns_bytes_are_deterministic_and_order_independent(tmp_path: Path) -> None:
    """The same catalog in any input order writes the same bytes (indent=2, sorted keys)."""
    from belay.corpus.share import save_patterns

    a = build_bundle([_case(cid="a"), _case(cid="b", tool="write_file")])["patterns"]
    b = list(reversed(a))

    save_patterns(tmp_path / "one", a)
    save_patterns(tmp_path / "two", b)
    assert (tmp_path / "one" / "patterns.json").read_bytes() == (
        tmp_path / "two" / "patterns.json"
    ).read_bytes()

    text = (tmp_path / "one" / "patterns.json").read_text(encoding="utf-8")
    assert text.startswith("{\n  \"patterns\"") or text.startswith("{\n  \"schema\"")
    assert text == json.dumps(
        {"schema": PATTERN_SCHEMA, "patterns": a}, indent=2, sort_keys=True
    ) + "\n"


def test_load_patterns_refuses_a_malformed_file(tmp_path: Path) -> None:
    """A corrupt catalog is a named refusal, never an empty read that hides patterns."""
    from belay.corpus.share import PATTERNS_FILENAME, load_patterns

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / PATTERNS_FILENAME).write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_patterns(corpus)
    assert "patterns.json" in str(exc.value)

    (corpus / PATTERNS_FILENAME).write_text(
        json.dumps({"schema": "belay-corpus-patterns/2", "patterns": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError) as exc:
        load_patterns(corpus)
    assert "patterns.json" in str(exc.value) and "schema" in str(exc.value)


def test_merge_patterns_dedupes_by_id_and_sorts() -> None:
    """A second import adds only new patterns; the result is always sorted by id."""
    from belay.corpus.share import merge_patterns

    existing = build_bundle([_case(cid="a"), _case(cid="b", tool="write_file")])["patterns"]
    new = build_bundle([_case(cid="dup-of-a"), _case(cid="c", tool="move_file")])["patterns"]

    merged = merge_patterns(existing, new)

    assert [entry["pattern_id"] for entry in merged] == sorted(
        entry["pattern_id"] for entry in merged
    )
    assert len(merged) == 3
    assert merged == merge_patterns(existing, new)  # idempotent


def test_cli_share_export_writes_only_whitelisted_facts(tmp_path: Path, capsys) -> None:
    """AC-1: the file carries the eight facts; no sibling artifact or secret reaches it."""
    from belay import cli

    corpus = tmp_path / "corpus"
    _write_case(
        corpus,
        _case(
            cid="SECRET-CASE-ID",
            trajectory={"status": "FAIL", "cause": "SECRET-TRAJECTORY-CAUSE"},
            rules=("read-only",),
            scope="SECRET-SCOPE-PATH/",
        ),
    )
    out = tmp_path / "patterns.json"

    rc = cli.main(
        ["corpus", "share", "export", "--corpus-dir", str(corpus), "--out", str(out)]
    )
    assert rc == 0

    text = out.read_text(encoding="utf-8")
    bundle = json.loads(text)
    assert bundle["schema"] == PATTERN_SCHEMA
    assert [set(entry) == ENTRY_KEYS for entry in bundle["patterns"]] == [True]

    for forbidden in (
        "SECRET-CASE-ID",
        "SECRET-TRACE-LINE",
        "SECRET-MANIFEST-PATH",
        "SECRET-PRESTATE-FILE",
        "SECRET-PRESTATE-CONTENT",
        "SECRET-TRAJECTORY-CAUSE",
        "SECRET-SERVER-COMMAND",
        "SECRET-TRACE-ID",
        "SECRET-CAPTURED-AT",
        "SECRET-CAPABILITY",
        "SECRET-CAUSE-NOTE",
        "SECRET-SCOPE-PATH",
        str(corpus),
    ):
        assert forbidden not in text

    printed = capsys.readouterr().out
    assert "1 case(s) -> 1 pattern(s)" in printed
    assert "NOT cases" in printed and "never replayed" in printed and "never scored" in printed


def test_cli_share_export_is_deterministic(tmp_path: Path) -> None:
    """Two exports of the same corpus are byte-identical."""
    from belay import cli

    corpus = tmp_path / "corpus"
    _write_case(corpus, _case(cid="a"))
    _write_case(corpus, _case(cid="b", tool="write_file"))

    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    assert cli.main(["corpus", "share", "export", "--corpus-dir", str(corpus), "--out", str(first)]) == 0
    assert cli.main(["corpus", "share", "export", "--corpus-dir", str(corpus), "--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()


def test_cli_share_export_of_an_empty_corpus_is_a_valid_empty_bundle(tmp_path: Path, capsys) -> None:
    """AC-6: no cases -> exit 0 and a bundle that imports as nothing, even with no dir yet."""
    from belay import cli

    out = tmp_path / "empty.json"
    rc = cli.main(
        ["corpus", "share", "export", "--corpus-dir", str(tmp_path / "absent"), "--out", str(out)]
    )
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "schema": PATTERN_SCHEMA,
        "patterns": [],
    }
    assert cli.main(["corpus", "share", "import", str(out), "--corpus-dir", str(tmp_path / "fresh")]) == 0


def test_cli_share_export_refuses_a_corrupt_case_without_writing(tmp_path: Path, capsys) -> None:
    """A corrupt case is exit 2 and NO output file: an export is never partial."""
    from belay import cli

    corpus = tmp_path / "corpus"
    _write_case(corpus, _case(cid="good"))
    broken = corpus / "broken"
    broken.mkdir()
    (broken / "case.json").write_text('{"id": "broken"}', encoding="utf-8")
    out = tmp_path / "patterns.json"

    rc = cli.main(
        ["corpus", "share", "export", "--corpus-dir", str(corpus), "--out", str(out)]
    )
    assert rc == 2
    assert not out.exists()
    assert "missing required field" in capsys.readouterr().out


def test_cli_share_import_is_idempotent_and_round_trips(tmp_path: Path, capsys) -> None:
    """AC-3: importing the exported bundle twice adds nothing the second time."""
    from belay import cli
    from belay.corpus.share import PATTERNS_FILENAME, load_patterns

    source = tmp_path / "source"
    _write_case(source, _case(cid="a"))
    _write_case(source, _case(cid="b", tool="write_file"))
    out = tmp_path / "bundle.json"
    assert cli.main(["corpus", "share", "export", "--corpus-dir", str(source), "--out", str(out)]) == 0

    destination = tmp_path / "destination"
    assert cli.main(["corpus", "share", "import", str(out), "--corpus-dir", str(destination)]) == 0
    first_bytes = (destination / PATTERNS_FILENAME).read_bytes()
    first_out = capsys.readouterr().out
    assert "2 added" in first_out

    assert cli.main(["corpus", "share", "import", str(out), "--corpus-dir", str(destination)]) == 0
    assert "0 added" in capsys.readouterr().out
    assert (destination / PATTERNS_FILENAME).read_bytes() == first_bytes
    assert len(load_patterns(destination)) == 2

    ids = [entry["pattern_id"] for entry in load_patterns(destination)]
    assert ids == sorted(ids)


def test_cli_share_import_refuses_a_malformed_bundle_whole(tmp_path: Path, capsys) -> None:
    """AC-3: a malformed/unknown-schema bundle is exit 2, named, and writes nothing."""
    from belay import cli
    from belay.corpus.share import PATTERNS_FILENAME

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema": "belay-corpus-patterns/1",
                "patterns": [{"pattern_id": "sha256:00", "label": "pending"}],
            }
        ),
        encoding="utf-8",
    )

    rc = cli.main(["corpus", "share", "import", str(bad), "--corpus-dir", str(corpus)])
    assert rc == 2
    printed = capsys.readouterr().out
    assert "pattern bundle" in printed and "missing" in printed
    assert not (corpus / PATTERNS_FILENAME).exists()

    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"schema": "belay-corpus-patterns/9", "patterns": []}), encoding="utf-8")
    assert cli.main(["corpus", "share", "import", str(unknown), "--corpus-dir", str(corpus)]) == 2
    assert "schema" in capsys.readouterr().out
    assert not (corpus / PATTERNS_FILENAME).exists()


def test_cli_share_list_counts_by_label_rule_and_tool(tmp_path: Path, capsys) -> None:
    """AC-4: text counts by label/rule/tool, and says plainly that patterns are not scored."""
    from belay import cli
    from belay.corpus.share import save_patterns

    corpus = tmp_path / "corpus"
    save_patterns(
        corpus,
        build_bundle(
            [
                _case(cid="a", label="true-positive", tool="edit_file"),
                _case(cid="b", label="pending", tool="write_file", rules=("no-assertion-weakening",)),
            ]
        )["patterns"],
    )

    rc = cli.main(["corpus", "share", "list", "--corpus-dir", str(corpus)])
    assert rc == 0
    out = capsys.readouterr().out

    assert "2 pattern(s)" in out
    assert "by label" in out
    assert "true-positive" in out and "pending" in out
    assert "by rule" in out
    assert "read-only" in out and "no-assertion-weakening" in out
    assert "by tool" in out
    assert "edit_file" in out and "write_file" in out
    assert "NOT cases" in out and "never replayed" in out and "never scored" in out


def test_cli_share_list_json_is_machine_readable(tmp_path: Path, capsys) -> None:
    """`--json` gives the same counts as a document, and says `scored: false`."""
    from belay import cli
    from belay.corpus.share import save_patterns

    corpus = tmp_path / "corpus"
    save_patterns(corpus, build_bundle([_case(cid="a"), _case(cid="b", label="pending")])["patterns"])

    rc = cli.main(["corpus", "share", "list", "--corpus-dir", str(corpus), "--json"])
    assert rc == 0
    document = json.loads(capsys.readouterr().out)

    assert document["schema"] == PATTERN_SCHEMA
    assert document["count"] == 2
    assert document["labels"] == {"pending": 1, "true-positive": 1}
    assert document["rules"] == {"read-only": 2}
    assert document["tools"] == {"edit_file": 2}
    assert document["scored"] is False


def test_patterns_json_does_not_change_corpus_list_or_score(tmp_path: Path, capsys) -> None:
    """AC-5: a catalog beside the cases leaves `corpus list`/`score` byte-identical."""
    from belay import cli
    from belay.corpus.share import save_patterns

    corpus = tmp_path / "corpus"
    _write_case(corpus, _case(cid="a", label="true-positive", status="FAIL"))
    _write_case(corpus, _case(cid="b", label="false-positive", status="PASS", tool="write_file"))

    def render() -> str:
        assert cli.main(["corpus", "list", str(corpus)]) == 0
        listed = capsys.readouterr().out
        assert cli.main(["corpus", "score", str(corpus)]) == 0
        scored = capsys.readouterr().out
        return listed + scored

    before = render()
    save_patterns(corpus, build_bundle([_case(cid="a"), _case(cid="b")])["patterns"])
    after = render()
    assert after == before
    assert "pattern(s)" not in after


def test_patterns_json_is_never_replayed_as_a_case(tmp_path: Path, capsys) -> None:
    """AC-5: `corpus run` iterates dirs, so a catalog file is never a case to replay."""
    from belay import cli
    from belay.corpus.run import run_corpus
    from belay.corpus.share import save_patterns

    corpus = tmp_path / "corpus"
    save_patterns(corpus, build_bundle([_case(cid="a")])["patterns"])

    assert run_corpus(corpus).results == []
    assert cli.main(["corpus", "run", str(corpus)]) == 0
    out = capsys.readouterr().out
    assert "0 case(s)" in out
