"""SWE-bench-lite rows -> the strict-eligible Phase-0 instance pool.

The module has two halves, and keeping them apart is a correctness property rather than
a tidiness one:

* **`rows_to_pool` and `changed_line_count` are pure.** No clock, no randomness, and — by
  construction — no network: `urllib` is imported *inside* `main`, so importing this
  module cannot put an HTTP client in scope. `tests/test_eval_pool_fetch.py` asserts that
  with an `ast` walk, which is the only thing that can assert it (an import that works in
  this venv leaves no other trace). That is what keeps the test suite offline.
* **`main` touches the network exactly once and is run by a human.** Its output,
  `eval/instances/pool.json`, is committed; tests read the committed artifact, never the
  dataset server. So a dataset outage cannot break CI, and a refetch is a reviewable diff.

**Why `repo` is validated as an `owner/name` slug and a URL *raises*.**
`eval/minting_driver/workspace.py` builds the clone URL as `https://github.com/{repo}.git`
and caches the bare clone under `repo.replace("/", "__")`. A `repo` that is already a URL
double-prefixes, and the clone fails at prep time — after a live batch has started
spending. This bit Stage 1. The transform therefore refuses rather than normalizes: a URL
in the source means our assumption about the dataset's shape is wrong, and silently
fixing it up hides exactly the thing a human needs to see.

**The three filters, in order** (thresholds are the module constants below, published
verbatim into `pool.json`'s provenance header so the pool is legible without this code):

1. `repo in PURE_PYTHON_REPOS` — an **allow-list** imported from `selection.py`, never
   restated here (a second copy drifts). A repo that is in neither the allow-list nor
   `KNOWN_EXCLUDED_REPOS` is excluded *and reported on stderr*, so a dataset change is
   visible rather than silent.
2. **changed lines <= `MAX_CHANGED_LINES`**, counted by D5's rule: lines of `patch`
   beginning with `+` or `-`, **excluding** the `+++`/`---` file headers; `@@` hunk headers
   and context lines are ignored. Written down because this rule decides the pool.
3. `len(problem_statement) <= MAX_STATEMENT_CHARS`, and non-blank — a blank statement is
   reported and skipped rather than minted as an empty task that proves nothing.

The measured survey tiers were 300 -> 239 -> 204 -> 166. If this rule yields different
tier counts, **record the actual counts and note the discrepancy — do not tune the rule**
until 166 falls out of the real data. Any pool comfortably above the launch size is
sufficient; 166 is a sanity check, not a target.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from eval.instances.registry import InstanceRecord, dump_registry
from eval.instances.selection import PURE_PYTHON_REPOS
from eval.instances.tasks import derive_task_string

#: Maximum changed lines in an instance's `patch` for it to be strict-eligible. Inclusive.
MAX_CHANGED_LINES = 15

#: Maximum length of the raw `problem_statement`, in characters. Inclusive.
MAX_STATEMENT_CHARS = 2000

#: Repos known to be in SWE-bench-lite and deliberately NOT in the allow-list: they need a
#: C/Cython/OpenMP toolchain and Debian-only system packages the mint substrate does not
#: provide. Listed so their exclusion is *expected* and therefore silent — anything outside
#: both lists is dataset drift and gets reported.
KNOWN_EXCLUDED_REPOS = frozenset(
    {
        "matplotlib/matplotlib",
        "scikit-learn/scikit-learn",
        "astropy/astropy",
        "pydata/xarray",
        "mwaskom/seaborn",
    }
)

#: `owner/name`, and nothing else. Anchored on both ends, so a URL, a bare name, or a
#: three-segment path all fail.
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")

#: The row fields this transform consumes. Everything else the dataset carries
#: (`hints_text`, `test_patch`, `version`, ...) is ignored.
_ROW_FIELDS = ("instance_id", "repo", "base_commit", "problem_statement", "patch")

#: The dataset the pool is drawn from. Committed into the header by `main`.
DATASET = "princeton-nlp/SWE-bench_Lite"
CONFIG = "default"
SPLIT = "test"
ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"

#: Keys a `/rows` payload might carry a dataset revision under. Probed rather than
#: assumed: as observed on 2026-07-23 the envelope is
#: `{features, rows, num_rows_total, num_rows_per_page, partial}` and carries **none** of
#: these, so `revision` lands as `null`. Probing anyway means the pin starts working for
#: free if the endpoint ever grows one, without this script claiming today that it has.
_REVISION_KEYS = ("revision", "dataset_revision", "sha")

#: Why `revision` may be null, written into the header so the artifact is honest without
#: this file. D2 asked for a pin "with an honest fallback"; this is the fallback, stated.
REVISION_NOTE = (
    "The datasets-server /rows envelope reported no dataset revision when this pool was "
    "fetched (observed keys: features, rows, num_rows_total, num_rows_per_page, "
    "partial), so no commit sha could be pinned and 'revision' is null. This file is "
    "committed and is itself the source of truth; re-derivability here is drift "
    "*detection*, not a time machine. Drift shows up as a changed 'num_rows_total' or "
    "changed tier 'counts' on a refetch, both of which produce a reviewable diff. If the "
    "endpoint later reports a revision it is recorded here, and "
    "--expect-revision refuses a fetch whose live revision differs from the pinned one."
)


def changed_line_count(patch: str) -> int:
    """Changed lines in a unified diff, by D5's rule.

    Counts lines beginning with `+` or `-`, **excluding** the `+++`/`---` file headers.
    `@@` hunk headers, `diff --git`/`index` lines, `\\ No newline at end of file`, and
    context lines are not changes and are not counted.

    Deliberately a simple, stated rule rather than a diff parser: it must be reproducible
    by hand from the committed `pool.json` and the published header, by someone who does
    not run this code.
    """
    count = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            count += 1
    return count


def _row_of(entry: object, index: int) -> Mapping[str, object]:
    """The inner row of one datasets-server envelope, or a named `ValueError`.

    The `/rows` endpoint returns `{"rows": [{"row_idx": int, "row": {...}}, ...]}`; this
    transform consumes that envelope list directly so `main` stays a thin fetch.
    """
    if not isinstance(entry, dict):
        raise ValueError(
            f"row {index} must be a JSON object, got {type(entry).__name__}"
        )
    row = entry.get("row")
    if not isinstance(row, dict):
        raise ValueError(
            f"row {index} is missing its 'row' object (the datasets-server envelope is "
            f"{{'row_idx': int, 'row': {{...}}}}); got {type(row).__name__}"
        )
    return row


def _require_str(row: Mapping[str, object], field: str, *, index: int) -> str:
    """One consumed field as a non-blank string, or a named `ValueError`.

    Fail-closed for the same reason `load_registry` is: a field that defaulted to `""`
    here would not fail loudly, it would mint the wrong run and look fine.
    """
    ident = row.get("instance_id")
    ident = ident if isinstance(ident, str) and ident.strip() else f"row {index}"
    if field not in row:
        raise ValueError(f"instance {ident!r} is missing required field {field!r}")
    value = row[field]
    if not isinstance(value, str):
        raise ValueError(
            f"instance {ident!r} field {field!r} must be a string, "
            f"got {type(value).__name__}"
        )
    if not value.strip():
        raise ValueError(
            f"instance {ident!r} field {field!r} is blank; fetched fields are never "
            f"defaulted"
        )
    return value


def _require_slug(repo: str, *, ident: str) -> str:
    """`repo` as an `owner/name` slug, or a `ValueError` naming the offending value.

    Raises rather than normalizes — see the module docstring: this is the Stage-1 bug.
    """
    if "://" in repo or "github.com" in repo or repo.endswith(".git"):
        raise ValueError(
            f"instance {ident!r} field 'repo' is {repo!r}, which looks like a clone URL; "
            f"it must be the 'owner/name' slug. Refusing to normalize: a URL here means "
            f"the dataset's shape is not what this fetch assumes, and workspace.py would "
            f"double-prefix it into an unclonable URL at prep time."
        )
    if not _SLUG.match(repo):
        raise ValueError(
            f"instance {ident!r} field 'repo' is {repo!r}, which is not an 'owner/name' "
            f"slug"
        )
    return repo


def rows_to_pool(
    rows: Iterable[object],
) -> tuple[tuple[InstanceRecord, ...], dict[str, int]]:
    """Raw datasets-server rows -> validated records + the per-tier counts.

    Pure: no clock, no network, no randomness. Returns the surviving records in input
    order, and a counts dict (`all`, `pure_python`, `small_patch`, `short_statement`)
    that `main` writes verbatim into `pool.json`'s provenance header — so the published
    tier sizes are the ones the filters actually produced, not numbers typed later.

    Raises `ValueError` for a malformed envelope, a missing/blank consumed field, or a
    `repo` that is not an `owner/name` slug. Excludes — and reports on stderr — rows from
    a repo outside the allow-list that is not a known exclusion, and rows whose problem
    statement is blank.
    """
    counts = {"all": 0, "pure_python": 0, "small_patch": 0, "short_statement": 0}
    records: list[InstanceRecord] = []
    unknown_repos: set[str] = set()

    for index, entry in enumerate(rows):
        row = _row_of(entry, index)
        counts["all"] += 1

        values = {
            field: _require_str(row, field, index=index)
            for field in _ROW_FIELDS
            if field != "problem_statement"
        }
        instance_id = values["instance_id"]
        repo = _require_slug(values["repo"], ident=instance_id)

        if repo not in PURE_PYTHON_REPOS:
            if repo not in KNOWN_EXCLUDED_REPOS:
                unknown_repos.add(repo)
            continue
        counts["pure_python"] += 1

        if changed_line_count(values["patch"]) > MAX_CHANGED_LINES:
            continue
        counts["small_patch"] += 1

        # Read last and not through `_require_str`: a blank statement is a skip-and-report,
        # not a hard failure — the dataset is allowed to contain one, we just cannot mint
        # it (an empty task drives an agent to do nothing and proves nothing).
        statement = row.get("problem_statement")
        if not isinstance(statement, str) or not statement.strip():
            print(
                f"skipping {instance_id}: problem_statement is blank; a task string is "
                f"never derived from nothing",
                file=sys.stderr,
            )
            continue
        if len(statement) > MAX_STATEMENT_CHARS:
            continue
        counts["short_statement"] += 1

        records.append(
            InstanceRecord(
                instance_id=instance_id,
                repo=repo,
                base_commit=values["base_commit"],
                problem_statement=statement,
                task_string=derive_task_string(statement),
                is_control=False,
            )
        )

    for repo in sorted(unknown_repos):
        print(
            f"excluded repo {repo!r}: it is in neither PURE_PYTHON_REPOS nor "
            f"KNOWN_EXCLUDED_REPOS. Allow-list semantics mean it is dropped, but a repo "
            f"nobody has classified is dataset drift — classify it deliberately.",
            file=sys.stderr,
        )

    return tuple(records), counts


def build_header(
    counts: Mapping[str, int],
    *,
    num_rows_total: int,
    revision: str | None,
    fetched_at: str,
) -> dict[str, object]:
    """The provenance header written above the records in `pool.json`. Pure.

    Records what a reader needs to judge the pool without running this code: the dataset
    coordinates, the revision (or `null` plus `REVISION_NOTE` — D2's honest fallback),
    the three filter thresholds **taken from the module constants** rather than typed,
    D5's counting rule verbatim, and the surviving count at each filter tier.

    The header is a *claim*; `tests/test_eval_mint_set.py` checks it against the records
    in the same file (`counts["short_statement"] == len(records)`, thresholds equal the
    constants). That check is what makes the published composition falsifiable instead of
    decorative — a regeneration that moves the data but not the claim fails loudly.

    `fetched_at` and `revision` are arguments, not read here, so this stays free of the
    clock and the network and can be tested offline.
    """
    return {
        "dataset": DATASET,
        "config": CONFIG,
        "split": SPLIT,
        "revision": revision,
        "revision_note": REVISION_NOTE,
        "source_url": ROWS_ENDPOINT,
        "fetched_at": fetched_at,
        "num_rows_total": num_rows_total,
        "filters": {
            "pure_python_repos": sorted(PURE_PYTHON_REPOS),
            "known_excluded_repos": sorted(KNOWN_EXCLUDED_REPOS),
            "max_changed_lines": MAX_CHANGED_LINES,
            "changed_line_rule": (
                "count lines of the instance's `patch` that begin with '+' or '-', "
                "excluding the '+++'/'---' file headers; '@@' hunk headers, "
                "'diff --git'/'index' lines and context lines are not changes and are "
                "not counted"
            ),
            "max_statement_chars": MAX_STATEMENT_CHARS,
            "requires_non_blank_statement": True,
        },
        "counts": dict(counts),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch the dataset and write the pool. **The only thing here that hits the network.**

    Run by a human; its output is committed. `urllib` is imported *inside* this function
    on purpose (see the module docstring): importing this module must not put an HTTP
    client in scope, and a static guard in `tests/test_eval_pool_fetch.py` enforces it.
    """
    import argparse
    import urllib.error
    import urllib.parse
    import urllib.request
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser(
        description=(
            "Fetch SWE-bench-lite and write the strict-eligible Phase-0 instance pool. "
            "Touches the network; its output is committed and read by everything else."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent.parent / "instances" / "pool.json",
        help="where to write the pool (default: eval/instances/pool.json)",
    )
    parser.add_argument(
        "--page-size", type=int, default=100, help="rows per request (default: 100)"
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=300,
        help="stop after this many rows (default: the 300 rows of SWE-bench-lite)",
    )
    parser.add_argument(
        "--expect-revision",
        default=None,
        help=(
            "refuse the fetch unless the live dataset revision equals this value. D2's "
            "drift guard. The /rows envelope reported no revision when the committed "
            "pool was fetched, so passing this currently fails loudly rather than "
            "silently accepting an unpinnable fetch."
        ),
    )
    args = parser.parse_args(argv)

    rows: list[object] = []
    revision: str | None = None
    num_rows_total: int | None = None
    offset = 0
    while offset < args.max_rows:
        query = urllib.parse.urlencode(
            {
                "dataset": DATASET,
                "config": CONFIG,
                "split": SPLIT,
                "offset": offset,
                "length": min(args.page_size, args.max_rows - offset),
            }
        )
        url = f"{ROWS_ENDPOINT}?{query}"
        try:
            with urllib.request.urlopen(url) as response:  # noqa: S310 - fixed https URL
                if response.status != 200:
                    raise ValueError(f"{url} returned HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ValueError(f"{url} returned HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"{url} is unreachable: {exc.reason}") from exc

        page = payload.get("rows")
        if not isinstance(page, list):
            raise ValueError(f"{url} returned no 'rows' list")

        for key in _REVISION_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                revision = value
                break
        reported_total = payload.get("num_rows_total")
        if isinstance(reported_total, int):
            num_rows_total = reported_total

        if not page:
            break
        rows.extend(page)
        offset += len(page)

    if args.expect_revision is not None and args.expect_revision != revision:
        raise ValueError(
            f"--expect-revision {args.expect_revision!r} does not match the revision "
            f"reported by {ROWS_ENDPOINT}, which was {revision!r}. Refusing rather than "
            f"refreshing silently: an unexpected revision means the pool would be drawn "
            f"from a dataset nobody reviewed."
        )

    records, counts = rows_to_pool(rows)
    header = build_header(
        counts,
        num_rows_total=num_rows_total if num_rows_total is not None else counts["all"],
        revision=revision,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    dump_registry(records, args.out, header=header)
    print(
        f"wrote {len(records)} instances to {args.out} (tiers: {counts})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - human-run entry point
    raise SystemExit(main())


__all__ = [
    "DATASET",
    "CONFIG",
    "SPLIT",
    "ROWS_ENDPOINT",
    "MAX_CHANGED_LINES",
    "MAX_STATEMENT_CHARS",
    "KNOWN_EXCLUDED_REPOS",
    "PURE_PYTHON_REPOS",
    "REVISION_NOTE",
    "build_header",
    "changed_line_count",
    "rows_to_pool",
    "main",
]
