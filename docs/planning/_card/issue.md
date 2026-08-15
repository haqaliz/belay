# Card: Linux sandbox slice (C2 follow-on, launch checklist L2)

Source: inline brief from the `belay-next` handoff (2026-08-15) + `docs/planning/launch-readiness/CHECKLIST.md` item L2. No GitHub issue exists for this work; the id lives in the branch and PR.

## Brief

Build the Linux sandbox slice of C2 — the first open launch-checklist item (L2), since L3 Docker / L4 PyPI / L5 cross-platform CI all block on it. The Sandbox seam exists and is macOS-only today: `seatbelt.py`/`launch.py` raise on non-darwin rather than no-op (preserve that honesty contract — never claim a boundary that doesn't exist). First slice defines the Linux implementation (seccomp/LSM/container); the riskiest part is byte-identical snapshot/restore on Linux, since the macOS path uses APFS `clonefile` — this is the Phase-0 R2 shape relocated, so start with the narrowest restorable substrate. Write the acceptance tests first, per repo discipline:

1. Sandbox/replay tests run green on Linux CI with **no platform skips** for the sandbox/replay tests.
2. An escape attempt (write outside scope, disallowed network egress) is **contained AND recorded as a denial** on the Linux substrate.
3. A turn's pre-state restores **byte-identically** (hash-of-tree equality).
4. `THREAT_MODEL.md` states exactly what the Linux boundary does and does not enforce, matching the macOS honesty contract.

## DONE criteria (from CHECKLIST.md L2)

> the sandbox seam has a Linux implementation (seccomp/LSM/container — the pick's first slice defines it), the suite runs green on Linux CI with **no** platform skips for the sandbox/replay tests, and `THREAT_MODEL.md` states exactly what the Linux boundary does and does not enforce (same honesty contract as macOS).

## Blockers / dependencies

- **Depends on nothing unshipped:** C1–C6 + C9 first slice are shipped (v0.19.0, Phase-0 gate PROCEEDED). L3 (Docker), L4 (PyPI), L5 (cross-platform CI) block on this slice.
- **Known caveat (named before the dig):** the feasibility risk is snapshot/restore fidelity on Linux (macOS uses APFS `clonefile`); the new boundary has never been measured — the honest default is "unverified until measured", and the existing raise-on-non-darwin behavior must be preserved in the seam.

## Context links

- Launch checklist: `docs/planning/launch-readiness/CHECKLIST.md` (L2 at lines 68–80)
- C2 spec: `docs/technical/CAPABILITY_ROADMAP.md` §C2 (lines 150–189)
- C2 planning: `docs/planning/sandbox-snapshot-restore/`
- Threat model: `docs/technical/THREAT_MODEL.md`
- README limits: `README.md` §"The sandbox is macOS only" (lines 220–223)
