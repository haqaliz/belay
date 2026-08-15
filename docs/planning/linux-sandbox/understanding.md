# Linux sandbox slice — understanding note (Phase 2)

## What the work is really asking

Launch-checklist item **L2** (`docs/planning/launch-readiness/CHECKLIST.md:68-80`): make the
engine's containment + snapshot/restore work on Linux, with **no platform skips** in the
sandbox/replay tests on Linux CI, and an honest Linux section in `THREAT_MODEL.md`. This is
the C2 second slice — the moment "the abstraction is earned by the second" was designed for
(`docs/technical/CAPABILITY_ROADMAP.md:162-165`).

L3 (Docker), L4 (PyPI), L5 (cross-platform CI) all block on it. Phase-1 gate needs ≥3
external self-hosters; a Linux-hosted user cannot run Belay at all today.

## What the dig found (code beats prose)

1. **The "sandbox seam" is a doc concept, not a class.** There is no `Sandbox` protocol in
   `src/belay/sandbox/` today — `__init__.py` is an 82-byte docstring. The real seam is three
   `UnsupportedPlatform` raise points plus one probe:
   - `seatbelt.py:373-379` — `run()` raises off darwin ("cannot contain anything on…")
   - `launch.py:200-206` — `contained()` raises off darwin (the proxy's gate)
   - `clone.py:141-149` — `_require_darwin()` raises (snapshot/restore)
   - `ClonefileBackend.capabilities()` (`substrate.py:317-343`) — the one **probed** seam
     (xattrs branch already keyed on `os.listxattr`, which exists on Linux).
   The Linux slice must **create** the protocol the docs describe; the abstraction is not
   designed yet and this work earns it. The card's phrase "the Sandbox seam exists"
   (`_card/issue.md:7`) is **wrong as stated** — corrected here.

2. **Snapshot backend seam already exists.** `ClonefileBackend` (`substrate.py:317-343`) with
   `name = "clonefile-apfs"` and probed `capabilities()`; `guarded_restore` refuses across
   differing capability sets (`UNRESTORABLE_CAPABILITY_MISMATCH`, `substrate.py:393-410`).
   A Linux backend plugs in with a new name + `capabilities()`; the manifest round-trip
   (`persist.py`) needs no change. **The taxonomy already names the Linux slice as owner of
   three causes** (`substrate.py:171-186`): `UNRESTORABLE_CASE_COLLISION`,
   `UNRESTORABLE_INVALID_UTF8_NAME`, `UNRESTORABLE_NORMALIZATION_COLLISION` — cross-filesystem
   restore cases that cannot exist on APFS (case-insensitive/normalizing). A test asserts every
   enum member is classified exactly once (`substrate.py:59-61`).

3. **The deciding open question is old and still open:** does `bwrap` run on stock
   `ubuntu-latest`? (`sandbox-snapshot-restore/understanding.md:95-98`: "Whether `bwrap` runs
   on stock `ubuntu-latest` is unknown and **decides the Linux story**" — Ubuntu 23.10+
   AppArmor-restricts unprivileged user namespaces). **This must be measured first**, before
   the PRD's mechanism choice. The card's own caveat: "unverified until measured."

4. **Snapshot substrate on CI:** ext4 has **no reflink** and GitHub Linux runners are ext4
   (`prd.md:244`, `THREAT_MODEL.md:308-310`). Measured fallback: plain copy ~412MB real disk
   vs 3.1MB reflink; bsdtar 50× slower. So: production can use reflink (`FICLONE`) where
   available; CI will exercise the honest fallback path. `capabilities()` already encodes this
   honesty distinction. **This is the "narrowest restorable substrate" decision: the Linux
   backend must be honest about which fidelity it provides where.**

5. **CI is macOS-only today** (`.github/workflows/ci.yml` — single `macos-latest` job; no
   ubuntu job anywhere; release builds on ubuntu without running tests). L2's DONE criterion
   forces adding the ubuntu job in this slice.

6. **Platform-gated tests:** ~21 module-level `skipif(sys.platform != "darwin")` files
   (containment, launch, proxy_containment, replay e2e, verify CLI e2e, phase0 e2e, launch
   demo, interop, corpus e2e, …) plus per-test gates. Two tricky edges:
   - `test_corpus_roundtrip.py:103-105` has the **reverse** gate — `skipif(sys.platform ==
     "darwin")` asserting the off-substrate SKIP — must be rewritten once Linux replay works.
   - Ungated tests that **hard-depend** on the darwin substrate (`test_snapshot.py`,
     `test_turn_gate.py`, `test_snapshot_persist.py`, `test_persist_relative_tree.py`,
     `test_substrate.py`) would ERROR on a Linux job today — order matters: backend first,
     then the ubuntu job.
   - `test_launch.py:29-55` asserts the raise itself (monkeypatching `sys.platform = "linux"`)
     — must be rewritten to assert the Linux path. The brief's "preserve the raise" is better
     read as: **raise on any platform with no implementation**, which is the honest contract.

7. **Denial provenance must not drift.** macOS infers denials from child stderr
   (`inferred: true, source: "child-stderr"`, EPERM marker only, `seatbelt.py:284-322`). The
   Linux record must carry the same shape; whether Linux offers a kernel source (audit) that
   would upgrade provenance is an open question — do not invent it in this slice.

8. **`gc()` and `_strip_acls` are macOS-only** (`substrate.py:446-481`: `os.chflags`,
   `/bin/chmod -R -N`) — Linux `gc()` is a plain rmtree path that is currently untested.

9. **Network policy vocabulary is SBPL-shaped** (`NETWORK_MODES = deny-all|allow-all|allow-ports`,
   `seatbelt.py:74`) because SBPL rejects per-host rules. Linux CAN express per-host — widening
   is a **trace-format semantic change** (`network_policy` record, `trace.py:60`). Decision for
   the PRD: widen now or keep the closed enum for cross-platform consistency.

10. **Replay/verify all funnel through the sandbox** (`replay/client.py:68,387` imports
    `contained`; `verify/turn.py`, `verify/result.py` (determinism re-invokes 3×),
    `verify/effect.py`), so the Linux containment path must be byte-compatible with how the
    macOS path composes (`launch.contained` yields `Contained(argv, scope, profile,
    profile_path)`; argv shape pinned in `test_launch.py:138-139`).

## Verdict-axis placement

This work touches **A1** (the sandbox is a verdict axis — the boundary that contains is the
same machinery that judges) and **A2** (replay restore runs inside the sandbox). No verdict
semantics change; the axes stay deterministic and execution-grounded. A3 is untouched. The
honesty contract (UNVERIFIED-never-PASS, raise-never-noop) is the design center of this slice.

## Contradictions flagged (not papered over)

- `_card/issue.md:7` "The Sandbox seam exists" — **false in code**; the protocol must be
  created by this work (which is precisely what the docs planned: "earned by the second").
- The brief's "preserve the raise-on-non-darwin behavior" conflicts with making Linux real on
  the two raise points; the honest re-scope is "raises on platforms with no implementation",
  and the tests asserting the linux-raise must be rewritten, not kept.
- README badge + classifier (`pyproject.toml:33` lists only MacOS) become stale the moment
  Linux works — part of the slice.

## Open questions for the PRD (Phase 3)

1. **Mechanism**: bwrap (unprivileged userns) vs Landlock (kernel, needs ~5.13+, no
   namespaces, but weaker: no network policy via Landlock itself) vs seccomp+namespaces combo.
   **Measure on stock `ubuntu-latest` first** — this decides. (Open question 4 of the C2
   understanding, `:337`.)
2. Network vocabulary: widen per-host on Linux or keep closed enum?
3. Snapshot backend: reflink-where-available + honest fallback (copy/tar) with
   `capabilities()` — is that the shape? What is the CI-substrate path?
4. Denial provenance on Linux: keep child-stderr inference (same record shape) or kernel source?
5. Scope of "no platform skips": all sandbox/replay tests, or the union that passes on both
   substrates — how much of the darwin-gated suite is genuinely substrate-independent vs
   seatbelt-specific (e.g. `test_sbpl_limits.py` pins against `sandbox-exec` itself and stays
   darwin-only by nature)?
6. `Contained` shape (`profile` field is SBPL-specific) — backend-parameterize vs. abstract.
