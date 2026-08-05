"""RED-first tests for `eval/scripts/forecast_exposure.py` — the pre-mint forecast.

`under-firing-measurable` (v0.12.0) measured that **9 of 15 instances gave the A1 content
rule zero in-scope files to judge**. Nothing in the record separates *"those 15 draws
happened to be low-exposure"* from *"low exposure is a property of SWE-bench-lite"*. If it
is the population, a mint at n>=50 spends ~11 hours and returns another uninterpretable
near-zero. This script is the offline evidence the owner reads **before** funding it.

**Everything asserted here is about honesty of presentation, not about the answer.** The
fixtures are tiny and synthetic on purpose: a test that asserted `59` would be asserting
the answer rather than the arithmetic, and would have to be edited every time the pool
changes — which is exactly how a measurement gets tuned until it looks right. The real
figures live in one place only, `acceptance.out`, produced by one run of the committed
script (`exposure-forecast/spec.md` criteria 6, 9, 10).

What the tests pin, and why each one is a defect worth a test:

* **Determinism.** Same inputs -> byte-identical output, so `acceptance.out` is a
  re-derivable artifact rather than a transcript of one lucky afternoon.
* **Denominators everywhere.** A bare count is a defect (criterion 2). Asserted on the
  *rendered text*: every line that states a percentage must also carry `N/D`.
* **Pool and launched reported separately** (criterion 3). The draw deliberately
  rebalanced composition, so a combined or averaged figure is a category error — the
  combined denominator must not appear anywhere in the output.
* **Controls partitioned out** of both headlines (criterion 4), following the
  `phase0 combine` precedent.
* **Absent is not zero** (criterion 7). A missing or empty `problem_statement` renders
  `unknown` and is named. This is also why the script does *not* reuse
  `eval.instances.registry.load_registry`: that loader is fail-closed and *raises* on a
  blank required field, which is right for a mint (it would otherwise mint the wrong run)
  and wrong here, where the field's absence is the thing being reported.
* **The token set is read from the module constant** (criterion 6) — patched tokens must
  change both the stated set and the matching, so the output cannot be a stale copy.
* **The honesty paragraph is present and names `flask-4992`** (criterion 8), the known
  false negative: it scores 0/1 on this signal and wrote to a test file four times.
* **No network, no clock, no randomness** — an AST import guard in the spirit of
  `tests/test_verify_zero_llm.py`, so the guard reads the source that ships rather than
  the venv, and fails loud on a new import instead of rotting quietly.
* **The calibration constant transcribes the published table** and is not a re-derivation
  of it: its totals must reproduce 17 comparisons / 7 files / 6 judged / 9 zero.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from eval.scripts import forecast_exposure as fx

# --------------------------------------------------------------------------------------
# Fixture helpers. Deliberately tiny, deliberately not the real pool.
# --------------------------------------------------------------------------------------

#: A statement carrying no token from the frozen set. Checked by a test below rather than
#: assumed, because a fixture that silently matched would make every "no" assertion vacuous.
CLEAN_STATEMENT = "The value returned by the config loader is off by one."

#: A statement carrying exactly one token (`traceback`).
HIT_STATEMENT = "Calling it raises, and the traceback points at the loader."


def _record(
    instance_id: str,
    repo: str,
    *,
    problem_statement: object = CLEAN_STATEMENT,
    task_string: object = "Fix the following issue in this repository:\n\nSomething.",
    is_control: bool = False,
) -> dict:
    """One registry-shaped record. `problem_statement` may be `None` or `""` on purpose."""
    record = {
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": "0" * 40,
        "problem_statement": problem_statement,
        "task_string": task_string,
        "is_control": is_control,
    }
    return record


def _write(path: Path, records: list[dict]) -> Path:
    """A registry file: the committed shape is a dict with an `instances` list."""
    path.write_text(json.dumps({"instances": records}, indent=2) + "\n")
    return path


def _fixture_pair(tmp_path: Path) -> tuple[Path, Path]:
    """A pool of 5 and a launched set of 3 (+1 control) whose rates deliberately DIFFER.

    Pool: 2 of 5 mention a token (40.0%). Launched non-control: 2 of 3 (66.7%). The
    control mentions a token too, so partitioning it out is observable rather than
    incidental. Nothing here is an average of anything else — which is the point.
    """
    pool = _write(
        tmp_path / "pool.json",
        [
            _record("django__django-1", "django/django", problem_statement=HIT_STATEMENT),
            _record("django__django-2", "django/django"),
            _record("sympy__sympy-1", "sympy/sympy", problem_statement=HIT_STATEMENT),
            _record("sympy__sympy-2", "sympy/sympy"),
            _record("sympy__sympy-3", "sympy/sympy"),
        ],
    )
    selected = _write(
        tmp_path / "selected.json",
        [
            _record("django__django-1", "django/django", problem_statement=HIT_STATEMENT),
            _record("sympy__sympy-1", "sympy/sympy", problem_statement=HIT_STATEMENT),
            _record("sympy__sympy-2", "sympy/sympy"),
            _record(
                "control__x",
                "pallets/flask",
                problem_statement="Control instance: the test suite is never touched.",
                is_control=True,
            ),
        ],
    )
    return pool, selected


def _run(pool: Path, selected: Path) -> str:
    """The rendered report for a fixture pair, through the same path `main` uses."""
    return fx.render(
        fx.load_instances(pool),
        fx.load_instances(selected),
        pool_label=str(pool),
        selected_label=str(selected),
    )


# --------------------------------------------------------------------------------------
# The token set and how it matches
# --------------------------------------------------------------------------------------


def test_frozen_token_set_is_exactly_the_committed_nine() -> None:
    """The set is frozen before calibration is computed; a change here is a spec event.

    Pinned verbatim so that "tune the tokens until the cross-reference looks better"
    cannot happen as a quiet edit (criteria 6 and 10). If this test is ever updated, the
    reason belongs in the aspect spec, not in a commit body.
    """
    assert fx.FORECAST_TOKENS == (
        "test",
        "tests",
        "testing",
        "pytest",
        "assert",
        "assertion",
        "failing",
        "traceback",
        "reproduc",
    )


@pytest.mark.parametrize(
    "text",
    [
        "the tests fail",
        "TESTING this is",
        "run pytest -k foo",
        "the assertion is wrong",
        "an assert fires",
        "reproduce it like this",
        "reproduction steps below",
        "a failing case",
        "the traceback says",
        "Tests: none",
    ],
)
def test_word_prefix_match_hits(text: str) -> None:
    assert fx.mentions_token(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "protest about the loader",  # `test` mid-word is not a word-prefix
        "unittest is imported",  # ditto — this is a deliberate, documented miss
        "the failure is silent",  # `failing` does not prefix-match `failure`
        "no signal here at all",
        "",
    ],
)
def test_word_prefix_match_misses(text: str) -> None:
    assert fx.mentions_token(text) is False


def test_clean_fixture_statement_really_is_clean() -> None:
    """Non-vacuity: the "no" fixture must actually be a no, or every negative is empty."""
    assert fx.mentions_token(CLEAN_STATEMENT) is False
    assert fx.mentions_token(HIT_STATEMENT) is True


def test_output_states_the_token_set_read_from_the_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 6: the stated set is the constant, not a hand-copied string beside it.

    Patching the constant must change BOTH the stated set and the matching. A report that
    printed a literal list would pass the first half and fail the second.
    """
    pool, selected = _fixture_pair(tmp_path)
    assert ", ".join(fx.FORECAST_TOKENS) in _run(pool, selected)

    monkeypatch.setattr(fx, "FORECAST_TOKENS", ("banana",))
    patched = _run(pool, selected)
    assert "banana" in patched
    assert "traceback" not in patched.split("HONEST")[0]
    # `HIT_STATEMENT` mentions `traceback`, not `banana`: under the patched set the pool
    # headline must fall to zero, proving the matcher reads the same constant.
    assert "0/5" in patched


# --------------------------------------------------------------------------------------
# Determinism (criterion 1)
# --------------------------------------------------------------------------------------


def test_same_inputs_render_byte_identical(tmp_path: Path) -> None:
    pool, selected = _fixture_pair(tmp_path)
    assert _run(pool, selected) == _run(pool, selected)


def test_main_writes_byte_identical_output_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool, selected = _fixture_pair(tmp_path)
    argv = ["--pool", str(pool), "--selected", str(selected)]

    assert fx.main(argv) == 0
    first = capsys.readouterr().out
    assert fx.main(argv) == 0
    second = capsys.readouterr().out

    assert first == second
    assert first.encode() == second.encode()


# --------------------------------------------------------------------------------------
# Denominators (criterion 2)
# --------------------------------------------------------------------------------------

_PERCENT = re.compile(r"\d+(?:\.\d+)?%")
_FRACTION = re.compile(r"\d+/\d+")


def test_every_line_with_a_percentage_also_carries_its_fraction(tmp_path: Path) -> None:
    """A bare rate is a defect: `36%` of what, out of how many, is the whole question."""
    pool, selected = _fixture_pair(tmp_path)
    offenders = [
        line
        for line in _run(pool, selected).splitlines()
        if _PERCENT.search(line) and not _FRACTION.search(line)
    ]
    assert offenders == []


def test_headline_figures_render_with_their_denominators(tmp_path: Path) -> None:
    pool, selected = _fixture_pair(tmp_path)
    report = _run(pool, selected)
    assert "2/5" in report  # pool: 2 of 5 statements mention a token
    assert "2/3" in report  # launched non-control: 2 of 3
    assert "1/2" in report  # per repo, django
    assert "1/3" in report  # per repo, sympy (pool)


# --------------------------------------------------------------------------------------
# Pool vs launched (criterion 3)
# --------------------------------------------------------------------------------------


def test_pool_and_launched_are_separate_sections_never_averaged(tmp_path: Path) -> None:
    pool, selected = _fixture_pair(tmp_path)
    report = _run(pool, selected)

    assert "POOL" in report
    assert "LAUNCHED" in report
    assert "never averaged" in report.lower()
    # No figure may carry the COMBINED denominator (5 + 4 records, or 5 + 3 non-controls):
    # summing the two populations is the category error this section exists to prevent.
    # Matched as a whole fraction, because the output legitimately cites published figures
    # such as `3/93` whose text contains "/9".
    for combined in (8, 9):
        assert re.search(rf"\b\d+/{combined}\b", report) is None


def test_launched_rate_is_not_the_pool_rate(tmp_path: Path) -> None:
    """The fixture's two populations differ; both figures must survive into the output."""
    pool, selected = _fixture_pair(tmp_path)
    report = _run(pool, selected)
    assert "40.0%" in report  # 2/5
    assert "66.7%" in report  # 2/3


# --------------------------------------------------------------------------------------
# Controls (criterion 4)
# --------------------------------------------------------------------------------------


def test_controls_are_partitioned_out_of_the_launched_headline(tmp_path: Path) -> None:
    """The control mentions a token; counting it would inflate the launched figure to 3/4."""
    pool, selected = _fixture_pair(tmp_path)
    report = _run(pool, selected)

    assert "2/3" in report
    assert "3/4" not in report
    assert "control__x" in report
    assert "CONTROLS" in report


def test_controls_absent_from_the_pool_are_not_reported_as_a_discrepancy(
    tmp_path: Path,
) -> None:
    """The 3 real controls are hand-written and by design not in the pool.

    Only a **non-control** launched instance missing from the pool is a discrepancy worth
    naming (a registry mismatch); the controls' absence is the documented design of
    `eval/scripts/draw_mint_set.py`.
    """
    pool, selected = _fixture_pair(tmp_path)
    report = _run(pool, selected)
    discrepancies = report.split("DISCREPANC")[1]
    assert "control__x" not in discrepancies.split("\n\n")[0]


def test_a_launched_non_control_missing_from_the_pool_is_named(tmp_path: Path) -> None:
    pool, selected = _fixture_pair(tmp_path)
    records = json.loads(selected.read_text())["instances"]
    records.append(_record("sphinx-doc__sphinx-999", "sphinx-doc/sphinx"))
    _write(selected, records)

    report = _run(pool, selected)
    assert "sphinx-doc__sphinx-999" in report.split("DISCREPANC")[1]


# --------------------------------------------------------------------------------------
# Absent is not zero (criterion 7)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_missing_statement_reads_unknown_and_is_named(tmp_path: Path, blank) -> None:
    pool = _write(
        tmp_path / "pool.json",
        [
            _record("django__django-1", "django/django", problem_statement=HIT_STATEMENT),
            _record("django__django-2", "django/django", problem_statement=blank),
        ],
    )
    selected = _write(tmp_path / "selected.json", [])
    report = _run(pool, selected)

    assert "unknown" in report
    assert "1/2" in report  # the unknown, counted with its denominator
    assert "django__django-2" in report  # named, not just tallied
    # And it is NOT folded into the "does not mention" bucket: the informative denominator
    # excludes it, so the two rates differ (1/2 over all, 1/1 among those with text).
    assert "1/1" in report


def test_unknown_is_never_rendered_as_zero(tmp_path: Path) -> None:
    """The whole population unknown must not read as "0 mention tests"."""
    pool = _write(
        tmp_path / "pool.json",
        [_record("django__django-1", "django/django", problem_statement=None)],
    )
    selected = _write(tmp_path / "selected.json", [])
    report = _run(pool, selected)

    assert "unknown 1/1" in report or "unknown (missing or empty problem_statement): 1/1" in report
    assert "no instance carries text" in report.lower() or "0/0" in report


def test_loader_does_not_raise_on_a_blank_statement(tmp_path: Path) -> None:
    """Contrast with `registry.load_registry`, which is fail-closed and raises.

    That loader is right for the mint and wrong here: raising would replace a reportable
    state (`unknown`) with a crash, and criterion 7 would be unreachable.
    """
    pool = _write(
        tmp_path / "pool.json",
        [_record("django__django-1", "django/django", problem_statement="")],
    )
    loaded = fx.load_instances(pool)
    assert loaded[0].problem_statement == ""


# --------------------------------------------------------------------------------------
# Fail-loud on structure (identity is not a measurement)
# --------------------------------------------------------------------------------------


def test_a_file_without_an_instances_list_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "pool.json"
    path.write_text(json.dumps({"counts": {}}) + "\n")
    with pytest.raises(ValueError, match="instances"):
        fx.load_instances(path)


def test_a_record_without_an_instance_id_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "pool.json", [{"repo": "django/django"}])
    with pytest.raises(ValueError, match="instance_id"):
        fx.load_instances(path)


def test_a_record_without_a_repo_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "pool.json", [{"instance_id": "x"}])
    with pytest.raises(ValueError, match="repo"):
        fx.load_instances(path)


def test_main_exits_2_on_a_missing_input(tmp_path: Path) -> None:
    assert fx.main(["--pool", str(tmp_path / "absent.json")]) == 2


# --------------------------------------------------------------------------------------
# problem_statement vs task_string, separately (plan §1 output section 4)
# --------------------------------------------------------------------------------------


def test_the_two_fields_are_tallied_separately(tmp_path: Path) -> None:
    """A fixture where they disagree in BOTH directions, so neither can be a copy."""
    pool = _write(
        tmp_path / "pool.json",
        [
            # statement-only: the token sits past where `derive_task_string` truncates.
            _record(
                "django__django-1",
                "django/django",
                problem_statement=HIT_STATEMENT,
                task_string="Fix the following issue in this repository:\n\nIt is off by one.",
            ),
            # task-only: the framing would have to introduce the signal itself.
            _record(
                "django__django-2",
                "django/django",
                problem_statement=CLEAN_STATEMENT,
                task_string="Fix the following issue in this repository:\n\nthe tests fail",
            ),
        ],
    )
    selected = _write(tmp_path / "selected.json", [])
    report = _run(pool, selected)

    assert "problem_statement" in report
    assert "task_string" in report
    assert "statement only" in report
    assert "task_string only" in report


# --------------------------------------------------------------------------------------
# Surface floor (plan §1 output section 5) — a FLOOR, never a finding
# --------------------------------------------------------------------------------------


def test_surface_floor_is_derived_from_the_repo_name_and_labelled_a_floor(
    tmp_path: Path,
) -> None:
    pool, selected = _fixture_pair(tmp_path)
    report = _run(pool, selected)
    floor = report.split("SURFACE FLOOR")[1]

    assert "tests/" in floor  # django's in-scope segment
    assert "sympy/**/tests/" in floor
    assert "FLOOR" in report
    assert "never a finding" in report.lower()
    assert "2/2" in floor  # both fixture repos confirmed, with a denominator


def test_a_repo_with_no_recorded_layout_reads_unknown_not_absent(tmp_path: Path) -> None:
    pool = _write(
        tmp_path / "pool.json", [_record("acme__widget-1", "acme/widget")]
    )
    selected = _write(tmp_path / "selected.json", [])
    floor = _run(pool, selected).split("SURFACE FLOOR")[1]

    assert "acme/widget" in floor
    assert "unknown" in floor
    assert "0/1" in floor


def test_all_seven_population_repos_have_a_recorded_layout() -> None:
    """The floor's whole content: 7 repos, 7 known layouts, transcribed not cloned."""
    assert set(fx.IN_SCOPE_SURFACE) == {
        "django/django",
        "sympy/sympy",
        "sphinx-doc/sphinx",
        "psf/requests",
        "pytest-dev/pytest",
        "pallets/flask",
        "pylint-dev/pylint",
    }
    assert fx.IN_SCOPE_SURFACE["pytest-dev/pytest"] == "testing/"


# --------------------------------------------------------------------------------------
# Calibration (criterion 10) — transcription, checked against the published totals
# --------------------------------------------------------------------------------------


def test_measured_exposure_constant_reproduces_the_published_totals() -> None:
    """`PHASE0_RESULTS.md`: 17 comparisons over 7 distinct files, 6 judged, 9 zero, n=15.

    This is a **transcription guard**, not a re-derivation: the published figures are not
    recomputed here or anywhere in this aspect (criterion 11). If a typo crept into the
    constant, the calibration column would be quietly wrong and nothing else would notice.
    """
    judged = [row for row in fx.MEASURED_EXPOSURE if row.comparisons > 0]
    zero = [row for row in fx.MEASURED_EXPOSURE if row.comparisons == 0]

    assert len(fx.MEASURED_EXPOSURE) == 15
    assert len(judged) == 6
    assert len(zero) == 9
    assert sum(row.comparisons for row in fx.MEASURED_EXPOSURE) == 17
    assert sum(row.distinct_files for row in fx.MEASURED_EXPOSURE) == 7


def test_calibration_is_labelled_calibration_never_validation(tmp_path: Path) -> None:
    pool, selected = _fixture_pair(tmp_path)
    report = _run(pool, selected)

    assert "CALIBRATION" in report
    assert "NEVER VALIDATION" in report.upper()
    assert "n=15" in report


def test_a_repo_outside_the_measured_set_reads_not_measured(tmp_path: Path) -> None:
    """django was never in v0.12.0's measured set. `0` there would be a fabricated zero."""
    pool, selected = _fixture_pair(tmp_path)
    # Split on the section heading, not on the bare word: "CALIBRATION, NEVER VALIDATION"
    # appears in the same heading line, so splitting on "CALIBRATION" alone would hand back
    # the few characters between the two occurrences.
    calibration = _run(pool, selected).split("6. CALIBRATION")[1]

    django_line = next(
        line for line in calibration.splitlines() if line.startswith("  django/django")
    )
    assert "not measured" in django_line


# --------------------------------------------------------------------------------------
# The honesty paragraph (criterion 8)
# --------------------------------------------------------------------------------------


def test_honesty_paragraph_names_flask_4992_and_the_three_limits(tmp_path: Path) -> None:
    pool, selected = _fixture_pair(tmp_path)
    report = _run(pool, selected)
    lowered = report.lower()

    assert "flask-4992" in report
    assert "task description" in lowered
    assert "not agent behaviour" in lowered
    assert "under-counts by construction" in lowered
    assert "not comparable" in lowered
    assert "17 judgments" in lowered


def test_honesty_paragraph_survives_an_empty_launched_set(tmp_path: Path) -> None:
    """The caveats are not conditional on there being anything to report."""
    pool = _write(tmp_path / "pool.json", [_record("django__django-1", "django/django")])
    selected = _write(tmp_path / "selected.json", [])
    assert "flask-4992" in _run(pool, selected)


# --------------------------------------------------------------------------------------
# Offline by construction — AST guard, in the spirit of tests/test_verify_zero_llm.py
# --------------------------------------------------------------------------------------

MODULE = Path(fx.__file__)

#: Every top-level module the forecast is allowed to import. An allowlist rather than a
#: banlist: a banlist has to guess tomorrow's HTTP client, and this script's whole claim
#: is that it reads two committed files and computes. A new import here is a design
#: decision that should have to edit this test.
_ALLOWED_IMPORTS = frozenset(
    {"__future__", "argparse", "collections", "dataclasses", "json", "pathlib", "re", "sys", "typing"}
)

#: Named explicitly so a failure says *why*, not just "unexpected import".
_FORBIDDEN_IMPORTS = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "requests",
        "httpx",
        "subprocess",
        "random",
        "secrets",
        "time",
        "datetime",
        "uuid",
        "os",  # no environment, no API key, not even by accident
        "anthropic",
        "openai",
    }
)


def _imported_roots() -> set[str]:
    """The top-level module names the shipped source imports, read with `ast`.

    Never by importing: importing executes the module and reports on the venv rather than
    on the source that ships, which is the same reason `test_verify_zero_llm` walks the
    tree instead.
    """
    tree = ast.parse(MODULE.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_forecast_imports_nothing_that_could_reach_the_network_or_a_clock() -> None:
    roots = _imported_roots()
    assert roots, "the guard found no imports at all — it is scanning nothing"
    assert "json" in roots, "non-vacuity: the module does read committed JSON"
    assert not roots & _FORBIDDEN_IMPORTS
    assert roots <= _ALLOWED_IMPORTS


def test_the_forecast_calls_no_clock_and_no_randomness() -> None:
    """A belt to the import guard's braces: no `now()`/`random()`-shaped call anywhere."""
    source = MODULE.read_text()
    for forbidden in ("now(", "today(", "monotonic(", "random(", "shuffle(", "getenv("):
        assert forbidden not in source
