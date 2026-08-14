"""RED contract tests for `eval/scripts/derive_observed_ids.py`.

`registry-rescope/spec.md` AC-1: the previously-minted set is derived deterministically
from committed artifacts only, never typed by hand — the observed set is what keeps the
gate mint's fresh draws honest, so the derivation is pinned by test on the committed
sources:

* every real (non-control) id in the committed stage registries (`stage2.json`,
  `stage4.json`, `stage4a.json`) is a member;
* `pytest-dev__pytest-7432`, the live smoke, is a member;
* the banked corpus literal (`EXCLUDED_INSTANCE_IDS`) is a subset — while the
  committed `observed.json` artifact does not exist yet, that literal is the
  independent check; once the artifact is committed, the derivation must equal it;
* the set is deterministic (two calls, identical result), sorted, non-empty, and
  contains no control id.

No network, no clock: every source is a committed file in the repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.instances.registry import load_registry, real
from eval.scripts.build_stage4_registry import EXCLUDED_INSTANCE_IDS
from eval.scripts.derive_observed_ids import derive_observed_ids

REPO_ROOT = Path(__file__).parent.parent
INSTANCES_DIR = REPO_ROOT / "eval" / "instances"

#: The committed stage registries whose real ids are previously-minted.
STAGE_REGISTRIES = ("stage2.json", "stage4.json", "stage4a.json")

#: The committed artifact the derived set is written to (AC-1, byte-identical
#: regeneration). Not committed yet: until it exists the test falls back to
#: EXCLUDED_INSTANCE_IDS as the independent check.
OBSERVED_ARTIFACT = INSTANCES_DIR / "observed.json"

#: The 2026-08-05 live smoke capture (`subscription-model-client`).
SMOKE_INSTANCE_ID = "pytest-dev__pytest-7432"


def _committed_stage_real_ids() -> set[str]:
    """The real ids of the committed stage registries, read through the shipped loader."""
    ids: set[str] = set()
    for name in STAGE_REGISTRIES:
        for record in real(load_registry(INSTANCES_DIR / name)):
            ids.add(record.instance_id)
    return ids


def test_observed_ids_derived_deterministically() -> None:
    first = derive_observed_ids()
    second = derive_observed_ids()

    assert first == second, (
        "the derivation must be a pure function of committed files: two calls, "
        "identical result"
    )
    assert isinstance(first, tuple)
    assert all(isinstance(instance_id, str) for instance_id in first)
    assert first == tuple(sorted(first)), (
        "the set must be sorted, so a regenerated artifact compares byte-for-byte"
    )
    assert first, "the observed set must be non-empty: the gate has minted before"

    controls_in_set = [instance_id for instance_id in first if instance_id.startswith("control__")]
    assert not controls_in_set, (
        f"the observed set must never contain a control id: {controls_in_set}"
    )

    committed = _committed_stage_real_ids()
    missing = sorted(committed - set(first))
    assert not missing, (
        f"every real id of the committed stage registries is previously-minted and "
        f"must be in the observed set; missing: {missing}"
    )


def test_observed_ids_smoke_included() -> None:
    assert SMOKE_INSTANCE_ID in derive_observed_ids(), (
        "the 2026-08-05 live smoke capture was driven live and must never be re-minted"
    )


def test_observed_ids_regeneration_byte_identical() -> None:
    derived = set(derive_observed_ids())

    if OBSERVED_ARTIFACT.exists():
        committed = json.loads(OBSERVED_ARTIFACT.read_text(encoding="utf-8"))
        if isinstance(committed, dict) and "instances" in committed:
            committed = committed["instances"]
        assert isinstance(committed, list) and all(
            isinstance(item, str) for item in committed
        ), "observed.json must be a JSON list of instance ids"
        assert committed == sorted(committed), "the committed artifact must be sorted"
        assert len(committed) == len(set(committed)), "the committed artifact has no duplicates"
        assert set(committed) == derived, (
            "the committed observed.json must equal the derived set exactly (AC-1: "
            "regeneration is byte-identical)"
        )
    else:
        missing = sorted(set(EXCLUDED_INSTANCE_IDS) - derived)
        assert not missing, (
            "every banked EXCLUDED_INSTANCE_IDS id (the s2/s3 corpus transcription "
            "and the smoke) is previously-minted and must be in the derived set; "
            f"missing: {missing}"
        )
