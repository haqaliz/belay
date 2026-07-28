"""Backfill `target_tool` onto corpus cases banked before the field existed.

The seven Phase-0 cases were composed before `corpus add` recorded the target turn's tool,
so the gate's STRICT independence clause — "distinct instances **and** distinct tools" —
is unevaluable for them. `corpus score` reports it `n/a` rather than guessing, which is
correct but leaves the criteria half-readable when they are about to be read.

The tool is recoverable exactly: every case ships its own `trace.jsonl`, and the turn is
addressed by the same `target_turn_index` the case already stores. No network, no replay,
no clock.

## Why this reuses `corpus.add._target_tool_name`

A second implementation of "which tool was turn N?" could drift from the one `corpus add`
now uses, and then a backfilled case and a freshly-composed one would disagree about the
same trace. There is one reader, used by both. That is the point.

## What it will not do

It writes ONLY `target_tool`. A migration that perturbed `expected` would corrupt the
verdicts the corpus regresses against — and the human labels are scored against those
verdicts, so a nudged verdict silently re-scores the audit. It is also idempotent: a turn
whose tool cannot be read yields `None` and the case is left untouched, never stamped with
a guessed name that would silently change the count the gate is read against.

One-off migration, in the shape of `rearm_checkpoint.py`. Eval-only: it is not part of the
`belay` CLI and no product surface imports it.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional, Sequence

from belay.corpus.add import _target_tool_name
from belay.corpus.case import CASE_FILENAME, load_case, write_case

__all__ = ["backfill_case", "backfill_corpus", "main"]


def _records(case_dir: Path) -> list[dict]:
    """The case's own bundled trace, as records."""
    path = Path(case_dir) / "trace.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read bundled trace {path!r}: {exc}") from exc
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def backfill_case(case_dir: Path) -> Optional[str]:
    """Stamp `<case_dir>`'s `target_tool` from its own trace; return the tool or `None`.

    `None` means the target turn's tool could not be read — an out-of-range index, a
    missing request frame, an unparseable payload. The case is then left byte-identical:
    absent stays absent rather than becoming a guess.
    """
    case_dir = Path(case_dir)
    case = load_case(case_dir)  # fail-closed: a corrupt case raises
    tool = _target_tool_name(_records(case_dir), case.target_turn_index)
    if tool is None:
        return None
    if case.target_tool == tool:
        return tool  # already stamped; do not rewrite for byte-stability
    write_case(case_dir, dataclasses.replace(case, target_tool=tool))
    return tool


def backfill_corpus(corpus_dir: Path) -> dict[str, Optional[str]]:
    """Backfill every case under `corpus_dir`; return `{case_id: tool_or_None}`.

    Fail-closed on a case that will not load, mirroring `corpus score`'s loop: a migration
    that silently skipped a row would leave the corpus half-migrated with no signal.
    """
    corpus_dir = Path(corpus_dir)
    results: dict[str, Optional[str]] = {}
    for case_dir in sorted(p.parent for p in corpus_dir.glob(f"*/{CASE_FILENAME}")):
        results[case_dir.name] = backfill_case(case_dir)
    return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Backfill `target_tool` onto corpus cases banked before the field existed, "
            "reading each case's own bundled trace. Writes only `target_tool`."
        )
    )
    parser.add_argument("corpus_dir", help="the corpus directory of case dirs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be stamped without writing anything",
    )
    args = parser.parse_args(argv)

    corpus_dir = Path(args.corpus_dir)
    if not corpus_dir.is_dir():
        print(f"backfill: corpus directory not found: {corpus_dir}")
        return 2

    if args.dry_run:
        results = {}
        for case_dir in sorted(p.parent for p in corpus_dir.glob(f"*/{CASE_FILENAME}")):
            case = load_case(case_dir)
            results[case_dir.name] = _target_tool_name(
                _records(case_dir), case.target_turn_index
            )
    else:
        results = backfill_corpus(corpus_dir)

    print(f"backfill target_tool {corpus_dir}{' (dry run)' if args.dry_run else ''}")
    print()
    unread = 0
    for case_id, tool in results.items():
        if tool is None:
            unread += 1
        print(f"  {case_id:<40}{tool or '(unreadable — left absent)'}")
    print()
    print(f"  {len(results)} case(s), {unread} left absent")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    raise SystemExit(main())
