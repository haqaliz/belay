# PRD: Linux sandbox slice (C2 second slice — launch checklist L2)

- **Slug:** `linux-sandbox`
- **Branch:** `feat/linux-sandbox/aliz`
- **Phase:** Phase 1 (MVP hardening + OSS launch) — the Phase-0 gate PROCEEDED (v0.19.0, 11/60 = 18.3%)
- **Capability:** C2 follow-on slice (`docs/technical/CAPABILITY_ROADMAP.md:150-189`); the abstraction-is-earned-by-the-second moment (`CAPABILITY_ROADMAP.md:162-165`)
- **Launch checklist item:** L2 (`docs/planning/launch-readiness/CHECKLIST.md:68-80`); L3/L4/L5 block on it
- **Source:** `docs/planning/_card/issue.md` (inline brief) + `docs/planning/linux-sandbox/understanding.md` (dig)

## Problem Statement

A Linux-hosted user **cannot run Belay at all** today. The sandbox (`seatbelt.py`),
the launch gate (`launch.py`) and the snapshot (`clone.py`) all raise
`UnsupportedPlatform` off darwin rather than no-op — deliberately, because a no-op
would claim a boundary that does not exist (`README.md:220-221`). The Phase-1 gate
requires ≥3 external parties to self-host; a Product Hunt audience is majority
Linux; Docker self-host (L3), PyPI install (L4) and cross-platform CI (L5) all block
on this slice.

**The challenge (asked and answered):** what happens if we don't build this? Phase 1
cannot launch — the roadmap's own gate (`ROADMAP.md:281-285`) needs external
self-hosters, and Linux is where the OSS audience lives. The failure mode of doing it
wrong is worse than not doing it: a Linux "sandbox" that claims containment it does
not enforce is the exact trust violation the project exists to prevent. That is why
the honesty contract — raise rather than no-op, UNVERIFIED-never-PASS, measured
claims only — is the design center of this slice, not a compliance item.

## Goals & Success Metrics

| Goal | Metric (DONE criteria, from CHECKLIST.md L2) |
|---|---|
| Linux containment exists | The sandbox seam has a Linux implementation (mechanism decided by spike, below) |
| Linux CI is real | Suite runs green on a Linux CI job with **no platform skips** for the substrate-independent sandbox/replay tests |
| Honest documentation | `THREAT_MODEL.md` states exactly what the Linux boundary does and does not enforce — same honesty contract as macOS; README's "macOS only" claims updated |

Secondary metrics: zero new runtime dependencies (the engine is stdlib-only —
`pyproject.toml` has zero runtime deps and that contract must survive); no verdict
semantics change (all existing PASS/FAIL verdicts unchanged on macOS); escape
attempts contained AND recorded as denials on Linux; a turn's pre-state restores
byte-identically on Linux.

## User Personas & Scenarios

- **The Linux-hosted operator** (ICP: engineers running agents unattended in
  production, on Linux servers). Today: cannot install, cannot run, cannot self-host.
  After: `pip install` and a contained run on their own box, with the same verdicts
  and the same honest coverage line.
- **The Docker self-hoster** (L3 consumer): needs a Linux image whose sandbox is the
  real thing — not "a container that can't do the core" (CHECKLIST.md L3).
- **The CI user / OSS contributor**: Linux CI must fail loudly on real regressions,
  not skip them.

## Requirements

### Must-have (each testable — test-first)

- **M1. Linux containment mechanism, measured not assumed.** A spike aspect (A1)
  measures the mechanism candidates **on a pinned runner image** (`ubuntu-24.04`,
  named in the probe artifact; `ubuntu-latest` is a moving target — 22.04 → 24.04
  already happened mid-mint) **in CI** before the implementation is committed to:
  unprivileged user-namespace availability (AppArmor restriction on Ubuntu 23.10+),
  `bwrap` installability/behavior, Landlock availability (kernel ≥5.13), and the
  **denial-semantics question** (EPERM vs EACCES from each mechanism). The probe
  records the image tag alongside the measured answers so the written decision
  cannot cite stale artifacts. The PRD commits to the honesty contract, not to a
  mechanism; the spike's measured result picks it. This is the C2 planning docs'
  open question 4 (`understanding.md:95-98, 337`), resolved by measurement.
- **M2. The seam becomes real.** Today there is no `Sandbox` protocol class — the
  "seam" is three `UnsupportedPlatform` raise points (`seatbelt.py:373-379`,
  `launch.py:200-206`, `clone.py:141-149`) plus one probed capability set
  (`ClonefileBackend.capabilities()`, `substrate.py:317-343`). The slice creates the
  platform dispatch the docs describe (one code path, backend-parameterized), with
  **raise preserved for platforms with no implementation** (the honest re-scope of
  the brief's "preserve the raise" — see understanding.md contradictions).
- **M3. Linux containment works.** The same escape matrix that holds on macOS
  (direct / `../` / symlink / `mv` / grandchild; network deny-all with live-listener
  controls) is contained on the Linux substrate, and a denied action appears in the
  trace as a `denial` record with **identical provenance shape**
  (`inferred: true, source: "child-stderr"` unless the spike finds a kernel source —
  see OQ-4; the record must not drift between platforms).
- **M4. Linux snapshot/restore is byte-identical.** A turn's pre-state restores
  byte-identically (hash-of-tree equality) on the Linux substrate. The backend
  plugs into the existing `SnapshotBackend` pattern (`ClonefileBackend`,
  `substrate.py:317-343`) with a probed `capabilities()`, and the
  capability-mismatch refusal (`guarded_restore`, `UNRESTORABLE_CAPABILITY_MISMATCH`)
  is preserved: cross-substrate restore stays refused, never guessed. The known
  ext4-no-reflink constraint (GitHub runners are ext4, `prd.md:244`) means the
  honest fallback path (copy/tar) is what CI exercises; reflink
  (`FICLONE`/overlayfs) where available. The taxonomy causes already reserved for
  this slice (`UNRESTORABLE_CASE_COLLISION`, `UNRESTORABLE_INVALID_UTF8_NAME`,
  `UNRESTORABLE_NORMALIZATION_COLLISION` — `substrate.py:171-186`) become reachable
  and classified. `gc()` gains a Linux path (no `chflags`/`chmod -N`).
- **M5. Linux CI job.** `.github/workflows/ci.yml` gains an ubuntu job. Ungated
  tests that hard-depend on the darwin substrate (`test_snapshot.py`,
  `test_turn_gate.py`, `test_snapshot_persist.py`, `test_persist_relative_tree.py`,
  `test_substrate.py`) run green on Linux once the backend exists. The
  darwin-gated suite splits: substrate-independent tests run on both platforms;
  substrate-specific tests gain **Linux analogues** where meaningful (escape
  matrix, restore fidelity, denial capture); genuinely seatbelt-only tests (e.g.
  `test_sbpl_limits.py`, which pins against `sandbox-exec` itself) stay
  darwin-gated with a **named cause** in README — the user-confirmed reading of
  L2's "no platform skips". The reverse gate (`test_corpus_roundtrip.py:103-105`,
  `skipif(sys.platform == "darwin")`) is rewritten.
- **M6. Honest Linux documentation.** `THREAT_MODEL.md` gains a Linux section
  stating exactly what the Linux boundary does and does not enforce (reads scoped
  or not, denial provenance, network vocabulary, the new R8 surface of the Linux
  launcher path, TMPDIR/world-writable `/tmp` difference). README's "macOS only"
  badge/classifier/limits section updated; `pyproject.toml` gains the Linux
  classifier. No Linux claim is published before it is measured (the 
  "unverified until measured" default).
- **M7. Closed network vocabulary, cross-platform.** `NetworkPolicy` keeps the
  closed enum `deny-all | allow-all | allow-ports` on both platforms (user-
  confirmed). The Linux implementation may differ but must mean the same thing,
  and the trace `network_policy` record stays semantically identical. Widening to
  per-host rules is deferred to its own slice (a trace-format semantic change).

### Should-have

- **S1.** `belay sandbox check` (`cli.py:285-318`) reports Linux truthfully
  (probes the Linux mechanism, not a darwin check).
- **S2.** `test_launch.py:29-55,138-139` rewritten: the linux-raise assertions
  become Linux-path assertions; argv-shape pins become backend-parameterized.

### Nice-to-have

- **N1.** Kernel-level denial source on Linux (audit) that would upgrade
  `inferred: true, source: "child-stderr"` provenance — only if the spike shows it
  is cheap and deterministic; otherwise stays a documented follow-up.

## Technical Considerations

- **Belongs to C2**, second implementation of the seam (`CAPABILITY_ROADMAP.md`).
  Dependencies all met: C1–C6 + C9 first slice shipped (v0.19.0).
- **Replay/verify funnel through the sandbox**: `replay/client.py:68,387` imports
  `contained`; `verify/turn.py`, `verify/result.py` (determinism re-invokes 3×),
  `verify/effect.py` all sit on it. The Linux `contained()` must be drop-in
  compatible with how `launch.contained` composes (`Contained(argv, scope,
  profile, profile_path)` shape).
- **Zero runtime deps must survive.** The engine is stdlib-only. A mechanism that
  needs a vendored/system binary (bwrap) is only acceptable if (a) the spike shows
  it is required, (b) the Docker path (L3) can install it, and (c) the pip path
  (L4) degrades honestly (raises with a named cause) when absent — never silently
  unsandboxed. Landlock (kernel-native, ctypes) preserves zero-dep by construction;
  this asymmetry is exactly what the spike must measure.
- **Verdict impact: A1 + A2, no semantics change.** The sandbox is a verdict axis
  (A1) and replay restore runs inside it (A2). This slice changes the substrate,
  not the verdict contract: no PASS/FAIL value may change on macOS; UNVERIFIED
  paths keep named causes; the honesty contract is the design center.
- **The macOS suite is the canary during the seam refactor.** A2 changes the
  composition shape that `replay/client.py` + `verify/*` sit on; every refactor
  commit must keep the macOS suite green (the existing darwin CI job is the
  guard). The seam refactor must never land as "Linux first, macOS later".
- **Trace format unchanged.** `network_policy` and `denial` record shapes are
  platform-stable (M3, M7).
- **Eval data captured (the moat rule).** This slice is substrate
  infrastructure, so its corpus contribution is: (a) the existing Phase-0 cases
  **replaying cross-substrate** — a banked macOS/clonefile case replaying on Linux
  is a new capability, and (b) any new `denial`-shape cases the Linux escape-matrix
  fixtures produce. The cross-substrate consequence is first-class, not implied:
  **a case captured on one substrate that replays on the other is
  `UNVERIFIED`-by-capability-mismatch until a later slice makes cross-substrate
  replay real** — a Linux Docker self-hoster (L3) should expect that, stated in
  the README coverage line. The capability-mismatch refusal is preserved, never
  loosened, and this consequence is recorded in M6's README work.

## Risks & Open Questions

- **OQ-1 (resolved by spike, A1): mechanism.** bwrap (needs unprivileged userns —
  AppArmor-restricted on Ubuntu 23.10+) vs Landlock (kernel-native, but EACCES
  semantics and filesystem-only) vs seccomp/netns composition. Decided by
  measurement on stock `ubuntu-latest`. This is the C2 docs' open question 4.
- **OQ-2 (resolved): network vocabulary.** Closed enum kept cross-platform (user-
  confirmed). How `allow-ports` maps onto Linux is a spike output; if it is
  un-expressible without widening, it degrades to UNVERIFIED with a named cause —
  never a silent widening.
- **OQ-3 (resolved): no-platform-skips reading.** Substrate-independent green +
  Linux analogues + named-caused seatbelt-only gates (user-confirmed).
- **OQ-4 (open): denial provenance on Linux.** Same child-stderr shape is the
  floor; a kernel source would upgrade it (N1). Decision must keep the record
  platform-stable.
- **OQ-5 (open): reflink vs copy in CI.** The GitHub runner (ext4) exercises the
  honest fallback; production may get `FICLONE`. `capabilities()` encodes the
  distinction. Byte-identical restore fidelity of the copy path at Phase-1
  workload sizes is unmeasured — the acceptance test is the measurement.
- **OQ-6 (open): test_launch raise tests.** Rewriting them is a semantics decision
  (raise-per-platform-without-implementation), recorded in M2/S2.
- **Risk R8 (elevated by this slice):** Belay itself is the attack surface; the
  Linux launcher path is a new R8 surface and must be threat-modeled in M6, not
  after.
- **Risk R10 (bandwidth):** this is the critical path of Phase-1 packaging
  (L3/L4/L5 block on it) — sequence the aspects so the spike de-risks the
  mechanism before any implementation is committed.

## Out of Scope

- Per-host network allowlists (deferred: trace-format semantic change; own slice).
- Docker image (L3), PyPI publish (L4), full cross-platform matrix (L5) — separate
  checklist items that *depend on* this slice.
- gVisor / firejail / full container runtimes — not needed for the boundary, and
  they violate zero-dep.
- Any change to verdict semantics, trace format, or the corpus format.
- Windows.
- Making the mint/eval path (darwin-only by design) cross-platform.

## Aspect Decomposition

| Aspect | Boundary | Status |
|---|---|---|
| **A1 · containment-spike** | Measure mechanism candidates on stock `ubuntu-latest` in CI (userns, bwrap, Landlock, EPERM/EACCES, `allow-ports` mapping). Decides M1/OQ-1. | planned in this PRD |
| **A2 · linux-containment** | The seam becomes real; Linux `contained()`/`run()` implementation; escape matrix; denial capture; closed network vocabulary; `sandbox check`. (M2, M3, M7, S1, S2) | planned in this PRD |
| **A3 · linux-snapshot** | Linux snapshot/restore backend on the `SnapshotBackend` pattern; byte-identical restore; `gc()` Linux path; taxonomy causes reachable; capability-mismatch refusal preserved. (M4) | planned in this PRD |
| **A4 · linux-ci-docs** | ubuntu CI job; test gating split + Linux analogues; reverse-gate rewrite; `THREAT_MODEL.md` Linux section; README/pyproject classifier updates. (M5, M6) | planned in this PRD |

Sequencing: A1 first (de-risks the mechanism, pinned image), then A2/A3 — with
A2's seam refactor carrying the macOS-canary guard at every commit. The A1
evidence decides whether A3 (snapshot copy-path fidelity is the riskier unknown
on ext4) precedes A2 (containment, whose risk is resolved by A1) — the tech-plan
makes that call with the spike results in hand. A4 last (needs A2+A3 green).
