# A1 decision — the Linux mechanism, measured on ubuntu-24.04

**Date:** 2026-08-15 · **Branch:** feat/linux-sandbox/aliz · **Run:** CI #31897452698
**Artifact:** `linux-probe-result` (actions/upload-artifact), probe_result.json
**Runner:** `ubuntu-24.04` (pinned) · **Measured kernel:** `6.17.0-1022-azure` · glibc 2.39 · x86_64

> This decision cites ONLY the CI artifact. `probe_result.json` is gitignored
> (`/probe_result.json`) precisely so a local run cannot be cited as if it were
> the pinned-image measurement. Re-run the `spike-linux` job to re-measure.

## The question the C2 planning docs left open

`docs/planning/sandbox-snapshot-restore/understanding.md:95-98`:
*"`bwrap` looks best on paper… but it needs unprivileged user namespaces, and
**Ubuntu 23.10+ restricts those via AppArmor** — and GitHub Actions runners are
Ubuntu. Whether `bwrap` runs on stock `ubuntu-latest` is unknown and decides the
Linux story."*

## Measured findings (each from the artifact)

| Probe | Status | Finding |
|---|---|---|
| `unshare_userns` | `ok` (as a measurement) | **Unprivileged user namespaces are RESTRICTED on this image.** The `unshare` binary fails: `write failed /proc/self/uid_map: Operation not permitted` — the AppArmor restriction, confirmed on `ubuntu-24.04`. |
| `bwrap` | `absent` | bubblewrap is **not installed** on the image, and its prerequisite (userns) is blocked above — the bwrap route is dead on stock runners without root + sysctl changes. |
| `landlock` | `ok` | Kernel 6.17, **ABI 7**, ruleset creation succeeds via syscalls 444-446, **network domain supported** (`LANDLOCK_RULE_NET_PORT`). Viable with zero dependencies (ctypes). |
| `denial_marker` | `ok` | Landlock's refused write yields **EACCES** (`cannot create /etc/…: Permission denied`) — NOT EPERM. The macOS `_DENIAL_MARKER = "Operation not permitted"` does not survive on Linux. |
| `allow_ports_mapping` | `not-expressible` | Landlock's net domain restricts TCP by **port only** (`LANDLOCK_ACCESS_NET_CONNECT_TCP` + `LANDLOCK_RULE_NET_PORT`); there is **no address scope**, so "loopback-only" is inexpressible. A port grant would be a *looser* boundary than the closed vocabulary claims. |

## The decision

### Mechanism: **Landlock (filesystem containment) + seccomp (network deny)**

- **Filesystem write-scope containment: Landlock.** Kernel-native (zero-dep
  preserved — the `pyproject.toml:42-43` contract survives), no userns needed
  (the one blocker bwrap hit), ABI 7 measured working on the pinned image.
  `LANDLOCK_ACCESS_FS_*` maps onto the write-scope semantics of
  `seatbelt.build_profile` (write to the granted roots, refuse elsewhere).
- **Network: seccomp for `deny-all`** (the default). Landlock's net domain can
  only *grant* by port; it cannot express "no network at all". The default
  `deny-all` needs a seccomp filter over the connect/sendto/etc. syscalls —
  which also delivers **EPERM to the child on refusal**, so the macOS-style
  marker may actually survive on the network axis.
- **`allow-all`**: no filter (or an empty grant).
- **`allow-ports`: degrades to UNVERIFIED-with-cause on Linux.** Per PRD M7 the
  closed vocabulary must mean the same thing on both platforms; landlock cannot
  express loopback-only, and a port-only grant would silently loosen the
  boundary. Honest degradation (a named-cause refusal/UNVERIFIED), never a
  silent widening. macOS keeps working `allow-ports`; Linux says so plainly.

### Denial provenance on Linux (OQ-4, resolved with a caveat)

- Filesystem denials on Linux are **EACCES**, which is the SAME text an ordinary
  `chmod` produces — the macOS distinguishability (EPERM-only) does not transfer.
- The record keeps the identical shape (`inferred: true, source:
  "child-stderr"`) — a record whose `detail` is the verbatim line, with the
  THREAT_MODEL Linux section stating the ambiguity: inside a landlock boundary,
  an EACCES is *consistent with* a denial but not *proof* of one.
- Network denials (seccomp) are EPERM — distinguishable, like macOS.
- The kernel-source upgrade (audit) stays N1 (deferred), now with a sharper
  reason: it is the only path to provable, rather than inferred, filesystem
  denials on Linux.

### Consequences for A2 / A3

- **A2 (`linux-containment`) builds landlock + seccomp** — composition details,
  argv shape and denial capture are in the A2 plan; this decision is its
  mechanism line.
- **A3 (`linux-snapshot`) is unaffected by the mechanism choice** — the snapshot
  backend lives in `snapshot/`; no constraint from landlock/seccomp recorded.
- **The macOS suite is untouched**: Seatbelt remains the darwin backend; the
  seam dispatch adds landlock+seccomp for Linux.

## What this does NOT claim

- Not measured on any other Linux image (Docker images, other distros) — only
  `ubuntu-24.04`/kernel 6.17. A Docker image (L3) may differ and must re-probe.
- Landlock ABI 7 features beyond what the probe exercised (e.g. `scoped` bits
  for unix-socket scoping) are not claimed — A2 measures what it uses.
- No containment claim yet: this is the *mechanism* decision; the boundary
  itself is A2's acceptance, measured by its own escape matrix.
