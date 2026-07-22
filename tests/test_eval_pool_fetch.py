"""The pure row -> pool transform behind the committed SWE-bench-lite instance pool.

`eval/scripts/fetch_swebench_pool.py` has two halves that must never be confused:
`main()`, which touches the HuggingFace datasets-server exactly once and is run **by a
human**, and `rows_to_pool`, which is a pure function from already-fetched rows to
validated `InstanceRecord`s. Only the second half is tested here, against a hand-written
fixture in the recorded API shape — so this file is deterministic, offline, and CI-safe,
and it survives any regeneration of `pool.json`.

Two of these tests are not "coverage", they are scar tissue:

* `test_pool_fetch_repo_is_a_slug_not_a_url` — `workspace.py:99` builds the clone URL as
  `https://github.com/{repo}.git`, so a `repo` that is already a URL double-prefixes and
  the clone fails at prep time, after budget has been spent. **This bit Stage 1.** The
  transform must *raise* on a URL rather than normalize it: a URL in the source means our
  assumption about the dataset is wrong, and quietly fixing it up hides that.
* `test_pool_fetch_transform_touches_no_network` — an `ast` walk (mirroring
  `tests/test_import_guard.py`) proving `urllib` is imported inside `main` and nowhere
  else. Importing this module must not put a network client anywhere near the test suite;
  a static walk is the only thing that guarantees it, because an import that *works* in
  this venv leaves no other trace.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from eval.instances.registry import dump_registry, load_registry
from eval.instances.tasks import TASK_PREFIX, derive_task_string
from eval.scripts.fetch_swebench_pool import (
    MAX_CHANGED_LINES,
    MAX_STATEMENT_CHARS,
    REVISION_NOTE,
    build_header,
    changed_line_count,
    rows_to_pool,
)

FIXTURE = Path(__file__).parent / "fixtures" / "swebench_rows_sample.json"

MODULE = (
    Path(__file__).parent.parent / "eval" / "scripts" / "fetch_swebench_pool.py"
)


def _fixture_rows() -> list[dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = payload["rows"]
    assert len(rows) == 6, (
        "the fixture is meant to carry exactly 6 rows (2 keepers, 1 known-excluded "
        "repo, 1 oversized patch, 1 overlong statement, 1 unknown repo); if it has "
        "changed, the tier counts below are no longer meaningful"
    )
    return rows


def _row(**overrides) -> dict:
    """One row envelope in the recorded API shape, before any override."""
    row = {
        "instance_id": "pallets__flask-1234",
        "repo": "pallets/flask",
        "base_commit": "d8c37f43724cd9fb0870f77877b7c4c7e38a19e0",
        "problem_statement": "Something is broken and should be fixed.",
        "patch": (
            "diff --git a/src/flask/app.py b/src/flask/app.py\n"
            "--- a/src/flask/app.py\n"
            "+++ b/src/flask/app.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-    old = 1\n"
            "+    new = 1\n"
        ),
    }
    row.update(overrides)
    return {"row_idx": 0, "row": row, "truncated_cells": []}


# --------------------------------------------------------------------------------------
# AC1 — every produced record is a valid registry record
# --------------------------------------------------------------------------------------


def test_pool_fetch_produces_valid_registry(tmp_path: Path) -> None:
    """**AC1.** Every produced record survives a `dump_registry` -> `load_registry`.

    The loader is fail-closed on missing/blank fields, so a round trip is the strongest
    available statement that nothing the transform emits can mint a run with an empty
    `base_commit` or an empty task.
    """
    records, _counts = rows_to_pool(_fixture_rows())

    assert records, "the fixture must yield at least one keeper or this test is vacuous"

    path = tmp_path / "pool.json"
    dump_registry(records, path)

    assert load_registry(path) == records

    for record in records:
        assert record.task_string == derive_task_string(record.problem_statement)
        assert record.task_string.startswith(TASK_PREFIX)
        assert record.is_control is False


# --------------------------------------------------------------------------------------
# AC1 — the Stage-1 bug: `repo` is a slug, never a URL
# --------------------------------------------------------------------------------------


def test_pool_fetch_repo_is_a_slug_not_a_url() -> None:
    """**AC1 / D1.** `repo` is `owner/name`; a URL in the source is a loud failure.

    `prepare_workspace` builds `https://github.com/{repo}.git` from this field and caches
    the clone under `repo.replace("/", "__")`. A URL here double-prefixes and the clone
    dies at prep time — silently, until a live run burns budget on it.
    """
    records, _counts = rows_to_pool(_fixture_rows())

    for record in records:
        assert "://" not in record.repo
        assert "github.com" not in record.repo
        assert not record.repo.endswith(".git")
        owner, _, name = record.repo.partition("/")
        assert owner and name and "/" not in name, (
            f"repo {record.repo!r} is not an owner/name slug"
        )


@pytest.mark.parametrize(
    "bad_repo",
    [
        "https://github.com/pallets/flask",
        "git@github.com:pallets/flask.git",
        "pallets/flask.git",
        "flask",
        "",
    ],
)
def test_pool_fetch_raises_on_a_repo_that_is_not_a_slug(bad_repo: str) -> None:
    """A non-slug `repo` **raises**; it is never normalized into one.

    Normalizing would hide the thing that actually matters: our assumption about the
    dataset's shape is wrong. The failure must be at fetch time, in front of a human,
    not at clone time in the middle of a paid batch.
    """
    with pytest.raises(ValueError) as excinfo:
        rows_to_pool([_row(repo=bad_repo)])

    assert "repo" in str(excinfo.value)
    assert bad_repo in str(excinfo.value) or "blank" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# The three strict filters
# --------------------------------------------------------------------------------------


def test_pool_fetch_applies_the_strict_filters() -> None:
    """Each of the three filters drops exactly its own row, and the counts say so.

    The counts are what lands in `pool.json`'s provenance header, so they must be the
    real tier sizes rather than a re-derivation someone types by hand later.
    """
    records, counts = rows_to_pool(_fixture_rows())

    kept = {record.instance_id for record in records}
    assert kept == {"pallets__flask-4045", "psf__requests-2317"}

    assert counts == {
        "all": 6,
        "pure_python": 4,  # matplotlib (excluded repo) and acme/widget (unknown) drop
        "small_patch": 3,  # the django row's patch exceeds the changed-line budget
        "short_statement": 2,  # the sympy row's problem statement exceeds the budget
    }


def test_pool_fetch_excludes_unknown_repos(capsys: pytest.CaptureFixture[str]) -> None:
    """Allow-list, not deny-list — and the exclusion is *reported*, never silent.

    A repo that appears in a refetched dataset and is in neither list is a dataset
    change. Excluding it keeps the pool safe; printing it keeps the change visible.
    """
    records, counts = rows_to_pool(_fixture_rows())

    assert all(record.repo != "acme/widget" for record in records)
    assert all(record.repo != "matplotlib/matplotlib" for record in records)

    reported = capsys.readouterr().err
    assert "acme/widget" in reported, (
        "a repo in neither the allow-list nor the known-excluded list must be reported"
    )
    assert "matplotlib/matplotlib" not in reported, (
        "a KNOWN excluded repo is expected and must not be reported as dataset drift"
    )
    assert counts["pure_python"] == 4


def test_pool_fetch_skips_and_reports_a_blank_problem_statement(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A blank statement is skipped and reported, never minted as an empty task.

    `derive_task_string` raises on a whitespace-only statement precisely because an
    empty task would drive an agent to do nothing and quietly become a mint instance
    that proves nothing.
    """
    records, counts = rows_to_pool(
        [_row(instance_id="pallets__flask-blank", problem_statement="   \n  ")]
    )

    assert records == ()
    assert counts["small_patch"] == 1
    assert counts["short_statement"] == 0
    assert "pallets__flask-blank" in capsys.readouterr().err


def test_pool_fetch_raises_on_a_missing_row_field() -> None:
    """A row missing a consumed field raises rather than defaulting it to `""`."""
    envelope = _row()
    del envelope["row"]["base_commit"]

    with pytest.raises(ValueError) as excinfo:
        rows_to_pool([envelope])

    assert "base_commit" in str(excinfo.value)


def test_pool_fetch_raises_on_a_row_envelope_without_a_row() -> None:
    """The transform consumes the API's `{"row_idx", "row"}` envelope, and says so."""
    with pytest.raises(ValueError) as excinfo:
        rows_to_pool([{"row_idx": 0}])

    assert "row" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# D5 — the changed-line counting rule
# --------------------------------------------------------------------------------------


def test_changed_line_count_ignores_diff_headers() -> None:
    """**D5.** Count `+`/`-` lines; exclude `+++`/`---` headers, `@@` hunks, context.

    Written down and tested because this rule decides which instances are eligible, and
    an off-by-two here changes the pool. The measured survey tiers (300 -> 239 -> 204 ->
    166) were produced by *some* rule; if ours disagrees, the discrepancy gets recorded,
    the rule does not get tuned until 166 falls out of the real data.
    """
    patch = (
        "diff --git a/pkg/mod.py b/pkg/mod.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/pkg/mod.py\n"
        "+++ b/pkg/mod.py\n"
        "@@ -10,7 +10,8 @@ def f():\n"
        "     context line\n"
        "-    removed_one = 1\n"
        "-    removed_two = 2\n"
        "+    added_one = 1\n"
        "+    added_two = 2\n"
        "+    added_three = 3\n"
        "     another context line\n"
        "\\ No newline at end of file\n"
    )

    assert changed_line_count(patch) == 5

    assert changed_line_count("") == 0
    assert changed_line_count("--- a/x\n+++ b/x\n@@ -1 +1 @@\n") == 0


def test_changed_line_count_thresholds_are_named_constants() -> None:
    """The thresholds are module constants, so the header can publish them verbatim."""
    assert MAX_CHANGED_LINES == 15
    assert MAX_STATEMENT_CHARS == 2000


def test_a_patch_at_the_threshold_is_kept_and_one_over_is_dropped() -> None:
    """The `<= 15` boundary is inclusive — pinned so nobody "clarifies" it later."""
    body = "@@ -1,1 +1,1 @@\n"

    at_limit = _row(
        instance_id="pallets__flask-at-limit",
        patch="--- a/x\n+++ b/x\n" + body + "+a\n" * MAX_CHANGED_LINES,
    )
    over_limit = _row(
        instance_id="pallets__flask-over-limit",
        patch="--- a/x\n+++ b/x\n" + body + "+a\n" * (MAX_CHANGED_LINES + 1),
    )

    kept, _ = rows_to_pool([at_limit])
    dropped, _ = rows_to_pool([over_limit])

    assert [record.instance_id for record in kept] == ["pallets__flask-at-limit"]
    assert dropped == ()


def test_a_statement_at_the_threshold_is_kept_and_one_over_is_dropped() -> None:
    """The `<= 2000` boundary is inclusive, on the raw statement, before derivation."""
    kept, _ = rows_to_pool(
        [_row(instance_id="a__b-1", problem_statement="x " * (MAX_STATEMENT_CHARS // 2))]
    )
    dropped, _ = rows_to_pool(
        [
            _row(
                instance_id="a__b-2",
                problem_statement="x " * (MAX_STATEMENT_CHARS // 2) + "y",
            )
        ]
    )

    assert len(kept) == 1
    assert dropped == ()


# --------------------------------------------------------------------------------------
# The transform is structurally incapable of reaching the network
# --------------------------------------------------------------------------------------


def _urllib_imports(tree: ast.AST) -> list[ast.stmt]:
    """Every import statement in `tree` whose root module is `urllib`."""
    found: list[ast.stmt] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "urllib" for alias in node.names):
                found.append(node)
        elif isinstance(node, ast.ImportFrom):
            if (
                node.level == 0
                and node.module is not None
                and node.module.split(".")[0] == "urllib"
            ):
                found.append(node)
    return found


def test_pool_fetch_transform_touches_no_network() -> None:
    """`urllib` is imported inside `main`, and nowhere else in the module.

    Mirrors `tests/test_import_guard.py`: parse with `ast`, never import the module under
    test. Importing to inspect would run the module's side effects and would report on
    this venv rather than on the source that actually runs. The property is what keeps
    the whole test suite offline — the network lives in one function that no test calls.
    """
    tree = ast.parse(MODULE.read_bytes(), filename=str(MODULE))

    main = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        ),
        None,
    )
    assert main is not None, "fetch_swebench_pool.main is missing — guard is vacuous"

    inside_main = {id(node) for node in ast.walk(main)}

    all_urllib = _urllib_imports(tree)
    assert all_urllib, (
        "no `urllib` import found at all — either the fetch no longer uses the stdlib "
        "HTTP client (check it has not grown a third-party dependency: runtime "
        "dependencies are zero and that is load-bearing), or this guard is vacuous"
    )

    outside = [
        f"line {node.lineno}"
        for node in all_urllib
        if id(node) not in inside_main
    ]
    assert not outside, (
        "`urllib` imported outside main() in eval/scripts/fetch_swebench_pool.py:\n  "
        + "\n  ".join(outside)
        + "\n\nWHY THIS IS A FAILURE: importing this module must not bring a network "
        "client into scope. Tests import `rows_to_pool`; the fetch itself is a "
        "human-run maintenance step whose OUTPUT is committed. Keeping `urllib` inside "
        "main() makes 'the tests never fetch' a structural property rather than a "
        "convention someone can forget."
    )


def test_the_module_imports_only_stdlib_and_first_party() -> None:
    """Zero runtime dependencies is load-bearing; `eval/` does not get an exemption."""
    tree = ast.parse(MODULE.read_bytes(), filename=str(MODULE))

    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    import sys

    offenders = sorted(
        root for root in roots if root != "eval" and root not in sys.stdlib_module_names
    )
    assert not offenders, (
        f"non-stdlib import in the fetch script: {offenders}. The fetch is stdlib-only "
        "on purpose (`urllib.request` + `json` + `argparse`); adding `requests`, "
        "`datasets`, or `huggingface_hub` — even to a dev group — is not in scope."
    )


def test_the_allow_list_is_imported_not_restated() -> None:
    """The fetch imports `PURE_PYTHON_REPOS`; a second copy would drift silently."""
    from eval.instances.selection import PURE_PYTHON_REPOS
    from eval.scripts.fetch_swebench_pool import PURE_PYTHON_REPOS as imported

    assert imported is PURE_PYTHON_REPOS


def test_build_header_publishes_the_constants_and_the_counts() -> None:
    """The header is derived from the code, not typed beside it.

    `build_header` is pure — it takes the clock and the revision as arguments — so the
    one thing worth pinning is that the published thresholds ARE the module constants
    and the published tiers ARE the counts the transform returned. If a threshold were
    ever hand-written into the header, `pool.json` would describe a filter that was
    never applied, and every downstream consistency check would pass while lying.
    """
    _, counts = rows_to_pool(_fixture_rows())

    header = build_header(
        counts,
        num_rows_total=len(_fixture_rows()),
        revision=None,
        fetched_at="2026-07-23T00:00:00+00:00",
    )

    assert header["counts"] == counts
    assert header["counts"] is not counts, "the header must not alias the caller's dict"
    assert header["filters"]["max_changed_lines"] == MAX_CHANGED_LINES
    assert header["filters"]["max_statement_chars"] == MAX_STATEMENT_CHARS
    assert header["filters"]["changed_line_rule"].strip()
    assert header["revision"] is None
    assert header["revision_note"] == REVISION_NOTE, (
        "a null revision must always carry the stated reason: D2 asked for a pin with "
        "an honest fallback, and an unexplained null reads as an oversight"
    )
    assert "instances" not in header, (
        "an 'instances' key in the header would shadow the records; dump_registry "
        "refuses it, and it must never be constructed in the first place"
    )
