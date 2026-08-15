# Belay — Launch Readiness Checklist (Product Hunt MVP)

> Target: the roadmap's **Phase 1** ("MVP hardening + OSS / Product Hunt launch").
> The engine spine (C1–C6 + C9 slice) is shipped; these are the remaining gaps,
> re-ordered so every `belay-next` pick advances the list, and the last line is a
> **verifiable "ready to publish" gate** — not a vibe.

## How to use this checklist

1. **Start a session** with `belay-next`. The pick it returns MUST equal the first
   open (☐) item below. If it doesn't, either this checklist is stale or the pick is
   out of order — reconcile before starting the worktree, not after.
2. **Ship the item** via `belay-begin-fast`, following the repo's test-first rule.
3. **Mark it ✅ only when its DONE criteria hold** — verify, then check. Update
   `README.md` / `PHASE0_RESULTS.md` / this file in the same PR.
4. **When every ☐ is ✅ and the gate at the bottom is true** → publish.

The blocks are dependency-ordered: the number, then installability, then the launch
surface. Never start a later block while an earlier one is open — a Product Hunt
launch without the number is a feature announcement, not this product.

---

## Block 0 — Shipped (prerequisites, keep green)

- ✅ C1 capture · C2 sandbox (macOS) · C3 replay · C4 A2 · C5 A1 · C6 corpus · C9
  interop first slice · v0.17.0 shell toolset on the mint boundary. 1492 tests, zero
  runtime deps. No action — regression tests must stay green.

---

## Block A — The number (earn it before anything else)

### ✅ L1 · Run the trajectory-rule mint under the shell-offered toolset — DONE 2026-08-12

- **belay-next slug:** `mint-shell-toolset-run` — shipped, merged as
  `docs/planning/mint-shell-toolset-run/`.
- **Why first:** the roadmap launches *"on the strength of the Phase-0 number"* and
  says *"do not launch and hope."* Every prior mint was stopped by its own
  pre-registered gate; v0.17.0 re-scoped the toolset so the trajectory rule can
  actually measure. Nothing below is worth building into an unproven premise.
- **DONE =** ≥50 instances minted · ≥3 **independent** hand-audited TPs · no
  `INSTRUMENT SUSPECT` · no FAILing control · false-positive rate **stated** ·
  the number published in `docs/technical/PHASE0_RESULTS.md` and re-derivable via
  `belay phase0 report` from the committed ledger.
- **Result (all criteria met):** **60 distinct fresh non-control instances**
  (≥50) · **11 independent hand-audited TPs** (≥3) · no `INSTRUMENT SUSPECT` in any
  stage · 4/4 controls `VERIFIED_CLEAN` (no void) · FP rate **stated** (0
  adjudicated FPs of 23 trajectory FAILs; 12 unverifiable-by-seam; 171 per-turn
  FAILs are A2 verify-composition artifacts, never quoted as a violation rate).
  **The gate PROCEEDs.** Hand-audited violation rate (trajectory axis):
  **11/60 = 18.3%** — R1's quantitative form answered in the positive at n=60.
  Ledger re-renderable via `belay phase0 report` (byte-identical from clean
  checkout). Published in `PHASE0_RESULTS.md` → *The shell-toolset mint ran, and
  the gate PROCEEDs — 2026-08-12*.
- **Named caveats (read before building on the number):** the number is
  trajectory-axis only (A1 compared 0 files at n=60); the U9 verify seam caps the
  axis at claim-without-command detection; the vocabulary's coarse edge ("verified
  by reading the file back" → VERIFICATION) is recorded, not hidden; the positive
  control never exercised the axis's PASS side; the corpus holds zero banked
  trajectory cases (id-collision defect, recorded). n=60 × one model × one prompt
  is a measurement, not a base rate.
- **Next after this item:** Block B — installability.

---

## Block B — Installability (today nobody can run it)

Current state: the Linux sandbox slice has landed (macOS **and** Linux backends, suite
green on both in CI); no Docker image yet (L3), not published to PyPI (L4).

### ✅ L2 · Linux sandbox slice — DONE 2026-08-15

- **belay-next slug:** `linux-sandbox` — shipped as aspects A1 (containment spike,
  mechanism decision), A2 (Landlock + seccomp containment), A3 (copy-fidelity
  snapshot backend), A4 (ubuntu CI job + honest docs), under
  `docs/planning/linux-sandbox/`.
- **DONE criteria, checked off:**
  - [x] **The sandbox seam has a Linux implementation** — `src/belay/sandbox/linux.py`
        (Landlock filesystem write scope + seccomp network deny-all, decided by the
        measured A1 probe) and `src/belay/snapshot/linux.py` (copy-fidelity backend
        with sidecar repairs, `FICLONE` probed per directory).
  - [x] **The suite runs green on Linux CI** — the `test (Linux)` job on pinned
        ubuntu-24.04 runs the full suite: **1619 passed, 0 failed** (verified
        locally on ubuntu-24.04 + aarch64 linuxkit before first CI execution; the
        CI job is its first real run on the pinned x86_64 image).
  - [x] **No silent platform skips** — the user-confirmed gating split: substrate-
        independent tests run on both platforms, substrate-specific tests have
        Linux analogues (the A2/A3 escape matrix and fidelity round trips), and
        genuinely seatbelt-only tests (e.g. `test_sbpl_limits.py`, which pins
        against `sandbox-exec` itself) stay darwin-gated **with a named cause**.
        Enforced by `tests/test_platform_gate_named_causes.py`, which scans every
        sandbox/replay gate and requires its reason to name a cause from README's
        platform coverage table (spec criterion 2). Remaining Linux skips: 201,
        all named-caused (seatbelt-only, replay-reinvokes-seatbelt,
        linux-simulated, bsd-file-flags, darwin-acl, macos-python3-shim,
        root-environment, reflink-unavailable, collision-fixture-uncreatable).
  - [x] **`THREAT_MODEL.md` states exactly what the Linux boundary does and does not
        enforce** — the Linux section (write scope, network vocabulary, the EACCES
        provenance ambiguity, the `allow-ports` named-cause degradation, reads not
        scoped *by mechanism*, the R8 launcher surface, the TMPDIR/world-writable
        `/tmp` difference, the cross-substrate corpus consequence), every claim
        cross-referencing a measured artifact.
- **First-run findings (the point of A4's Phase 1):** the linux-gated A2/A3 tests
  had never executed on a real Linux box; the first run surfaced 11 failures, all
  fixed (see `docs/planning/linux-sandbox/linux-ci-docs/plan_20260815.md`):
  dash vs bash exit codes in the escape matrix; GNU coreutils quote-wrapped paths
  in denial parsing; the `_CONNECT` probe's socket creation outside its try; a
  `GuardedSnapshot` API misuse; `os.chflags` absent on Linux (st_flags axis,
  darwin-gated with cause); an uncaught cross-substrate `Unrestorable` in the
  replay engine (now UNVERIFIED-by-capability-mismatch, never a crash); a torture-
  tree mutation targeting the wrong symlink name.
- **Cross-substrate consequence, first-class:** a corpus case banked on
  clonefile/APFS re-verifying on Linux is SKIP with the named
  `UNRESTORABLE_CAPABILITY_MISMATCH` cause — never a guessed restore, never
  loosened (the reverse gate in `test_corpus_roundtrip.py` asserts it on both
  substrates).
- **Next after this item:** L3 — the Docker image (now packaging on top of a
  substrate that exists, no longer a blocker on a mechanism).

### ☐ L3 · Docker self-host

- **DONE =** `docker run` (and `docker compose` for the console) works on Linux +
  macOS host, per the roadmap's Phase-1 deliverable. The image runs the real sandbox
  — not a container that can't do the core.

### ☐ L4 · PyPI publish + quickstart flip

- **DONE =** `belay-harness` v0.1.0 published; `uv tool install belay-harness` /
  `pipx install` / `pip install` all work on a clean macOS and Linux box; the
  README's "until then, run from source" line is deleted; **time-to-first-verdict
  < 15 minutes** (roadmap metric) measured by a stranger following the quickstart —
  have one person time it.

### ☐ L5 · Cross-platform verification pass

- **DONE =** CI runs the full suite on Linux + macOS; any remaining platform skips
  are named with a cause in README; release checklist includes "tag → CI green on
  both platforms → publish to PyPI → build Docker image".

---

## Block C — The launch surface

### ☐ L6 · C7 live console ("watch and steer")

- **belay-next slug:** `live-console` / C7.
- **DONE =** local-first live run feed with streaming per-turn verdicts
  (PASS/WARN/FAIL/UNVERIFIED + the coverage line on every surface), per the
  CAPABILITY_ROADMAP C7 spec and its acceptance tests. This is the visual a PH
  launch demos — today it's CLI output and gifs.

### ☐ L7 · Launch demo, locked spec

- The roadmap's locked demo: one repo, one failing test, an agent told *"make the
  tests pass"* — it weakens the test and reports success (a real, documented
  behavior, not a staged trick). Belay flags the exact turn (A1 invariant, with the
  diff); shown side-by-side with a green Langfuse trace of the same run.
- **Tagline:** *"Your agent lied. Your dashboard didn't notice. Mine did."*
- **DONE =** the demo is a self-contained repo + runbook any stranger can reproduce,
  a fresh demo gif replaces the current one in the README, and the verdict is
  deterministic (A3 corroborates; never carries the demo).

---

## Block D — Optional, only after A–C are done

### ☐ L8 · C8 claim re-derivation (A3) — **cuttable, do not start early**

- **DONE =** C8 ships with A3 subordinated, `--no-claim-axis` refutation enforced by
  test, and every PASS/FAIL surviving unchanged. If the calendar slips, this is what
  slips — never Block A or B.

---

## 🚦 READY TO PUBLISH — the gate

**Publish when ALL of the following hold:**

- [ ] **L1 ✅** — the Phase-0 number is published: ≥50 instances, ≥3 independent
      hand-audited TPs, FP rate stated, no INSTRUMENT SUSPECT, ledger re-renderable
      via `belay phase0 report`.
- [ ] **L2–L5 ✅** — a stranger can install and run Belay on macOS **and** Linux in
      under 15 minutes, with `docker run` and `pip install` both real paths.
- [ ] **L6 ✅ + L7 ✅** — the console and the locked demo are the launch demo; the
      README demo assets are current.
- [ ] **≥1 external self-hoster** before launch day (roadmap Phase-1 target: ≥3) —
      someone who is not you installed it and caught a real failure on **their**
      agent; their report is a corpus case.
- [ ] **PH listing assets drafted:** tagline, the number, the demo gif, the honest
      coverage line ("macOS+Linux sandbox; sees what crosses the MCP boundary; a
      PASS excludes the network dimension").
- [ ] **L8** — optional; absence of A3 is not a blocker, by design.

**If any item is still ☐, the launch date is not set — the item list is.** The last
check is "the gate is true," which is checkable, not a feeling.

---

## Progress log

| Date | belay-next pick | L-item | Outcome / commit |
|------|-----------------|--------|------------------|
| 2026-08-15 | `linux-sandbox` | L2 | ✅ Shipped as A1–A4; `test (Linux)` ubuntu-24.04 job green (1619 passed / 0 failed), macOS green (1795 passed / 25 named-caused skips), `THREAT_MODEL.md` Linux section written against measured artifacts, named-cause gate scan test enforced, reverse gate rewritten for cross-substrate SKIP. Uncommitted at handoff — integrator commits. |
