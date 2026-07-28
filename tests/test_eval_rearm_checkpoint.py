"""RED-first tests for `eval/scripts/rearm_checkpoint.py` — the legacy ledger re-arm.

The circuit breaker (`eval/minting_driver/resilience.py`) stops a *future* mint from
recording a quota rejection as `failed`. It does nothing for the ledger that already
exists: `eval/mint/s3/checkpoint.json` holds 56 entries written before the vocabulary
existed, every one of them a 429 daily-cap rejection stored as `failed` — which
`Checkpoint.is_done` treats as done, permanently. Those 56 instances are the missing
denominator, and no resume will ever touch them.

This tool is the one-off that converts exactly those entries to `no_observation`, which
`is_done` re-arms. Everything asserted here is about what it must NOT do:

* **`captured` is never touched.** Re-arming a captured instance would re-drive an
  instance that already produced an observation — a double-spend, and a re-roll of a
  recorded result. `eval/README.md` bans `--force` for this reason and
  `mint-execution/spec.md` names it: "silently re-rolling until the number looks good is
  precisely the dishonesty this project exists to prevent." The guard is asserted with a
  `captured` entry carrying the REAL quota error text, so the classifier alone cannot be
  what protects it.
* **A genuine failure stays `failed`.** An instance that ran and errored produced an
  observation; only a quota rejection produced none.
* **`--dry-run` writes nothing** — asserted on the file's bytes *and* its mtime, because
  a rewrite with identical content is still a rewrite of the operator's only record.
* **A corrupt ledger is refused**, inheriting `load_checkpoint`'s fail-closed load.

Deterministic and offline: `tmp_path` only, no model, no network, no clock.
"""

from __future__ import annotations

import json

import pytest

from eval.minting_driver.checkpoint import load_checkpoint
from eval.scripts.rearm_checkpoint import main, quota_failures

#: The verbatim reason string all 56 stranded Stage-3 entries carry (the recorded
#: `str(exc)` of Google's 250-requests-per-day cap). Used rather than a paraphrase for
#: the same reason `tests/test_minting_driver_resilience.py` uses it: a tool tuned
#: against invented text would pass its tests and leave the real ledger stranded.
REAL_QUOTA_REASON = (
    "Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current "
    "quota, please check your plan and billing details. For more information on this "
    "error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your "
    "current usage, head to: https://ai.dev/rate-limit. \\n* Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_requests_per_model_per_day, limit: 250, "
    "model: gemini-3.1-pro\\nPlease retry in 10h50m43.651927829s.', 'status': "
    "'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '39043s'}]}}]"
)

#: A failure that is genuinely the instance's own: it ran, it errored, an observation
#: exists. Nothing about it is re-armable.
GENUINE_FAILURE_REASON = "BridgeCollisionError: batch destination already exists"


def _write_ledger(path, entries: dict) -> None:
    """A legacy-shaped ledger: `{status, reason, trace_path}`, no `history` key.

    Hand-written JSON on purpose — this is the shape of the file that already exists on
    disk, and writing it through `Checkpoint.save` would silently add the `history` the
    real file does not have.
    """
    path.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")


def _mixed_ledger(path):
    """3 quota `failed`, 1 genuine `failed`, 2 `captured` — one of them quota-worded."""
    _write_ledger(
        path,
        {
            "django__django-11039": {
                "status": "failed",
                "reason": REAL_QUOTA_REASON,
                "trace_path": None,
            },
            "django__django-11049": {
                "status": "failed",
                "reason": REAL_QUOTA_REASON,
                "trace_path": None,
            },
            "sympy__sympy-24152": {
                "status": "failed",
                "reason": REAL_QUOTA_REASON,
                "trace_path": None,
            },
            "pallets__flask-4045": {
                "status": "failed",
                "reason": GENUINE_FAILURE_REASON,
                "trace_path": None,
            },
            "psf__requests-2317": {
                "status": "captured",
                "reason": None,
                "trace_path": "/mint/s3/batch/trace-psf__requests-2317.jsonl",
            },
            # A `captured` entry whose reason text WOULD classify quota. The guard must
            # be the status, not the classifier: an instance that produced a trace is
            # done, whatever its reason field happens to say.
            "psf__requests-1963": {
                "status": "captured",
                "reason": REAL_QUOTA_REASON,
                "trace_path": "/mint/s3/batch/trace-psf__requests-1963.jsonl",
            },
        },
    )
    return path


def test_quota_failures_selects_only_quota_classified_failures(tmp_path):
    """The selection itself, before anything is rewritten."""
    checkpoint = load_checkpoint(_mixed_ledger(tmp_path / "cp.json"))

    assert quota_failures(checkpoint) == (
        "django__django-11039",
        "django__django-11049",
        "sympy__sympy-24152",
    )


def test_rearm_rewrites_exactly_the_quota_failures(tmp_path, capsys):
    """3 of 6 entries flip to `no_observation`; the other 3 are byte-identical."""
    path = _mixed_ledger(tmp_path / "cp.json")

    code = main(["--checkpoint", str(path)])
    assert code == 0

    after = load_checkpoint(path)
    for instance_id in (
        "django__django-11039",
        "django__django-11049",
        "sympy__sympy-24152",
    ):
        assert after.status(instance_id) == "no_observation", instance_id
        assert after.is_done(instance_id) is False, instance_id

    # The genuine failure ran and errored: it produced an observation and stays done.
    assert after.status("pallets__flask-4045") == "failed"
    assert after.is_done("pallets__flask-4045") is True
    assert after.reason("pallets__flask-4045") == GENUINE_FAILURE_REASON
    assert after.history("pallets__flask-4045") == []

    out = capsys.readouterr().out
    assert "3" in out and "re-arm" in out.lower()


def test_captured_is_never_touched_even_with_a_quota_reason(tmp_path):
    """THE guard: re-arming a captured instance is a double-spend and a re-roll.

    `psf__requests-1963` is `captured` and carries the real quota error text in its
    `reason`. If the tool selected on the reason alone it would re-arm an instance that
    already produced a trace — the mint would drive it a second time, bridge into an
    occupied batch destination, and the recorded result of the first run would be
    replaced by a second roll of the same dice.
    """
    path = _mixed_ledger(tmp_path / "cp.json")

    assert main(["--checkpoint", str(path)]) == 0

    after = load_checkpoint(path)
    for instance_id in ("psf__requests-2317", "psf__requests-1963"):
        assert after.status(instance_id) == "captured", instance_id
        assert after.is_done(instance_id) is True, instance_id
        # Untouched means untouched: no history entry, and the trace path intact.
        assert after.history(instance_id) == [], instance_id
        assert after.trace_path(instance_id) is not None, instance_id


def test_the_original_reason_is_preserved_in_history(tmp_path):
    """The re-arm supersedes the disposition; it must not erase it.

    `eval/README.md` bans `--force` for losing "the record of what already ran". A
    migration that overwrote the 56 quota reasons in place would lose exactly that, and
    with it the only evidence of WHY those instances are eligible again.
    """
    path = _mixed_ledger(tmp_path / "cp.json")

    assert main(["--checkpoint", str(path)]) == 0

    after = load_checkpoint(path)
    assert after.history("django__django-11039") == [
        {"status": "failed", "reason": REAL_QUOTA_REASON}
    ]
    # And the new reason says what happened, rather than silently repeating the old one.
    assert "re-arm" in (after.reason("django__django-11039") or "").lower()


def test_dry_run_writes_nothing_at_all(tmp_path, capsys):
    """`--dry-run` reports and returns; the file's bytes AND mtime are unchanged.

    Asserted on mtime as well as content because an identical rewrite is still a
    rewrite: this ledger is the only record of a mint that cannot be re-run.
    """
    path = _mixed_ledger(tmp_path / "cp.json")
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    code = main(["--checkpoint", str(path), "--dry-run"])

    assert code == 0
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime

    out = capsys.readouterr().out
    assert "dry run" in out.lower()
    # It still reports the same plan it would have executed.
    assert "django__django-11039" in out
    assert "3" in out


def test_rearming_twice_is_a_no_op(tmp_path, capsys):
    """Idempotent: after the first pass there are no `failed` quota entries left.

    Worth pinning because the obvious wrong implementation — select on the reason text —
    would re-arm the same entries forever, appending a history entry every time.
    """
    path = _mixed_ledger(tmp_path / "cp.json")
    assert main(["--checkpoint", str(path)]) == 0
    first_pass = path.read_bytes()
    capsys.readouterr()

    assert main(["--checkpoint", str(path)]) == 0

    assert path.read_bytes() == first_pass
    assert "0" in capsys.readouterr().out
    assert load_checkpoint(path).history("django__django-11039") == [
        {"status": "failed", "reason": REAL_QUOTA_REASON}
    ]


def test_a_corrupt_ledger_is_refused(tmp_path, capsys):
    """Fail-closed load, inherited: exit 2 and one legible line, never a traceback.

    A ledger that cannot be parsed must never be read as "nothing to do" — that is the
    same silence that let 56 instances vanish in the first place.
    """
    path = tmp_path / "corrupt.json"
    path.write_text("{not json at all", encoding="utf-8")

    code = main(["--checkpoint", str(path)])

    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err
    assert str(path) in captured.err


def test_an_unknown_status_in_the_ledger_is_refused(tmp_path, capsys):
    """The other fail-closed case: a status outside the vocabulary."""
    path = tmp_path / "weird.json"
    _write_ledger(path, {"inst": {"status": "skipped", "reason": None}})

    assert main(["--checkpoint", str(path)]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_checkpoint_is_required_with_no_default(tmp_path):
    """No default path: this tool rewrites the operator's only record of a live mint,
    and a default is how it gets pointed at the wrong ledger."""
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


def test_a_missing_ledger_is_an_error_not_an_empty_success(tmp_path, capsys):
    """`load_checkpoint` treats an absent path as the first-run case; for THIS tool that
    is a typo'd path, and reporting "0 to re-arm" would read as "the ledger is clean"."""
    code = main(["--checkpoint", str(tmp_path / "nope.json")])

    assert code == 2
    assert "Traceback" not in capsys.readouterr().err
