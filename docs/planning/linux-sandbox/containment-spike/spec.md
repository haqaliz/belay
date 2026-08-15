# Aspect A1 — Containment spike on stock `ubuntu-latest`

## Problem slice

The Linux mechanism is **unmeasured**: the C2 planning docs flagged it as the
deciding open question (`docs/planning/sandbox-snapshot-restore/understanding.md:95-98,337`).
Everything downstream (A2 containment, A3 snapshot, A4 CI/docs) depends on knowing,
from an actual measurement on the CI substrate, which mechanism can enforce the
boundary there. This aspect is the measurement; it commits to nothing until it
runs.

## In-scope

- Probe, on stock `ubuntu-latest` **in CI** (a real ubuntu job):
  1. **Unprivileged user namespaces**: can `unshare -Urm` (or a Python
     `ctypes`/`os`-level probe) succeed? Is it AppArmor-restricted (Ubuntu 23.10+
     `apparmor_restrict_unprivileged_userns`)?
  2. **bwrap**: installable? runs? (measured behaviors: write-scope binding,
     `--unshare-net`, EPERM/EACCES on refused writes, denial text on stderr)
  3. **Landlock**: kernel ≥5.13? `prctl(PR_LANDLOCK_CREATE_RULESET)` reachable from
     Python 3.12 via ctypes? Which LANDLOCK_ACCESS_FS bits map onto the write-scope
     semantics of `seatbelt.build_profile`?
  4. **Denial semantics**: for each mechanism, what error does a refused write
     produce (EPERM vs EACCES) and is it distinguishable from an ordinary
     permission error? This decides M3's provenance floor.
  5. **`allow-ports` mapping**: can loopback-only outbound port restriction be
     expressed on Linux with the closed vocabulary, or must it degrade to
     UNVERIFIED with a named cause (OQ-2)?
- Output a written decision: **which mechanism A2/A3 build on**, with the measured
  evidence lines, or an explicit "none viable — revise plan" outcome.

## Out-of-scope

- Writing the production containment implementation (that is A2).
- Deciding the network vocabulary (already decided: closed enum, cross-platform).
- Any `src/belay/` change to verdict/trace semantics.

## Acceptance criteria (test-first)

1. A CI job named e.g. `spike-linux` (or a step in the ubuntu job) runs on
   `ubuntu-latest` and emits a **machine-readable probe result** (JSON) covering
   the five probes above — this job is the test that fails until the probe script
   exists and runs.
2. Every probe either measures a value or reports `unavailable` with the reason —
   no probe may be skipped silently.
3. The probe's verdict is deterministic (same inputs → same result on the same
   runner image), asserted by a repeat run in CI.
4. The written decision (in `docs/planning/linux-sandbox/containment-spike/`) cites
   the probe output by artifact path for each claim — nothing from memory or
   literature.

## Dependencies / sequencing

First aspect. Nothing else starts before its decision lands.

## Open questions this aspect resolves

OQ-1 (mechanism), the denial-semantics half of OQ-4, and the `allow-ports` half of
OQ-2 (mapping feasibility).
