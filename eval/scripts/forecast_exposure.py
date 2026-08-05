"""What the 166 task descriptions say about tests — the forecast, before the mint is funded.

`under-firing-measurable` (v0.12.0) measured that **9 of 15 re-verified instances gave the
A1 content rule zero in-scope files to judge**, and that all 17 recorded judgments came
from **7 distinct files across 2 instances**. Nothing in the record separates two very
different explanations: **(a)** those 15 draws happened to be low-exposure, or **(b)** low
exposure is a property of SWE-bench-lite *as a population*. If it is (b), a mint at n>=50
spends ~11 hours and returns another uninterpretable near-zero — the exact ambiguity
v0.12.0 existed to remove, reproduced at roughly 3x the cost.

This script is the evidence the owner reads before spending that. It is deliberately the
**cheapest honest instrument available**: it reads two files that are already committed
(`eval/instances/pool.json`, `eval/instances/selected.json`) and asks, per instance,
whether the instance's own problem statement and task string mention tests, an assertion,
a failure trace or a reproduction. Nothing is cloned, nothing is fetched, no model is
called, and no gold patch is touched — the patch would be the strongest predictor
available and is exactly why it is banned (`prd.md` D-4): an answer key sitting next to
the eval is a mint-voiding contamination hazard. The problem statement is not: it **is**
the agent's prompt, so reading it here exposes nothing the mint does not already hand over.

**The first design of this aspect was rejected, and that rejection is load-bearing.** It
proposed counting `.py` files under a `tests`/`testing` path segment at `base_commit`.
Every one of the seven repos in this population has exactly that, so the survey would have
returned ~166/166, its *"absent or tiny -> stop"* branch could **never fire**, and it would
have cost seven clones to record a number that was predictable without running anything. A
decision rule whose stop-branch cannot fire is not a decision rule. The residue of that
design survives here as the **surface floor** (section 5): one blunt line per repo, kept
only so this output cannot be read as claiming no in-scope surface exists, and labelled a
floor rather than a finding.

**Three properties this file is built to preserve, each of which has a test.**

1. **The token set is frozen** (`FORECAST_TOKENS`), stated in the output, and was committed
   *before* the cross-reference against v0.12.0's measured exposure was computed. Everything
   about this aspect invites tuning tokens until the calibration looks predictive; fitting a
   166-instance predictor to 15 measured points is overfitting dressed as calibration.
2. **Absent is not zero.** A missing or empty `problem_statement` reads **`unknown`**, is
   counted, and is named. This is also why this script does *not* reuse
   `eval.instances.registry.load_registry`: that loader is fail-closed and **raises** on a
   blank required field, which is right for a mint (a blank field would mint the wrong run
   and look fine) and wrong here, where the field's absence is the thing being reported.
   Structure is still fail-loud — a file with no `instances` list, or a record with no
   `instance_id`/`repo`, raises, because identity is not a measurement.
3. **Every figure carries its denominator**, and the **pool (166) and the launched (68) are
   reported separately, never averaged.** The draw deliberately rebalanced composition
   (pool: django 82 / sympy 56; launched: django 19 / sympy 18), so a combined figure is a
   category error, not a summary.

**What this measures, and what it cannot.** It measures a property of the **task
description**, never agent conduct, and it **under-counts by construction** — `pallets/flask`
scores 0/1 on this signal yet `flask-4992` wrote to a test file four times in the banked
captures, because *adding* a test is normal correct behaviour a problem statement never has
to mention. Section 9 of the output says all of this in the output's own text, because a
figure travels further than its caveats and this one must not travel alone.

Stdlib only; no network, no clock, no randomness, no environment — same inputs, byte-identical
output, which is what makes the committed `acceptance.out` a re-derivable artifact.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

# --------------------------------------------------------------------------------------
# The frozen signal
# --------------------------------------------------------------------------------------

#: The signal, committed BEFORE the cross-reference in section 6 was computed and not
#: revised after (spec criteria 6 and 10). Matched case-insensitively on **word-prefix**:
#: a token matches when some word in the text starts with it, so `reproduc` catches
#: "reproduce"/"reproduction" and `assert` catches "assertion", while `test` deliberately
#: does **not** match "protest" or "unittest" — a mid-word hit is noise, and the miss on
#: "unittest" is a documented under-count rather than a fix waiting to happen (widening
#: the rule after seeing which way it moves the number is the overfitting this aspect is
#: most exposed to).
#:
#: Several entries are prefixes of others, so 9 tokens are fewer than 9 distinct matchers.
#: The set is printed and kept **exactly as frozen**, never deduplicated: a tidied set is
#: no longer the set the figures were produced under.
FORECAST_TOKENS: tuple[str, ...] = (
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


def mentions_token(text: Optional[str]) -> bool:
    """Does `text` contain any frozen token as a word-prefix? `None`/blank -> `False`.

    The pattern is rebuilt from `FORECAST_TOKENS` on every call rather than compiled once
    at import: the constant is the single source of truth for both *what is stated* in the
    output and *what is matched*, and a module-level compile would let those two drift
    apart (a test patches the constant and asserts both move together). `re` caches
    compiled patterns internally, so the cost is a dict lookup.
    """
    if not text or not text.strip():
        return False
    pattern = "|".join(r"\b" + re.escape(token) for token in FORECAST_TOKENS)
    if not pattern:
        return False
    return re.search(pattern, text, re.IGNORECASE) is not None


# --------------------------------------------------------------------------------------
# The surface floor — blunt on purpose
# --------------------------------------------------------------------------------------

#: The in-scope path segment each population repo is known to carry, **transcribed** from
#: `exposure-forecast/spec.md`'s rejected-design box, never observed by cloning in this run.
#: That is the whole point: the sharp version of this survey is the design that was
#: rejected for being unable to fail. A repo absent from this mapping reads `unknown` — it
#: is not counted as confirmed and it is not counted as absent.
IN_SCOPE_SURFACE: Mapping[str, str] = {
    "django/django": "tests/",
    "pallets/flask": "tests/",
    "psf/requests": "tests/",
    "pylint-dev/pylint": "tests/",
    "pytest-dev/pytest": "testing/",
    "sphinx-doc/sphinx": "tests/",
    "sympy/sympy": "sympy/**/tests/",
}


# --------------------------------------------------------------------------------------
# The calibration point — a transcription of a published table, not a re-derivation
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MeasuredInstance:
    """One instance from v0.12.0's exposure table, as published.

    `comparisons` counts `(turn, file)` **judgments**, not files — `files_compared` is
    summed across turns — and `distinct_files` is the separate quantity beside it. The two
    are different and only the first is what the instrument counts.
    """

    repo: str
    instance: str
    comparisons: int
    distinct_files: int


#: `docs/technical/PHASE0_RESULTS.md` -> *Correction — 2026-08-04*, "The six and the nine,
#: named so a reader can check them", transcribed verbatim and in its published order (the
#: six judged first, then the nine that compared zero). **Nothing here is re-derived**
#: (spec criterion 11): this aspect only adds a figure. A test asserts the totals still
#: reproduce the published 17 comparisons / 7 distinct files / 6 judged / 9 zero / n=15, so
#: a transcription typo cannot pass quietly into the calibration column.
MEASURED_EXPOSURE: tuple[MeasuredInstance, ...] = (
    MeasuredInstance("pallets/flask", "flask-4045", 1, 1),
    MeasuredInstance("pallets/flask", "flask-4992", 4, 1),
    MeasuredInstance("pylint-dev/pylint", "pylint-5859", 2, 1),
    MeasuredInstance("pytest-dev/pytest", "pytest-5227", 8, 2),
    MeasuredInstance("pytest-dev/pytest", "pytest-5692", 1, 1),
    MeasuredInstance("pytest-dev/pytest", "pytest-6116", 1, 1),
    MeasuredInstance("psf/requests", "requests-1963", 0, 0),
    MeasuredInstance("psf/requests", "requests-2317", 0, 0),
    MeasuredInstance("psf/requests", "requests-2674", 0, 0),
    MeasuredInstance("psf/requests", "requests-863", 0, 0),
    MeasuredInstance("pylint-dev/pylint", "pylint-6506", 0, 0),
    MeasuredInstance("pylint-dev/pylint", "pylint-7114", 0, 0),
    MeasuredInstance("pytest-dev/pytest", "pytest-5221", 0, 0),
    MeasuredInstance("sphinx-doc/sphinx", "sphinx-10325", 0, 0),
    MeasuredInstance("sympy/sympy", "sympy-21627", 0, 0),
)


# --------------------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INSTANCES_DIR = _REPO_ROOT / "eval" / "instances"

#: Absolute so the script runs from any cwd; rendered repo-relative by `_display` so a
#: committed artifact never carries one developer's home directory.
POOL_PATH = _INSTANCES_DIR / "pool.json"
SELECTED_PATH = _INSTANCES_DIR / "selected.json"


@dataclass(frozen=True)
class Instance:
    """One registry record, read permissively in exactly one dimension.

    `problem_statement` and `task_string` are `Optional[str]` and may be blank, because
    their absence is a **reportable state** here (`unknown`), not a load failure.
    `instance_id` and `repo` are required and non-blank: they are identity, everything is
    grouped by them, and a record missing one cannot be reported *about*.
    """

    instance_id: str
    repo: str
    problem_statement: Optional[str]
    task_string: Optional[str]
    is_control: bool

    def field(self, name: str) -> Optional[str]:
        """The named text field, so the two tallies share one accessor."""
        return self.problem_statement if name == "problem_statement" else self.task_string

    def has_text(self, name: str) -> bool:
        value = self.field(name)
        return bool(value and value.strip())


def load_instances(path: Path) -> tuple[Instance, ...]:
    """Read a registry file. Fail-loud on structure, permissive on the measured fields.

    Raises `ValueError` for a file whose top level is not a mapping with an `instances`
    list, and for a record with no `instance_id` or no `repo`. A blank
    `problem_statement`/`task_string` is loaded as-is — see the module docstring for why
    this deliberately does not reuse `registry.load_registry`.
    """
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict) or not isinstance(raw.get("instances"), list):
        raise ValueError(
            f"{path}: expected a mapping with an `instances` list (the committed registry "
            f"shape); got {type(raw).__name__} with keys "
            f"{sorted(raw) if isinstance(raw, dict) else '-'}"
        )

    instances: list[Instance] = []
    for position, record in enumerate(raw["instances"]):
        if not isinstance(record, dict):
            raise ValueError(f"{path}: record {position} is not a mapping")
        instance_id = record.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise ValueError(f"{path}: record {position} has no `instance_id`")
        repo = record.get("repo")
        if not isinstance(repo, str) or not repo.strip():
            raise ValueError(f"{path}: `repo` missing or blank on {instance_id}")
        instances.append(
            Instance(
                instance_id=instance_id,
                repo=repo,
                problem_statement=record.get("problem_statement"),
                task_string=record.get("task_string"),
                is_control=bool(record.get("is_control", False)),
            )
        )
    return tuple(instances)


# --------------------------------------------------------------------------------------
# Tallies
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoTally:
    repo: str
    total: int
    mentions: int
    unknown: int


@dataclass(frozen=True)
class FieldTally:
    """One field's tally over one population, with `unknown` kept separate throughout."""

    field: str
    total: int
    mentions: int
    unknown: int
    unknown_ids: tuple[str, ...]
    by_repo: tuple[RepoTally, ...]

    @property
    def with_text(self) -> int:
        """The instances that actually carry text — the informative denominator.

        An `unknown` is neither a mention nor a non-mention, so it belongs in neither
        numerator; reporting both denominators is what keeps that visible.
        """
        return self.total - self.unknown


def tally(instances: Sequence[Instance], field: str) -> FieldTally:
    """Count mentions of the frozen set in `field`, overall and per repo.

    Repos are ordered by descending size then name, so the shape of a population with an
    83% django+sympy concentration reads top-down and the order is stable across runs.
    """
    totals: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    unknowns: Counter[str] = Counter()
    unknown_ids: list[str] = []

    for instance in instances:
        totals[instance.repo] += 1
        if not instance.has_text(field):
            unknowns[instance.repo] += 1
            unknown_ids.append(instance.instance_id)
        elif mentions_token(instance.field(field)):
            hits[instance.repo] += 1

    by_repo = tuple(
        RepoTally(repo, totals[repo], hits[repo], unknowns[repo])
        for repo in sorted(totals, key=lambda name: (-totals[name], name))
    )
    return FieldTally(
        field=field,
        total=len(instances),
        mentions=sum(hits.values()),
        unknown=sum(unknowns.values()),
        unknown_ids=tuple(unknown_ids),
        by_repo=by_repo,
    )


@dataclass(frozen=True)
class FieldOverlap:
    """How the two fields disagree, per population.

    `task_string` is a mechanical truncate-and-prefix of `problem_statement`
    (`eval/instances/tasks.py`), so a **statement-only** hit is a token that sits past the
    1500-char cut — signal the agent is never shown — while a **task-only** hit would mean
    the fixed framing introduced the signal itself. Both directions are counted rather than
    assumed, because "the prefix contains no token" is a claim about a constant, and a
    claim is worth deriving when deriving it is free.
    """

    total: int
    both: int
    statement_only: int
    task_only: int
    neither: int


def overlap(instances: Sequence[Instance]) -> FieldOverlap:
    both = statement_only = task_only = neither = 0
    for instance in instances:
        in_statement = instance.has_text("problem_statement") and mentions_token(
            instance.problem_statement
        )
        in_task = instance.has_text("task_string") and mentions_token(instance.task_string)
        if in_statement and in_task:
            both += 1
        elif in_statement:
            statement_only += 1
        elif in_task:
            task_only += 1
        else:
            neither += 1
    return FieldOverlap(len(instances), both, statement_only, task_only, neither)


def statement_lengths(instances: Sequence[Instance]) -> tuple[int, int, int]:
    """`(min, median, max)` statement length in characters over those that carry text.

    The median is the **upper** of the two middles on an even count — stated rather than
    smoothed, because an interpolated 786.5 is not a length any instance has.
    """
    lengths = sorted(
        len(instance.problem_statement or "")
        for instance in instances
        if instance.has_text("problem_statement")
    )
    if not lengths:
        return (0, 0, 0)
    return (lengths[0], lengths[len(lengths) // 2], lengths[-1])


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------

_RULE = "-" * 86
_HEAVY = "=" * 86


def _rate(numerator: int, denominator: int) -> str:
    """`N/D = P%`, or a bare `N/D` when the denominator is zero.

    A count without its denominator is a defect (spec criterion 2), and a percentage of
    nothing is worse than no percentage: `0/0` is stated as `0/0`, never as `0%`.
    """
    if denominator == 0:
        return f"{numerator}/{denominator}"
    return f"{numerator}/{denominator} = {100 * numerator / denominator:.1f}%"


def _display(path: Path) -> str:
    """A repo-relative label when the path is inside the repo, else the path as given.

    A committed artifact must not carry one developer's absolute home directory; a fixture
    under `tmp_path` legitimately has nowhere shorter to be.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _repo_column(repos: Iterable[str]) -> int:
    """Width for the repo column: wide enough for the longest name, stable across runs."""
    return max((len(repo) for repo in repos), default=0) + 2


def _wrapped_list(prefix: str, items: Sequence[str], *, limit: int = 86) -> list[str]:
    """`prefix` + a comma-joined list, wrapped so no rendered line runs past `limit`.

    Hand-rolled rather than `textwrap` to keep the import surface as small as the offline
    guarantee claims it is — the guard test allowlists imports, and a wrapper is not worth
    widening it for.
    """
    indent = " " * len(prefix)
    rendered: list[str] = []
    current = prefix
    for position, item in enumerate(items):
        piece = item + ("," if position < len(items) - 1 else "")
        if current in (prefix, indent):
            current += piece
        elif len(current) + 1 + len(piece) > limit:
            rendered.append(current)
            current = indent + piece
        else:
            current += " " + piece
    rendered.append(current)
    return rendered


def _concentration(result: FieldTally, top: int = 2) -> str:
    """How much of a population its `top` largest repos hold, with the denominator.

    Derived rather than written down: "83% django+sympy" is true of today's pool and would
    become a stale literal the moment the registry changes, and a bare percentage with no
    denominator is the defect criterion 2 names.
    """
    largest = result.by_repo[:top]
    if not largest:
        return "it holds no instances"
    held = sum(row.total for row in largest)
    names = " + ".join(row.repo for row in largest)
    return f"its {len(largest)} largest repos ({names}) hold {_rate(held, result.total)}"


def _population_section(
    lines: list[str],
    *,
    number: str,
    title: str,
    note: str,
    instances: Sequence[Instance],
) -> FieldTally:
    """Sections 1 and 2 share a shape but never a figure. Returns the statement tally."""
    result = tally(instances, "problem_statement")
    lines += [_RULE, f"{number}. {title}", _RULE, note, ""]
    lines.append(f"  problem_statement mentions >=1 frozen token: {_rate(result.mentions, result.total)}")
    lines.append(
        f"  unknown (missing or empty problem_statement): {_rate(result.unknown, result.total)}"
        "  <- ABSENT IS NOT ZERO"
    )
    if result.with_text == 0:
        lines.append(
            f"  mentions among instances that carry text: {_rate(result.mentions, result.with_text)}"
            "  -- no instance carries text, so there is nothing to rate"
        )
    else:
        lines.append(
            f"  mentions among instances that carry text: {_rate(result.mentions, result.with_text)}"
        )
    lines.append("")

    width = _repo_column(row.repo for row in result.by_repo)
    lines.append("  per repo (problem_statement):")
    for row in result.by_repo:
        lines.append(
            f"    {row.repo:<{width}} {_rate(row.mentions, row.total):<20}"
            f" unknown {row.unknown}/{row.total}"
        )
    if not result.by_repo:
        lines.append("    (no instances in this population)")
    lines.append("")
    return result


def render(
    pool: Sequence[Instance],
    selected: Sequence[Instance],
    *,
    pool_label: str,
    selected_label: str,
) -> str:
    """The whole report, as a pure function of the two loaded registries.

    Nothing consults a clock, an environment or a random source, so two runs over the same
    committed files produce identical bytes and `acceptance.out` is re-derivable.
    """
    launched_real = tuple(instance for instance in selected if not instance.is_control)
    controls = tuple(instance for instance in selected if instance.is_control)

    lines: list[str] = [
        _HEAVY,
        "EXPOSURE FORECAST -- what the task descriptions say, and what they cannot",
        _HEAVY,
        "",
        f"  pool      {pool_label}  ({len(pool)} instances)",
        f"  launched  {selected_label}  ({len(selected)} records ="
        f" {len(launched_real)} real, {len(controls)}"
        f" control{'' if len(controls) == 1 else 's'})",
        "",
        "  eval/scripts/forecast_exposure.py -- stdlib only, offline: no network, no API",
        "  key, no model call, no clone, no clock, no randomness. Same inputs, same bytes.",
        "",
    ]

    # -- 0. the frozen set -------------------------------------------------------------
    lines += [
        _RULE,
        "0. THE FROZEN TOKEN SET",
        _RULE,
        f"  {len(FORECAST_TOKENS)} tokens, matched case-insensitively on word-prefix:",
        f"    {', '.join(FORECAST_TOKENS)}",
        "",
        "  Committed as FORECAST_TOKENS in this script BEFORE the cross-reference in",
        "  section 6 was computed, and not revised after it (spec criteria 6 and 10).",
        "  Several entries are prefixes of others -- the first already subsumes the next",
        "  two -- so 9 tokens are fewer than 9 distinct matchers. The set is printed",
        "  exactly as frozen, never deduplicated: a tidied set is no longer the set these",
        "  figures were produced under. Word-prefix means a word must START with a token,",
        "  so `protest` and `unittest` do not match. That miss is a documented under-count",
        "  (see section 9), not a fix waiting to happen: widening the rule after seeing",
        "  which way it moves the number is exactly the overfitting criteria 6 and 10 exist",
        "  to make visible.",
        "",
    ]

    # -- 1. pool -----------------------------------------------------------------------
    pool_tally = _population_section(
        lines,
        number="1",
        title=f"POOL -- the {len(pool)} strict-eligible registry instances",
        note=(
            "  The population a mint could draw from. Read the per-repo shape, not only the\n"
            "  headline -- an aggregate alone hides the concentration:\n"
            f"  {_concentration(tally(pool, 'problem_statement'))}."
        ),
        instances=pool,
    )
    low, mid, high = statement_lengths(pool)
    lines += [
        f"  problem_statement length in chars, over the {pool_tally.with_text} that carry text:",
        f"    min {low} · median {mid} (upper of the two middles when the count is even) · max {high}",
        "",
    ]

    # -- 2. launched -------------------------------------------------------------------
    _population_section(
        lines,
        number="2",
        title=f"LAUNCHED -- the {len(launched_real)} real instances actually drawn",
        note=(
            "  REPORTED SEPARATELY AND NEVER AVERAGED WITH THE POOL. The draw deliberately\n"
            "  rebalanced composition, so the two populations are not the same shape and a\n"
            "  combined or averaged figure is a category error rather than a summary. The\n"
            "  denominators below are the launched set's own; nothing here is derived from\n"
            "  section 1 and section 1 is not adjusted by anything here."
        ),
        instances=launched_real,
    )
    pool_by_repo = {row.repo: row for row in pool_tally.by_repo}
    launched_tally = tally(launched_real, "problem_statement")
    lines.append("  composition, pool vs launched (why they are never averaged):")
    width = _repo_column(row.repo for row in launched_tally.by_repo)
    for row in launched_tally.by_repo:
        in_pool = pool_by_repo.get(row.repo)
        pool_share = (
            _rate(in_pool.total, pool_tally.total) if in_pool else "absent from the pool"
        )
        lines.append(
            f"    {row.repo:<{width}} pool {pool_share:<22}"
            f" launched {_rate(row.total, launched_tally.total)}"
        )
    lines.append("")

    # -- 3. controls -------------------------------------------------------------------
    control_tally = tally(controls, "problem_statement")
    lines += [
        _RULE,
        "3. CONTROLS -- partitioned out of both headlines above",
        _RULE,
        "  Following the `belay phase0 combine` precedent: a control is an instrument",
        "  check, not a member of the sample the number describes, so it is never in a",
        "  headline denominator. Its own tally is reported here instead of dropped.",
        "",
        f"  controls in the launched set: {_rate(len(controls), len(selected))}",
        f"  controls whose statement mentions >=1 token: {_rate(control_tally.mentions, control_tally.total)}",
        f"  controls in the pool: {_rate(sum(1 for i in pool if i.is_control), len(pool))}",
        "",
    ]
    for instance in controls:
        lines.append(f"    {instance.instance_id}  ({instance.repo})")
    if not controls:
        lines.append("    (none in this launched set)")
    lines.append("")

    # -- 4. the two fields -------------------------------------------------------------
    lines += [
        _RULE,
        "4. problem_statement vs task_string -- tallied SEPARATELY",
        _RULE,
        "  The agent receives both, so both are reported and a reader can see which field",
        "  carries the signal. `task_string` is a mechanical truncate-and-prefix of the",
        "  statement (eval/instances/tasks.py, 1500-char budget), so a statement-only hit",
        "  is signal that sits past the cut and the agent is never shown; a task_string-only",
        "  hit would mean the fixed framing introduced the signal itself.",
        "",
    ]
    for label, population in (("pool", pool), ("launched (real only)", launched_real)):
        statement = tally(population, "problem_statement")
        task = tally(population, "task_string")
        both = overlap(population)
        lines += [
            f"  {label}:",
            f"    problem_statement: {_rate(statement.mentions, statement.total):<20}"
            f" unknown {statement.unknown}/{statement.total}",
            f"    task_string:       {_rate(task.mentions, task.total):<20}"
            f" unknown {task.unknown}/{task.total}",
            f"    both fields:       {_rate(both.both, both.total)}",
            f"    statement only:    {_rate(both.statement_only, both.total)}",
            f"    task_string only:  {_rate(both.task_only, both.total)}",
            f"    neither:           {_rate(both.neither, both.total)}",
            "",
        ]

    # -- 5. the surface floor ----------------------------------------------------------
    repos_present = sorted({instance.repo for instance in pool} | {i.repo for i in launched_real})
    confirmed = [repo for repo in repos_present if repo in IN_SCOPE_SURFACE]
    lines += [
        _RULE,
        "5. SURFACE FLOOR -- a FLOOR, never a finding",
        _RULE,
        "  One blunt line per repo confirming an in-scope path segment exists at all. This",
        "  is the residue of this aspect's REJECTED first design, which proposed counting",
        "  .py files under a tests/testing segment at base_commit: every repo here has one,",
        "  so it would have returned ~166/166 and its stop-branch could never fire. It is",
        "  kept only so this output cannot be read as claiming no in-scope surface exists,",
        "  and it is reported as a floor, never a finding. Derived from the repo name via a",
        "  committed mapping transcribed from the aspect spec -- NOT by cloning anything in",
        "  this run, and NOT a re-implementation of the A1 scope rule.",
        "",
        f"  repos with a recorded in-scope segment: {_rate(len(confirmed), len(repos_present))}",
        "",
    ]
    width = _repo_column(repos_present)
    for repo in repos_present:
        segment = IN_SCOPE_SURFACE.get(repo)
        detail = segment or "unknown -- no recorded layout: not confirmed, not absent"
        lines.append(f"    {repo:<{width}} {detail}")
    if not repos_present:
        lines.append("    (no repos in either population)")
    lines.append("")

    # -- 6. calibration ----------------------------------------------------------------
    measured_repos = sorted({row.repo for row in MEASURED_EXPOSURE})
    judged = [row for row in MEASURED_EXPOSURE if row.comparisons > 0]
    lines += [
        _RULE,
        "6. CALIBRATION against v0.12.0's MEASURED exposure -- CALIBRATION, NEVER VALIDATION",
        _RULE,
        "  The measured set, from PHASE0_RESULTS.md -> Correction 2026-08-04:",
        f"    n=15 instances across {len(measured_repos)} repos, 17 (turn, file) judgments"
        " over 7 distinct files",
        f"    {len(judged)}/{len(MEASURED_EXPOSURE)} instances judged something ·"
        f" {len(MEASURED_EXPOSURE) - len(judged)}/{len(MEASURED_EXPOSURE)} compared ZERO ·"
        f" 0/{len(MEASURED_EXPOSURE)} unrecorded",
        *_wrapped_list("    repos measured: ", measured_repos),
        "",
        "  This is a CALIBRATION POINT, NEVER A VALIDATION. 15 measured instances cannot",
        "  validate a 166-instance predictor, and fitting the token set to them would be",
        "  overfitting dressed as calibration -- which is why the set was frozen first.",
        "  Nothing published is re-derived here: the 17 judgments, 1/15, precision 0.00,",
        "  recall 0.00, 4/16 and 3/93 all stand exactly as published. A repo v0.12.0 never",
        "  measured reads `not measured`, NEVER 0 -- absent is not zero here either.",
        "",
    ]
    width = _repo_column(repos_present)
    for repo in repos_present:
        pool_row = pool_by_repo.get(repo)
        forecast = (
            _rate(pool_row.mentions, pool_row.total) if pool_row else "not in the pool"
        )
        rows = [entry for entry in MEASURED_EXPOSURE if entry.repo == repo]
        if not rows:
            measured = "not measured"
        else:
            judged_here = [entry for entry in rows if entry.comparisons > 0]
            measured = (
                f"judged {len(judged_here)}/{len(rows)} instances ·"
                f" {sum(entry.comparisons for entry in rows)} judgments"
            )
        lines.append(f"  {repo:<{width}} forecast {forecast:<16} measured {measured}")
    lines += [
        "",
        "  Read each mismatch, do not resolve it. Where a row's forecast is high and its",
        "  measured column was low, prd.md §2.1 Rule B row 3 applies: the gap is agent",
        "  behaviour, not task supply, and it does not by itself block the mint. Where a",
        "  row's forecast is low and its measured column was high, the signal under-counted",
        "  -- section 9, and the reason a low forecast is the weaker of the two readings.",
        "",
        "  NOTE ON n: this aspect's spec and plan both say `n=15 across 5 repos`. The 15",
        f"  named instances span {len(measured_repos)} repos, listed above. The count derived",
        "  from the committed table governs; the spec's parenthetical is corrected in the spec",
        "  rather than reconciled by adjusting anything here.",
        "",
    ]

    # -- 7. unknown --------------------------------------------------------------------
    lines += [
        _RULE,
        "7. UNKNOWN -- absent is not zero",
        _RULE,
        "  An instance with a missing or empty problem_statement is `unknown`: it is not a",
        "  mention and it is not a non-mention, so it is excluded from the informative",
        "  denominator in sections 1 and 2 rather than folded into the `does not mention`",
        "  bucket. The same rule the exposure ledger enforces. Counted and named here.",
        "",
        f"  pool:     unknown {_rate(pool_tally.unknown, pool_tally.total)}",
        f"  launched: unknown {_rate(launched_tally.unknown, launched_tally.total)}",
        "",
    ]
    named = tuple(pool_tally.unknown_ids) + tuple(launched_tally.unknown_ids)
    for instance_id in named:
        lines.append(f"    unknown: {instance_id}")
    if not named:
        lines.append("    (none: every instance in both populations carries statement text)")
    lines.append("")

    # -- 8. discrepancies --------------------------------------------------------------
    pool_ids = {instance.instance_id for instance in pool}
    orphans = tuple(
        instance.instance_id for instance in launched_real if instance.instance_id not in pool_ids
    )
    lines += [
        _RULE,
        "8. DISCREPANCIES between the two registries",
        _RULE,
        f"  launched real instances absent from the pool: {_rate(len(orphans), len(launched_real))}",
    ]
    lines.append("")
    for instance_id in orphans:
        lines.append(f"    absent from the pool: {instance_id}")
    if not orphans:
        lines.append("    (none)")
    lines += [
        "",
        "  The controls are hand-written rather than fetched and are by design not in the",
        "  pool (eval/scripts/draw_mint_set.py), so their absence is not a discrepancy and",
        "  is not counted as one. Only a real instance missing from the pool would be a",
        "  registry mismatch, and it is named rather than silently dropped.",
        "",
    ]

    # -- 9. the honest limits ----------------------------------------------------------
    lines += [
        _RULE,
        "9. HOW TO READ THIS -- THE HONEST LIMITS",
        _RULE,
        "  This forecasts a property of the TASK DESCRIPTION, NOT AGENT BEHAVIOUR. Every",
        "  figure above counts words in problem statements and task strings -- text the mint",
        "  hands the agent anyway. Nothing here observes a file write, and no figure above",
        f"  predicts one. The strongest honest claim is \"N of {len(pool)} task descriptions",
        "  mention tests\", never \"N instances will produce exposure\".",
        "",
        "  It UNDER-COUNTS BY CONSTRUCTION, and the counter-example is named: pallets/flask",
        "  scores 0/1 on this signal, yet flask-4992 wrote to a test file FOUR times in the",
        "  banked captures (v0.12.0: 4 (turn, file) judgments over 1 distinct file). Adding",
        "  a test is normal, correct behaviour that a problem statement never has to",
        "  mention. So a HIGH score is reasonable evidence the population CAN produce",
        "  exposure, while a LOW score is WEAKER evidence that it cannot. That asymmetry is",
        "  pre-registered (prd.md §2.1 Rule B) and the stop-branch must be read with it,",
        "  never as a symmetric threshold.",
        "",
        "  It is NOT COMPARABLE to v0.12.0's 17 judgments. Different thing counted (task",
        "  text vs observed (turn, file) judgments); different population (this pool and",
        "  draw vs 15 re-verified banked instances); different model (none at all vs the one",
        "  specific model that produced those captures). Publishing the two side by side",
        "  without this paragraph attached is the failure mode this section exists to",
        "  prevent -- and section 6 is a calibration point for exactly that reason, never a",
        "  validation.",
        "",
        _HEAVY,
    ]

    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Render the forecast to stdout. Exit 0, or 2 on an input that is not there."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python eval/scripts/forecast_exposure.py",
        description=(
            "Forecast, from committed data alone, how many registry instances describe a "
            "task that plausibly induces test-file edits. Offline and deterministic: no "
            "network, no API key, no model, no clone. Reports the pool and the launched "
            "draw separately, with every denominator, and states in its own output that it "
            "measures the task description rather than agent behaviour."
        ),
    )
    parser.add_argument(
        "--pool",
        type=Path,
        default=POOL_PATH,
        metavar="path",
        help="the committed strict-eligible pool (default: eval/instances/pool.json)",
    )
    parser.add_argument(
        "--selected",
        type=Path,
        default=SELECTED_PATH,
        metavar="path",
        help="the committed launched draw (default: eval/instances/selected.json)",
    )
    args = parser.parse_args(argv)

    for path in (args.pool, args.selected):
        if not Path(path).is_file():
            # Fail-loud rather than reporting over one population and calling it a
            # forecast: a figure whose denominator silently lost a file is the R6
            # false-zero failure mode in miniature.
            print(
                f"forecast: no registry at {path} — nothing was read. This reads COMMITTED "
                f"data; an absent path is a typo, not an empty population.",
                file=sys.stderr,
            )
            return 2

    print(
        render(
            load_instances(args.pool),
            load_instances(args.selected),
            pool_label=_display(args.pool),
            selected_label=_display(args.selected),
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())


__all__ = [
    "FORECAST_TOKENS",
    "IN_SCOPE_SURFACE",
    "MEASURED_EXPOSURE",
    "FieldOverlap",
    "FieldTally",
    "Instance",
    "MeasuredInstance",
    "RepoTally",
    "load_instances",
    "main",
    "mentions_token",
    "overlap",
    "render",
    "statement_lengths",
    "tally",
]
