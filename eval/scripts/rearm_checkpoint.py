"""Re-arm the instances a provider quota cap stranded in an already-written ledger.

The circuit breaker (`eval/minting_driver/resilience.py`, `eval/minting_driver/batch.py`)
stops a *future* mint from recording a quota rejection as `failed`. It cannot help the
ledger that already exists. On 2026-07-24 a Stage-3 mint hit Google's 250-requests-per-day
cap on instance 3 of 68 and fed the remaining 56 into the same wall in 3m48s; every
rejection landed as `"failed"`, and `Checkpoint.is_done` counts `failed` as **done**. Those
56 instances are the missing denominator, and no resume will ever re-drive them.

This is the one-off migration that fixes exactly that file. It rewrites a `failed` entry
to `"no_observation"` — the status `is_done` re-arms — **if and only if** its recorded
`reason` classifies `quota` under the same `classify_error` the live breaker uses. That
reuse is the point, and it is why the classifier is duck-typed: here there is no exception
object at all, only the text `str(exc)` left behind in the ledger months ago.

Three rules make this a migration rather than a re-roll:

1. **`captured` is never touched, whatever its reason says.** An instance that produced a
   trace produced an observation and is done. Re-arming it would double-spend and replace
   a recorded result with a second roll of the same dice — `eval/README.md` bans `--force`
   for this reason, and `mint-execution/spec.md` names it: *"silently re-rolling until the
   number looks good is precisely the dishonesty this project exists to prevent."* The
   guard is the **status**, never the classifier.
2. **A genuine failure stays `failed`.** It ran, it errored, an observation exists. Only a
   quota rejection produced none.
3. **The original reason is preserved in `history`.** `Checkpoint.record` appends the
   superseded `{status, reason}` before overwriting, so the evidence for *why* each
   instance became eligible again survives in the file itself.

Fail-closed and fail-loud: a corrupt ledger raises (inherited from `load_checkpoint`), and
an **absent** ledger is an error here rather than the empty first-run case, because for
this tool a path that is not there is a typo and "0 to re-arm" would read as "clean".

Idempotent: after one pass no `failed` entry classifies `quota`, so a second run changes
nothing. `--dry-run` prints the same plan and writes nothing at all.

Stdlib only; no clock, no network, no randomness — re-running on an unchanged ledger
produces identical bytes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

from eval.minting_driver.checkpoint import Checkpoint, load_checkpoint
from eval.minting_driver.resilience import classify_error

#: The reason written onto a re-armed entry. Deliberately describes the MIGRATION rather
#: than repeating the provider's text: the provider's text is not lost (it moves to
#: `history`), and an entry whose reason is a copy of the old one is indistinguishable
#: from one this tool never touched.
REARM_REASON = (
    "re-armed by eval/scripts/rearm_checkpoint.py: the recorded failure classifies as a "
    "provider quota cap, so no session ran and no observation was produced. The original "
    "reason is preserved in this entry's history."
)

#: How much of a reason string the per-instance report line shows. Long enough to
#: recognise the error, short enough that 56 of them stay readable.
_REASON_EXCERPT = 96


def quota_failures(checkpoint: Checkpoint) -> tuple[str, ...]:
    """The `failed` instances whose recorded reason classifies `quota`, in ledger order.

    `classify_error` is handed the **reason string itself**, not a reconstructed
    exception: it reads `status_code` via `getattr` (absent on a `str`, so `None`) and
    otherwise inspects the message, which is exactly the information a ledger preserves.
    Wrapping the text in a synthetic exception would add nothing and would invite the
    fiction that the original exception object survived.

    A `None` reason classifies `terminal` (there is nothing to recognise) and is left
    alone — conservative in the safe direction, like the classifier itself.
    """
    return tuple(
        instance_id
        for instance_id in checkpoint.instance_ids()
        # The status guard comes FIRST and is not negotiable: `captured` is never a
        # candidate, however its reason happens to read.
        if checkpoint.status(instance_id) == "failed"
        and classify_error(checkpoint.reason(instance_id) or "") == "quota"
    )


def _excerpt(reason: Optional[str]) -> str:
    """One legible line from a reason string: newlines flattened, tail elided."""
    if not reason:
        return "(no reason recorded)"
    flat = " ".join(reason.split())
    if len(flat) <= _REASON_EXCERPT:
        return flat
    return flat[:_REASON_EXCERPT] + "..."


def rearm(checkpoint: Checkpoint, instance_ids: Sequence[str]) -> None:
    """Rewrite each named instance to `no_observation`, in place, preserving history.

    `Checkpoint.record` does the history append itself, so this is deliberately a thin
    loop: a second implementation of "supersede but do not erase" is a second place for
    the append-only guarantee to be wrong.
    """
    for instance_id in instance_ids:
        checkpoint.record(instance_id, "no_observation", reason=REARM_REASON)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Re-arm the stranded quota failures in one ledger. Exit 0, or 2 on a bad ledger."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m eval.scripts.rearm_checkpoint",
        description=(
            "Rewrite the `failed` entries of a mint checkpoint whose recorded reason is "
            "a provider quota cap into `no_observation`, so a resume re-drives them. "
            "`captured` entries are never touched; the original reason is preserved in "
            "each entry's history."
        ),
    )
    parser.add_argument(
        "--checkpoint",
        required=True,
        type=Path,
        metavar="path",
        help=(
            "the ledger to re-arm. REQUIRED and never defaulted: this rewrites the only "
            "record of a live, unrepeatable mint, and a default is how it gets pointed "
            "at the wrong file"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print exactly what would change and write nothing",
    )
    args = parser.parse_args(argv)

    path = Path(args.checkpoint)
    if not path.is_file():
        # `load_checkpoint` reads an absent path as the empty first-run case, which is
        # right for a mint and wrong here: a ledger that is not there is a typo, and
        # reporting "0 to re-arm" would read as "this ledger is already clean".
        print(
            f"rearm: no checkpoint at {path} — nothing was read. This tool migrates an "
            f"EXISTING ledger; an absent path is a typo, not an empty one.",
            file=sys.stderr,
        )
        return 2

    try:
        checkpoint = load_checkpoint(path)
    except ValueError as exc:
        # Fail-closed, inherited: a ledger that cannot be parsed must never be treated
        # as "nothing to do" — that silence is how the 56 vanished in the first place.
        print(f"rearm: {exc}", file=sys.stderr)
        return 2

    all_ids = checkpoint.instance_ids()
    candidates = quota_failures(checkpoint)

    if args.dry_run:
        print(f"rearm: DRY RUN — nothing will be written to {path}")
    else:
        print(f"rearm: {path}")
    print(f"  {len(all_ids)} entr(ies) recorded")
    print(f"  {len(candidates)} to re-arm (failed -> no_observation, quota-classified)")
    print(f"  {len(all_ids) - len(candidates)} untouched")
    for instance_id in candidates:
        print(f"  re-arm {instance_id}: {_excerpt(checkpoint.reason(instance_id))}")

    if args.dry_run or not candidates:
        # Nothing to re-arm is a legitimate, idempotent outcome — and it must not
        # rewrite the file either, so a second run leaves identical bytes.
        return 0

    rearm(checkpoint, candidates)
    # Atomic (temp file + `os.replace`), so an interrupted migration leaves the whole
    # old ledger or the whole new one, never a torn file.
    checkpoint.save(path)
    print(f"  wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())


__all__ = ["REARM_REASON", "main", "quota_failures", "rearm"]
