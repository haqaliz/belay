"""Persist a snapshot so a later process can restore it.

C2 takes a snapshot every turn and keeps everything `clone.restore` needs — the
`Sidecar` above all — **in memory**, in `gate.snapshots[handle]`. The trace records
only the handle; the disk holds only the cloned `turn-NNNN/` tree; nothing joins
them. `belay replay` runs in a later process by definition, so until the two are
joined on disk, a recorded handle cannot be turned back into a restorable pre-state.
This module is that join.

## Why the sidecar is the whole point

`clonefile` silently destroys three things — hardlink identity, setuid, and
directory mtimes — and all three are invisible to a content-only hash (see
`clone.py` and `bth1.py`). `clone.restore` puts them back **from the sidecar**, which
is why a `Snapshot` reconstructed with a *synthesized empty* sidecar would restore, a
hash of it would look correct, and it would have dropped exactly the divergence BTH-1
exists to catch — a false PASS with a hash on it. So the sidecar is not derived from
the on-disk tree here; it is **persisted from the original capture and reconstructed
byte-for-byte**.

## The bytes stay bytes

A `Sidecar`'s paths are raw bytes, for the reason BTH-1 gives: decoding a path would
reintroduce unicode normalisation into a comparison whose entire claim is that it is
byte-exact. JSON cannot hold arbitrary bytes, so each path is **base64-encoded and
never decoded** — the base64 round-trips a non-UTF-8 name that `str` would corrupt.
The mode and time integers are stored as themselves.

## No verdicts

This module writes and reads facts. Whether a restored tree matches, and what that
means, is C3's replay diff and C4's verdict — never decided here.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Optional

from belay.snapshot.clone import Sidecar, Snapshot
from belay.snapshot.substrate import FIDELITY_GAPS, GuardedSnapshot, Manifest


def _b64(raw: bytes) -> str:
    """Raw bytes -> an ASCII base64 string. The path is never decoded as text."""
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    """An ASCII base64 string -> the exact raw bytes it encoded."""
    return base64.b64decode(text)


def _sidecar_to_json(sidecar: Sidecar) -> dict:
    """The three sidecar fields as JSON, every path base64-encoded.

    Structure mirrors `Sidecar` exactly so that `_sidecar_from_json` can rebuild a
    value equal to the original: a link group is a primary and its other members, a
    special mode is a path and its `S_IMODE`, a dir time is a path and its
    `(atime_ns, mtime_ns)` pair.
    """
    return {
        "link_groups": [
            [_b64(primary), [_b64(other) for other in others]]
            for primary, others in sidecar.link_groups
        ],
        "special_modes": [[_b64(path), mode] for path, mode in sidecar.special_modes],
        "dir_times": [
            [_b64(path), [atime_ns, mtime_ns]]
            for path, (atime_ns, mtime_ns) in sidecar.dir_times
        ],
    }


def _sidecar_from_json(data: dict) -> Sidecar:
    """Rebuild the exact `Sidecar` `_sidecar_to_json` wrote.

    Tuples throughout, not lists: `Sidecar` is a frozen dataclass whose equality is
    by field value, so the reconstruction must match the original's tuple shape or a
    round-trip that preserved every byte would still compare unequal.
    """
    return Sidecar(
        link_groups=tuple(
            (_unb64(primary), tuple(_unb64(other) for other in others))
            for primary, others in data["link_groups"]
        ),
        special_modes=tuple(
            (_unb64(path), int(mode)) for path, mode in data["special_modes"]
        ),
        dir_times=tuple(
            (_unb64(path), (int(atime_ns), int(mtime_ns)))
            for path, (atime_ns, mtime_ns) in data["dir_times"]
        ),
    )


def persist_snapshot(
    snap: GuardedSnapshot,
    manifest_path: Path,
    *,
    source_root: Optional[str] = None,
) -> None:
    """Write a manifest joining `snap`'s handle to its tree and its sidecar bytes.

    Everything a later process needs to reconstruct a restorable `GuardedSnapshot`:
    the handle the trace records, the absolute path of the cloned tree, the backend
    and capabilities `guarded_restore` refuses across, the fidelity gaps a reader
    must be told about, and the sidecar — base64, never decoded.

    `source_root`, when given, is the absolute workspace the snapshot was taken
    *from* (the gate passes its already-resolved `self._scope`). It is stored
    verbatim — resolution is the caller's responsibility, not this function's. When
    `None`, the key is **omitted entirely**, so an old-shaped manifest stays byte-clean.
    """
    manifest_path = Path(manifest_path)
    payload = {
        "handle": snap.manifest.handle,
        "tree_path": str(snap.snapshot.path),
        "backend": snap.manifest.backend,
        "capabilities": sorted(snap.manifest.capabilities),
        "fidelity_gaps": [gap.value for gap in FIDELITY_GAPS],
        "sidecar": _sidecar_to_json(snap.snapshot.sidecar),
    }
    if source_root is not None:
        payload["source_root"] = str(source_root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_snapshot(manifest_path: Path) -> GuardedSnapshot:
    """Reconstruct a restorable `GuardedSnapshot` from a persisted manifest.

    The sidecar is rebuilt from the persisted bytes — **not** synthesized from the
    on-disk tree — so `clone.restore` / `guarded_restore` put back the hardlinks,
    setuid and dir mtimes `clonefile` dropped. Reconstructing an empty sidecar here
    is the one thing this function must never do; the fresh-process restore test and
    the empty-sidecar guard exist to keep it from happening quietly.

    `tree_path` is resolved relative to the manifest's OWN directory when it is a
    relative path, so a corpus case that bundled its tree into `<case>/prestate/`
    restores identically no matter which directory the process runs from. An ABSOLUTE
    `tree_path` — what `persist_snapshot` writes and every existing caller relies on —
    is used verbatim, so this is a pure superset of the prior behaviour.
    """
    manifest_path = Path(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    tree_path = Path(payload["tree_path"])
    if not tree_path.is_absolute():
        tree_path = manifest_path.parent / tree_path
    snapshot = Snapshot(
        path=tree_path,
        sidecar=_sidecar_from_json(payload["sidecar"]),
    )
    manifest = Manifest(
        backend=payload["backend"],
        capabilities=frozenset(payload["capabilities"]),
        handle=payload["handle"],
        source_root=_load_source_root(payload),
    )
    return GuardedSnapshot(snapshot=snapshot, manifest=manifest)


def _load_source_root(payload: dict) -> Optional[str]:
    """The manifest's `source_root`, fail-closed: absent -> None, malformed -> error.

    ABSENT (an old capture written before the field existed) is `None` — backward
    compatible. PRESENT must be a non-empty ABSOLUTE string; anything else (blank, a
    relative path, a non-string) is a named `ValueError`, never a silent `None`. Losing
    the malformed-vs-absent distinction is exactly how a corrupt field would read as an
    honest old manifest.
    """
    if "source_root" not in payload:
        return None
    value = payload["source_root"]
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError(
            f"manifest source_root must be a non-empty absolute path, got {value!r}"
        )
    return value


__all__ = ["load_snapshot", "persist_snapshot"]
