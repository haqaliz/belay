# Aspect A2 — Linux containment implementation

## Problem slice

Make the seam real and the Linux containment real: a platform dispatch replaces the
three raise points for Linux, the Linux mechanism (decided by A1) enforces the same
escape matrix as macOS, denials reach the trace with identical provenance shape,
and the network vocabulary stays closed and cross-platform.

## In-scope

- **The seam (M2):** the dispatch that today is three `UnsupportedPlatform` raises
  (`seatbelt.py:373-379`, `launch.py:200-206`, `clone.py:141-149`) becomes a
  platform-resolved implementation behind the existing call sites. **Raises are
  preserved for any platform with no implementation** (the honest re-scope:
  `unsupported` means "no implementation exists here", never "unsandboxed").
  `launch.contained`'s composition shape (`Contained(argv, scope, profile,
  profile_path)`) is preserved or backend-parameterized without breaking
  `replay/client.py:68,387` and `verify/*`.
- **Containment (M3):** the Linux implementation enforces the same escape matrix
  as the macOS profile — direct / `../` / symlink / `mv` / grandchild writes
  outside the write scope are refused, and the refusal appears as a `denial`
  record (`inferred: true, source: "child-stderr"` floor; provenance shape
  byte-identical to macOS).
- **Network (M7):** `deny-all | allow-all | allow-ports` mean the same thing on
  Linux. If the mechanism cannot express `allow-ports` within the closed
  vocabulary, it degrades to an honest UNVERIFIED with a named cause — never a
  silent widening.
- **`belay sandbox check` (S1):** probes the Linux mechanism truthfully.
- **Test rewrites (S2):** `test_launch.py:29-55` linux-raise assertions become
  linux-path assertions; argv-shape pins at `test_launch.py:138-139` become
  backend-parameterized.

## Out-of-scope

- Snapshot/restore (A3).
- CI job wiring and test-gating split (A4 — but the Linux-analogue escape-matrix
  tests are written here, gated to run on Linux by platform markers).
- Per-host network allowlists (deferred by decision).
- Upgrading denial provenance to a kernel source (N1, optional, only if A1 shows
  it is cheap and deterministic).

## Acceptance criteria (test-first)

1. The macOS escape matrix tests (direct / `../` / symlink / `mv` / grandchild;
  network deny-all with live listener) have Linux analogues that **pass on Linux**:
  a write outside scope is refused AND recorded as a denial naming the path.
2. A positive control: a write inside the scope succeeds (no false containment).
3. `launch.contained` yields a Linux argv that runs the contained command and
  blocks the same escapes; a run without a Linux implementation on a platform with
  none still raises `UnsupportedPlatform` (pinned by test).
4. The trace `denial` and `network_policy` records on Linux are shape-identical to
  macOS (field-for-field, asserted by test).
5. `belay sandbox check` reports the Linux mechanism truthfully (present /
  unavailable with cause) — never claims a boundary that is not there.
6. Deterministic, no network except local loopback listeners, runs in CI.

## Dependencies / sequencing

Needs A1's mechanism decision. A3 is independent once A1 is done (different module:
`snapshot/`); A4 needs both.

## Open questions / risks

- EPERM vs EACCES distinction on the chosen mechanism (A1 output) decides whether
  the `_DENIAL_MARKER` survives or gets a Linux-specific marker — the record
  shape stays identical either way.
- If A1 concludes no mechanism is viable on stock `ubuntu-latest`, this aspect's
  acceptance criteria are unreachable and the plan must be revised — the PRD says
  so in advance.
