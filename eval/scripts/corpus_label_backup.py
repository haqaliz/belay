"""Gate the destructive corpus re-add on the human labels being provably recoverable.

`corpus-task-prestate` changes what a case bundles, and `shutil.copytree` (`corpus/add.py`)
has no `dirs_exist_ok`, so re-adding a case FORCES deleting its directory first. That
deletion destroys `human_label` and `root_cause` — a hand-audit that cannot be repeated
cheaply, and whose free-text `note` exists nowhere else: `docs/technical/PHASE0_AUDIT.md`
carries the keys and the labels but PARAPHRASES the notes, so it is not a fallback.

Two executable checks, which are the aspect's acceptance criteria 11a and 11b:

    verify   — every backed-up case.json parses, carries a known `human_label`, and carries
               a `root_cause` with a non-empty `key` AND a non-empty `note`. This runs
               BEFORE any deletion; it is a gate, not a report.
    compare  — per case, the restored `human_label`, `root_cause.key`, and `root_cause.note`
               equal the backup CHARACTER FOR CHARACTER. Per case, never aggregated: a
               count would let one silently-truncated note through.

Both exit non-zero on any failure, so they can be run as a gate rather than read.

Eval-only, in the shape of `backfill_target_tool.py`: not part of the `belay` CLI, and no
product surface imports it. Stdlib only; no clock, no network, no replay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

from belay.corpus.case import _KNOWN_LABELS, CASE_FILENAME, load_case

__all__ = ["load_backup", "check_backup", "compare_restored", "main"]

#: The backup filename for a case, as written beside its siblings in one flat directory:
#: `<case-id>.case.json`. Flat rather than nested so the backup cannot be mistaken for a
#: corpus (a directory of case dirs), which is what `run_corpus` would try to replay.
_BACKUP_SUFFIX = ".case.json"


def load_backup(backup_dir: Path) -> dict[str, dict]:
    """Every backed-up case as `{case_id: parsed case.json}`, or raise a named `ValueError`.

    Parsed with plain `json`, NOT `load_case`: the backup is a copy of bytes, and the point
    of checking it is to learn whether those bytes are intact. Routing through the loader
    would conflate "the backup is unreadable" with "the loader rejects this shape".
    """
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        raise ValueError(f"backup directory not found: {backup_dir}")
    backups: dict[str, dict] = {}
    for path in sorted(backup_dir.glob(f"*{_BACKUP_SUFFIX}")):
        case_id = path.name[: -len(_BACKUP_SUFFIX)]
        try:
            backups[case_id] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"backup {path!r} could not be parsed: {exc}") from exc
    return backups


def check_backup(backup_dir: Path) -> list[str]:
    """Acceptance criterion 11a: return the problems with `backup_dir`; empty means it passes.

    A problem is a case whose backup lacks a `human_label` in `_KNOWN_LABELS`, or lacks a
    `root_cause` with a non-empty `key` and a non-empty `note`. Returned as a list rather
    than raised on the first one so a single run reports every gap in the backup — the whole
    point being to learn the backup is short BEFORE the originals are deleted.
    """
    problems: list[str] = []
    backups = load_backup(backup_dir)
    if not backups:
        return [f"{backup_dir}: no backups found"]
    for case_id, payload in backups.items():
        label = payload.get("human_label")
        if label not in _KNOWN_LABELS:
            problems.append(f"{case_id}: human_label is {label!r}, not a known label")
        cause = payload.get("root_cause")
        if not isinstance(cause, dict):
            problems.append(f"{case_id}: root_cause is {cause!r}, not an object")
            continue
        for field in ("key", "note"):
            value = cause.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{case_id}: root_cause.{field} is empty or missing")
    return problems


def compare_restored(backup_dir: Path, corpus_dir: Path) -> list[str]:
    """Acceptance criterion 11b: return per-case inequalities; empty means the labels survived.

    Compares the CURRENT corpus against the backup, per case, on the three human-authored
    fields and on nothing else — `expected` is the engine's and legitimately changes across
    a re-add. The note is compared with `!=` on the whole string, so a truncation of one
    character is a failure, and the case id is named in every message.
    """
    problems: list[str] = []
    backups = load_backup(backup_dir)
    corpus_dir = Path(corpus_dir)
    for case_id, payload in backups.items():
        case_dir = corpus_dir / case_id
        if not (case_dir / CASE_FILENAME).is_file():
            problems.append(f"{case_id}: no case in {corpus_dir} to compare against")
            continue
        case = load_case(case_dir)  # fail-closed: a corrupt restored case raises
        if case.human_label != payload.get("human_label"):
            problems.append(
                f"{case_id}: human_label {case.human_label!r} != "
                f"backup {payload.get('human_label')!r}"
            )
        want = payload.get("root_cause") or {}
        got = case.root_cause or {}
        for field in ("key", "note"):
            if got.get(field) != want.get(field):
                problems.append(
                    f"{case_id}: root_cause.{field} differs from the backup "
                    f"(restored {len(got.get(field) or '')} chars, "
                    f"backup {len(want.get(field) or '')} chars)"
                )
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Gate the destructive corpus re-add on the human labels being recoverable: "
            "`verify` checks the backup before any deletion, `compare` proves the restored "
            "labels equal it character for character."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="acceptance criterion 11a (run BEFORE deleting)")
    verify.add_argument("backup_dir", help="directory of <case-id>.case.json backups")

    compare = sub.add_parser("compare", help="acceptance criterion 11b (run AFTER relabeling)")
    compare.add_argument("backup_dir", help="directory of <case-id>.case.json backups")
    compare.add_argument("corpus_dir", help="the corpus directory of case dirs")

    args = parser.parse_args(argv)

    if args.command == "verify":
        backups = load_backup(Path(args.backup_dir))
        problems = check_backup(Path(args.backup_dir))
        print(f"verify backup {args.backup_dir}")
        print()
        for case_id, payload in backups.items():
            cause = payload.get("root_cause") or {}
            note = cause.get("note") or ""
            print(
                f"  {case_id:<40}{payload.get('human_label')!s:<16}"
                f"key={cause.get('key')!r} note={len(note)} chars"
            )
        print()
    else:
        problems = compare_restored(Path(args.backup_dir), Path(args.corpus_dir))
        backups = load_backup(Path(args.backup_dir))
        print(f"compare {args.corpus_dir} against backup {args.backup_dir}")
        print()
        failed = {p.split(":")[0] for p in problems}
        for case_id in backups:
            print(f"  {case_id:<40}{'DIFFERS' if case_id in failed else 'identical'}")
        print()

    if problems:
        for problem in problems:
            print(f"  FAIL {problem}")
        print()
        print(f"  {len(problems)} problem(s) — the labels are NOT provably safe")
        return 1
    print(f"  {len(backups)} case(s) OK")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    raise SystemExit(main())
