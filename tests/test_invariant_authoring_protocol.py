"""Phase 1 — the authoring protocol: input builder, response parser, subprocess seam.

Tests for `src/belay/authoring/protocol.py` (the `authoring-protocol` aspect, phases
1-2). The author is an out-of-process BYOK command: JSON in on stdin, JSON out on
stdout. Everything here is offline through the injectable runner seam — no model, no
network, no `claude` binary.

The protocol contract, stated once:

- **The engine never calls a model.** The author command is the operator's own; this
  module builds the payload it is allowed to see (D-7: task text + bounded repo
  inventory + rule vocabulary + library entries, never the control's records or path).
- **Fail-closed, never raising.** A non-zero exit, a timeout, a launch failure, malformed
  stdout, an unknown rule, a malformed candidate — every failure is a named outcome
  (`failure` / `rejection`), never a crash and never a silently swallowed policy.
- **Candidates are the model's proposal, not policy.** Validation (known rule, sane
  shape), deterministic dedup and ordering happen here; calibration against the control
  happens later, in the infer orchestration, by execution.
"""

import json
import subprocess

from belay.authoring.protocol import (
    AUTHOR_FAILED,
    AUTHOR_OUTPUT_UNPARSEABLE,
    CANDIDATE_MALFORMED,
    NO_AUTHOR_CONFIGURED,
    UNKNOWN_RULE,
    Candidate,
    Rejection,
    SubprocessInvariantAuthor,
    build_author_input,
    parse_author_response,
)
from belay.verify.invariants import (
    LIBRARY,
    RULE_NETWORK_EGRESS,
    _KNOWN_RULES,
)

_MAX_OUTPUT = 1024 * 1024

#: Names the payload must never carry (D-7): the control trace's records, its path, or
#: the manifests/snapshots replay needs. Asserted on the SERIALIZED bytes — a stray key
#: anywhere in the payload would surface as one of these substrings.
_FORBIDDEN = (b"trace", b"manifest", b"record", b"snapshot", b"control", b".belay")


# ---------------------------------------------------------------------------
# build_author_input
# ---------------------------------------------------------------------------


def test_build_author_input_carries_task_text():
    payload = build_author_input(task_text="make the failing test pass")
    assert payload["task"] == "make the failing test pass"
    assert "repo" not in payload


def test_build_author_input_omits_repo_when_no_files():
    payload = build_author_input(task_text="t")
    assert "repo" not in payload


def test_build_author_input_repo_files_sorted_and_bounded():
    files = [f"path/to/file{i:04d}.py" for i in range(5005)]
    payload = build_author_input(task_text="t", repo_files=files)
    repo = payload["repo"]
    assert repo["root"] == "repo"
    assert len(repo["files"]) == 5000
    assert repo["files"] == sorted(files)[:5000]
    assert repo["files"][0] == "path/to/file0000.py"
    assert repo["files"][-1] == "path/to/file4999.py"


def test_build_author_input_repo_preserves_order_of_given_sorted_files():
    files = ["b.py", "a.py", "c.py"]
    payload = build_author_input(task_text="t", repo_files=files)
    assert payload["repo"]["files"] == ["a.py", "b.py", "c.py"]


def test_build_author_input_rules_cover_every_known_rule():
    payload = build_author_input(task_text="t")
    rules = {entry["rule"]: entry for entry in payload["rules"]}
    assert set(rules) == set(_KNOWN_RULES) | {RULE_NETWORK_EGRESS}
    for rule, entry in rules.items():
        assert entry["rule"] == rule
        assert isinstance(entry["grounding"], str) and entry["grounding"]
        assert isinstance(entry["semantics"], str) and entry["semantics"]


def test_build_author_input_network_egress_documented_ungrounded():
    payload = build_author_input(task_text="t")
    by_rule = {entry["rule"]: entry for entry in payload["rules"]}
    assert by_rule[RULE_NETWORK_EGRESS]["grounding"] == "ungrounded"


def test_build_author_input_library_entries():
    payload = build_author_input(task_text="t")
    library = {entry["name"]: entry for entry in payload["library"]}
    assert set(library) == set(LIBRARY)
    for name, entry in library.items():
        assert entry["name"] == name
        assert entry["description"] == LIBRARY[name].description


def test_build_author_input_serialized_payload_has_no_control_artifacts():
    payload = build_author_input(
        task_text="make the failing test pass",
        repo_files=["tests/test_auth.py", "src/app.py"],
    )
    serialized = json.dumps(payload, sort_keys=True).encode("utf-8")
    for forbidden in _FORBIDDEN:
        assert forbidden not in serialized, (
            f"author payload leaked a control artifact substring {forbidden!r}; "
            f"D-7 forbids the control's records/path/manifests reaching the author"
        )


# ---------------------------------------------------------------------------
# parse_author_response — happy paths
# ---------------------------------------------------------------------------


def test_parse_returns_candidates():
    response = parse_author_response(
        json.dumps(
            {
                "candidates": [
                    {
                        "scope": "tests/",
                        "rule": "read-only",
                        "rationale": "tests must not be edited",
                    }
                ]
            }
        )
    )
    assert response.failure is None
    assert response.rejections == []
    assert response.candidates == [
        Candidate(
            scope="tests/", rule="read-only", rationale="tests must not be edited"
        )
    ]


def test_parse_accepts_missing_and_non_str_rationale():
    response = parse_author_response(
        json.dumps(
            {
                "candidates": [
                    {"scope": "src/", "rule": "read-only"},
                    {"scope": "src/", "rule": "no-create", "rationale": 7},
                ]
            }
        )
    )
    assert response.candidates == [
        Candidate(scope="src/", rule="no-create", rationale=None),
        Candidate(scope="src/", rule="read-only", rationale=None),
    ]


def test_parse_empty_candidates():
    response = parse_author_response(json.dumps({"candidates": []}))
    assert response.failure is None
    assert response.candidates == []
    assert response.rejections == []


# ---------------------------------------------------------------------------
# parse_author_response — the optional model id (additive, infer carries it)
# ---------------------------------------------------------------------------


def test_parse_carries_top_level_model_string():
    response = parse_author_response(
        json.dumps(
            {
                "model": "claude-opus-5",
                "candidates": [{"scope": "tests/", "rule": "read-only"}],
            }
        )
    )
    assert response.failure is None
    assert response.model == "claude-opus-5"
    assert response.candidates == [
        Candidate(scope="tests/", rule="read-only", rationale=None)
    ]


def test_parse_absent_model_is_none():
    response = parse_author_response(json.dumps({"candidates": []}))
    assert response.model is None


def test_parse_non_str_model_is_none():
    response = parse_author_response(json.dumps({"model": 7, "candidates": []}))
    assert response.model is None


# ---------------------------------------------------------------------------
# parse_author_response — determinism
# ---------------------------------------------------------------------------


def test_parse_deduplicates_and_sorts_by_rule_scope():
    response = parse_author_response(
        json.dumps(
            {
                "candidates": [
                    {"scope": "z/", "rule": "read-only", "rationale": "dup b"},
                    {"scope": "a/", "rule": "no-create"},
                    {"scope": "z/", "rule": "read-only", "rationale": "dup a"},
                    {"scope": "m/", "rule": "no-assertion-weakening"},
                ]
            }
        )
    )
    assert response.candidates == [
        Candidate(scope="m/", rule="no-assertion-weakening", rationale=None),
        Candidate(scope="a/", rule="no-create", rationale=None),
        Candidate(scope="z/", rule="read-only", rationale="dup b"),
    ]


# ---------------------------------------------------------------------------
# parse_author_response — fail-closed failure shapes
# ---------------------------------------------------------------------------


def test_parse_error_is_author_failed():
    response = parse_author_response(json.dumps({"error": "the model said no"}))
    assert response.failure == AUTHOR_FAILED
    assert response.candidates == []
    assert response.rejections == []


def test_parse_error_wins_over_candidates():
    response = parse_author_response(
        json.dumps(
            {
                "error": "boom",
                "candidates": [{"scope": "tests/", "rule": "read-only"}],
            }
        )
    )
    assert response.failure == AUTHOR_FAILED
    assert response.candidates == []


def test_parse_malformed_json_is_unparseable():
    response = parse_author_response("this is not json {")
    assert response.failure == AUTHOR_OUTPUT_UNPARSEABLE
    assert response.candidates == []
    assert response.rejections == []


def test_parse_non_object_is_unparseable():
    response = parse_author_response(json.dumps([1, 2, 3]))
    assert response.failure == AUTHOR_OUTPUT_UNPARSEABLE


def test_parse_missing_candidates_is_unparseable():
    response = parse_author_response(json.dumps({"scope": "tests/"}))
    assert response.failure == AUTHOR_OUTPUT_UNPARSEABLE


def test_parse_non_list_candidates_is_unparseable():
    response = parse_author_response(json.dumps({"candidates": {"scope": "x"}}))
    assert response.failure == AUTHOR_OUTPUT_UNPARSEABLE


# ---------------------------------------------------------------------------
# parse_author_response — per-candidate rejections, never a crash
# ---------------------------------------------------------------------------


def test_parse_unknown_rule_is_rejected_others_kept():
    response = parse_author_response(
        json.dumps(
            {
                "candidates": [
                    {"scope": "tests/", "rule": "totally-made-up"},
                    {"scope": "tests/", "rule": "read-only"},
                ]
            }
        )
    )
    assert response.failure is None
    assert response.candidates == [
        Candidate(scope="tests/", rule="read-only", rationale=None)
    ]
    assert response.rejections == [
        Rejection(
            scope="tests/", rule="totally-made-up", rationale=None, cause=UNKNOWN_RULE
        )
    ]


def test_parse_network_egress_is_rejected_unknown_rule():
    response = parse_author_response(
        json.dumps({"candidates": [{"scope": "", "rule": RULE_NETWORK_EGRESS}]})
    )
    assert response.candidates == []
    assert response.rejections == [
        Rejection(
            scope="", rule=RULE_NETWORK_EGRESS, rationale=None, cause=UNKNOWN_RULE
        )
    ]


def test_parse_non_str_scope_is_rejected():
    response = parse_author_response(
        json.dumps({"candidates": [{"scope": 42, "rule": "read-only"}]})
    )
    assert response.candidates == []
    assert response.rejections == [
        Rejection(
            scope=None, rule="read-only", rationale=None, cause=CANDIDATE_MALFORMED
        )
    ]


def test_parse_empty_scope_is_whole_tree():
    """An empty scope is a whole-tree declaration — the library's `no-create` / `no-delete`
    presets are exactly `{"scope": "", ...}` (`invariants.py` LIBRARY), and a resolved
    entry is byte-identical policy to a file-loaded declaration, so the author must be
    able to propose the same shape. Over-breadth is calibration's job, never a rejection
    here (a whole-tree `read-only` fails the calibration control, it is not malformed)."""
    response = parse_author_response(
        json.dumps({"candidates": [{"scope": "", "rule": "read-only"}]})
    )
    assert response.candidates == [
        Candidate(scope="", rule="read-only", rationale=None)
    ]
    assert response.rejections == []


def test_parse_non_str_rule_is_rejected():
    response = parse_author_response(
        json.dumps({"candidates": [{"scope": "tests/", "rule": 9}]})
    )
    assert response.candidates == []
    assert response.rejections == [
        Rejection(scope="tests/", rule=None, rationale=None, cause=CANDIDATE_MALFORMED)
    ]


def test_parse_empty_rule_is_rejected():
    response = parse_author_response(
        json.dumps({"candidates": [{"scope": "tests/", "rule": ""}]})
    )
    assert response.candidates == []
    assert response.rejections == [
        Rejection(scope="tests/", rule="", rationale=None, cause=CANDIDATE_MALFORMED)
    ]


def test_parse_non_dict_candidate_is_rejected():
    response = parse_author_response(json.dumps({"candidates": ["read-only"]}))
    assert response.candidates == []
    assert response.rejections == [
        Rejection(scope=None, rule=None, rationale=None, cause=CANDIDATE_MALFORMED)
    ]


def test_parse_hostile_candidates_never_crash():
    payload = {
        "candidates": [
            1,
            None,
            {"scope": None, "rule": []},
            {"scope": "", "rule": ""},
            {"rule": "read-only"},
            {"scope": "tests/", "rule": "read-only", "rationale": {"nested": True}},
            {"scope": "src/", "rule": "no-delete", "rationale": None},
        ]
    }
    response = parse_author_response(json.dumps(payload))
    assert response.failure is None
    assert response.candidates == [
        Candidate(scope="src/", rule="no-delete", rationale=None),
        Candidate(scope="tests/", rule="read-only", rationale=None),
    ]
    assert len(response.rejections) == 5
    assert all(r.cause == CANDIDATE_MALFORMED for r in response.rejections)


# ---------------------------------------------------------------------------
# Cause constants
# ---------------------------------------------------------------------------


def test_cause_constants_are_stable_names():
    assert NO_AUTHOR_CONFIGURED == "NO_AUTHOR_CONFIGURED"


# ---------------------------------------------------------------------------
# SubprocessInvariantAuthor — the subprocess seam (injectable runner)
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, returncode=0, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


class _RecordingRunner:
    def __init__(self, proc):
        self._proc = proc
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((tuple(command), kwargs))
        return self._proc


class _RaisingRunner:
    def __init__(self, exc):
        self._exc = exc

    def __call__(self, *args, **kwargs):
        raise self._exc


def test_author_defaults_runner_to_subprocess_run():
    author = SubprocessInvariantAuthor(("some-author",))
    assert author.runner is subprocess.run
    assert author.command == ("some-author",)
    assert author.timeout == 60.0


def test_author_sends_serialized_payload_on_stdin():
    runner = _RecordingRunner(_FakeProc(0, b'{"candidates": []}'))
    author = SubprocessInvariantAuthor(("fake-author",), runner=runner)
    payload = {"task": "make tests pass", "rules": []}
    assert author.author(payload) == '{"candidates": []}'
    assert len(runner.calls) == 1
    command, kwargs = runner.calls[0]
    assert command == ("fake-author",)
    assert kwargs["input"] == json.dumps(payload, sort_keys=True).encode("utf-8")
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == 60.0
    assert kwargs["check"] is False


def test_author_nonzero_exit_is_none():
    author = SubprocessInvariantAuthor(
        ("fake-author",),
        runner=_RecordingRunner(_FakeProc(returncode=3, stdout=b"boom")),
    )
    assert author.author({"task": "t"}) is None


def test_author_timeout_is_none():
    author = SubprocessInvariantAuthor(
        ("fake-author",),
        runner=_RaisingRunner(subprocess.TimeoutExpired("fake-author", 60.0)),
    )
    assert author.author({"task": "t"}) is None


def test_author_launch_failure_is_none():
    author = SubprocessInvariantAuthor(
        ("no-such-binary",), runner=_RaisingRunner(FileNotFoundError("no such file"))
    )
    assert author.author({"task": "t"}) is None


def test_author_caps_stdout_at_one_mib():
    big = b"x" * (_MAX_OUTPUT + 10)
    author = SubprocessInvariantAuthor(
        ("fake-author",), runner=_RecordingRunner(_FakeProc(0, big))
    )
    out = author.author({"task": "t"})
    assert out is not None
    assert len(out.encode("utf-8")) == _MAX_OUTPUT


def test_author_never_raises_on_unserializable_payload():
    author = SubprocessInvariantAuthor(
        ("fake-author",), runner=_RecordingRunner(_FakeProc(0, b'{"candidates": []}'))
    )
    assert author.author({"task": {"a", "b"}}) is None
