"""Re-add the 7 hand-audited Phase-0 cases in the v2 (`task_prestate`) case format.

A case cannot be upgraded in place: `shutil.copytree` in `corpus/add.py` has no
`dirs_exist_ok`, so a re-add forces deleting the case directory first. That makes this a
destructive one-time migration over data whose human labels are irreplaceable, so the whole
procedure is expressed here as gated steps rather than typed at a shell.

## The stage table is SAFETY-CRITICAL

`pallets__flask-4992` and `pylint-dev__pylint-5859` were each minted TWICE, in `s2` and in
`s3`, with different turn counts — so "turn 14 of flask-4992" names two DIFFERENT turns
depending on the stage. Picking the wrong one re-adds a different turn under the SAME case
id, and that case would then be re-labeled from the backup, reach `PASS` under the new rule,
and report MATCH. **Nothing would go red**, and the fixture set that is the acceptance
criterion for the whole unit would be certifying the rule against turns no human adjudicated.

The only in-corpus discriminator was `provenance.captured_at`, and a re-add overwrites it
with a fresh clock read. So `SOURCES` below is the record, and `--verify` is its enforcement:
per case, the trace's records must hash EQUAL to the named source capture's. Run it BEFORE
the delete (the current cases must match) and AFTER the re-add (the new ones must too).

## What this deliberately does NOT do

It does not restore the human labels. `add_case` has no `root_cause` parameter and must not
grow one — its documented purpose is that the engine never labels, and every parameter added
to it is another surface on which a future change could connect `verdict` to `human_label`.
Labels come back through `belay corpus label`, the validated path that exists for human
adjudication. `corpus_label_backup.py compare` then proves they came back intact.

Eval-only, in the shape of `rearm_checkpoint.py`: not part of the `belay` CLI, and no product
surface imports it. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

__all__ = ["SOURCES", "trace_digest", "verify_sources", "readd", "main"]

#: The default mint root. Gitignored, ~5.5 GB, and NOT movable — the captures embed absolute
#: snapshot paths — so the re-add reads them where they lie.
DEFAULT_MINT = Path(
    "/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/eval/mint"
)

#: `case id -> (mint stage, capture stem, target turn)`. Established MECHANICALLY, not by
#: eye: each case's `trace.jsonl` was parsed to records, hashed, and matched against the same
#: hash of every `eval/mint/{s1p,s2,s3}/batch/*.jsonl`; every case matched exactly one source.
#: Note the two `s2` rows sitting among the `s3` ones — that is the twice-minted hazard, and
#: it is why this table is committed rather than reconstructed.
SOURCES: dict[str, tuple[str, str, int]] = {
    "trace-pallets__flask-4045-turn8": ("s1p", "trace-pallets__flask-4045", 8),
    "trace-pallets__flask-4992-turn10": ("s3", "trace-pallets__flask-4992", 10),
    "trace-pallets__flask-4992-turn12": ("s3", "trace-pallets__flask-4992", 12),
    "trace-pallets__flask-4992-turn14": ("s2", "trace-pallets__flask-4992", 14),
    "trace-pallets__flask-4992-turn19": ("s3", "trace-pallets__flask-4992", 19),
    "trace-pylint-dev__pylint-5859-turn11": ("s2", "trace-pylint-dev__pylint-5859", 11),
    "trace-pylint-dev__pylint-5859-turn6": ("s3", "trace-pylint-dev__pylint-5859", 6),
}


def trace_digest(path: Path) -> str:
    """The sha256 of a trace's RECORD LIST, as sorted-key JSON.

    Over the parsed records rather than the raw bytes, because `add_case` re-serialises each
    record with `json.dumps` — a byte hash would differ on whitespace alone and prove nothing
    about whether the same turns are present. Sorted keys make the digest independent of key
    order on either side.
    """
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    payload = json.dumps(records, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_trace(mint: Path, case_id: str) -> Path:
    stage, stem, _turn = SOURCES[case_id]
    return mint / stage / "batch" / f"{stem}.jsonl"


def _source_manifests(mint: Path, case_id: str) -> Path:
    stage, stem, _turn = SOURCES[case_id]
    return mint / stage / "batch" / f"{stem}.manifests"


def verify_sources(corpus_dir: Path, mint: Path) -> list[str]:
    """Acceptance criterion 10, PER CASE: return the mismatches; empty means the table holds.

    Per case and never aggregated — a count would let one wrong-stage case through, and a
    wrong-stage case is precisely the failure that stays green.
    """
    problems: list[str] = []
    for case_id in SOURCES:
        bundled = Path(corpus_dir) / case_id / "trace.jsonl"
        source = _source_trace(mint, case_id)
        if not bundled.is_file():
            problems.append(f"{case_id}: no bundled trace at {bundled}")
            continue
        if not source.is_file():
            problems.append(f"{case_id}: no source capture at {source}")
            continue
        got, want = trace_digest(bundled), trace_digest(source)
        if got != want:
            problems.append(
                f"{case_id}: bundled trace sha256 {got[:16]} != source {source} {want[:16]} "
                f"— WRONG MINT STAGE, the case would carry a turn nobody adjudicated"
            )
    return problems


def readd(corpus_dir: Path, mint: Path, *, dry_run: bool = False) -> int:
    """Delete and re-add all 7 cases through `belay corpus add`. Returns an exit code.

    Goes through the CLI rather than `add_case` directly for one reason: `_cmd_corpus_add`
    derives `source_trace_id=trace_path.stem`, which is what reproduces the identical case
    ids. It also recomputes the verdict with the same effective A1 policy `verify` uses, so
    the stored `expected` is the verdict the CURRENT rule computes — which is the whole point
    of re-adding after the rule landed rather than before.

    NOT through `phase0 run`: that ingests only FLAGGED turns, and under the new rule these
    seven are no longer flagged, so it would never ingest them.
    """
    corpus_dir = Path(corpus_dir)
    for case_id, (stage, stem, turn) in SOURCES.items():
        case_dir = corpus_dir / case_id
        server = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))["server_command"]
        cmd = [
            sys.executable, "-m", "belay.cli", "corpus", "add",
            str(_source_trace(mint, case_id)),
            "--turn", str(turn),
            "--manifest-dir", str(_source_manifests(mint, case_id)),
            "--corpus-dir", str(corpus_dir),
            "--label", "false-positive",
            "--server", *server,
        ]
        print(f"  {case_id}  <- {stage}/{stem} turn {turn}")
        if dry_run:
            continue
        shutil.rmtree(case_dir)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"  FAIL {case_id}: corpus add exited {result.returncode}")
            return result.returncode
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Re-add the 7 hand-audited Phase-0 cases in the v2 case format. `--verify` is "
            "acceptance criterion 10 and must pass both before the delete and after the "
            "re-add; a mismatch means a WRONG MINT STAGE."
        )
    )
    parser.add_argument("corpus_dir", help="the corpus directory of case dirs")
    parser.add_argument("--mint", default=str(DEFAULT_MINT), help="the mint capture root")
    parser.add_argument(
        "--verify", action="store_true", help="only check the trace hashes; write nothing"
    )
    parser.add_argument("--dry-run", action="store_true", help="report the plan; write nothing")
    args = parser.parse_args(argv)

    corpus_dir, mint = Path(args.corpus_dir), Path(args.mint)

    if args.verify:
        problems = verify_sources(corpus_dir, mint)
        print(f"verify trace provenance {corpus_dir} against {mint}")
        print()
        for case_id in SOURCES:
            stage, stem, turn = SOURCES[case_id]
            failed = any(p.startswith(f"{case_id}:") for p in problems)
            print(f"  {case_id:<40}{stage}/{stem} turn {turn:<4}"
                  f"{'MISMATCH' if failed else 'sha256 equal'}")
        print()
        for problem in problems:
            print(f"  FAIL {problem}")
        if problems:
            print()
            print(f"  {len(problems)} problem(s) — DO NOT PROCEED")
            return 1
        print(f"  {len(SOURCES)} case(s) match their named source capture")
        return 0

    print(f"re-add {len(SOURCES)} case(s) into {corpus_dir}{' (dry run)' if args.dry_run else ''}")
    print()
    return readd(corpus_dir, mint, dry_run=args.dry_run)


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    raise SystemExit(main())
