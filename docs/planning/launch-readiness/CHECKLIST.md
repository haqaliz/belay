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

### ☑ L3 · Docker self-host — DONE 2026-08-20

- **DONE =** `docker run` (and `docker compose` for the console) works on Linux +
  macOS host, per the roadmap's Phase-1 deliverable. The image runs the real sandbox
  — not a container that can't do the core.
- **DONE criteria, checked off:**
  - [x] **`docker run belay <subcommand>` works, and the image runs the REAL
        sandbox** — `Dockerfile` (multi-stage, `python:3.12-slim`, non-root `belay`
        uid 1000, `ENTRYPOINT ["belay"]`). `belay sandbox check --scope /workspace`
        in the image decides the boundary by USING it: `landlock kernel ABI 8 (ok)`,
        `containment ok (a write outside the scope was refused)`, `seccomp ok (an
        AF_INET socket was refused)`. Not a container that can't do the core.
  - [x] **The whole suite runs green INSIDE the container, with every skip's cause
        machine-checked** — `tests/test_docker_inimage.py`. That one run carries the
        escape matrix (`test_linux_containment.py`) and the copy-fidelity snapshot
        round trips (`test_linux_snapshot.py`), so PRD acceptances 1–3 are one
        measurement rather than three claims. An unknown or unnamed skip cause FAILs.
  - [x] **`docker run belay` behaves identically to the installed CLI, proven by a
        capture → verify roundtrip generated IN-container** — gated proxy over real
        stdio, real snapshot, then `belay verify` re-executing against the restored
        pre-state: `turn 0 write_note PASS`, A2 replay PASS, A2 effect PASS,
        `effect:network NOT_COVERED`, 1 PASS / 0 FAIL / 0 UNVERIFIED, coverage line
        printed. The trace is made in-image and never mounted (no-raw-data-egress).
  - [x] **`docker compose` works and ships nothing broken** —
        `docker compose run --rm belay --help` reaches the same CLI surface; one
        service, and the C7 console is a COMMENT rather than a service resolving to
        an image nobody built (`tests/test_docker_compose.py`).
  - [x] **`THREAT_MODEL.md` states exactly what the container boundary does and does
        not enforce** — the container section: Landlock is the HOST kernel's and is
        not namespaced (pre-5.13 ⇒ launcher refuses, exit 2, named cause); Docker's
        seccomp profile sits UNDER Belay's and the two compose by intersection
        (measured, `Seccomp: 2` in a stock container); overlayfs ⇒
        `reflink-unavailable` ⇒ copy path; the cross-substrate corpus consequence
        bites (a macOS-banked case is SKIP inside the container); the world-writable
        `/tmp` neighbourhood is restated, not fixed; the docker.sock line stays
        closed. Every claim cites the run that produced it.
  - [x] **CI proves it on every PR** — the `docker` job on pinned `ubuntu-24.04`
        builds the image from the PR and runs all three modules inside/against it
        (run `32392451384`: docker ✅ 59s, `test (Linux)` ✅ 1638 passed / 200
        skipped, `test (macOS)` ✅, spike ✅).
- **The claim split, stated because CI cannot close it:** CI asserts the
  **Linux-host** path — on the pinned runner the container's kernel IS the runner's.
  The **macOS-host** path runs on Docker Desktop's Linux VM kernel, which CI cannot
  reach, so it ships as a **documented manual re-probe** (`docker run --rm belay
  sandbox check --scope /workspace`) with a recorded reference measurement to
  compare against, never as a CI-verified claim.
- **Findings, from running the quickstart rather than reading it:** (1) `docker build
  -t belay .` failed on any machine that had not just run `uv build` — the Dockerfile
  COPYd a prebuilt wheel and died at `lstat /dist`, and the session fixture hid it by
  building the wheel first; the build is multi-stage now and the fixture SWEEPS
  `dist/` instead. (2) `sandbox check --scope /workspace` exited 1 with "the probe
  never ran" — `WORKDIR` creates the directory as root and the image drops to
  `belay`, so the containment probe could not write inside the scope; `/workspace` is
  chowned. (3) A trace-ordering race the Linux runner caught: the proxy forwards
  before it records (deliberately — "forwarding must never wait on the recorder"), so
  a fast server can have its `tools/list` RESPONSE recorded before its own REQUEST;
  an inverted pair does not correlate, no annotation snapshot is taken, and
  effect-conformance abstains. Closed in the fixtures by waiting on the trace itself,
  with no engine change and no sleep. **Worth a follow-up on the engine side:** the
  degradation is honest (UNVERIFIED, never a false PASS) but it is a real
  coverage-loss path for any fast local server. **[Follow-up CLOSED 2026-09-05,
  `trace-ordering-fix`, v0.29.0 — the recorder now defers a response's record until
  its request's record is on disk, bounded and fail-open; `proxy.py` untouched. The
  fixture guards stay, re-scoped to snapshot-before-next-call, which is client-side by
  construction.]**
- **Deferred, deliberately, and named:** (1) the GHCR **publish** job — L3 ships
  packaging + validation; publishing is its own slice, and when it lands it should
  push the SAME image the `docker` job already validated (`RELEASING.md`). (2) A
  Docker `HEALTHCHECK` / entrypoint preflight (PRD should-have 9) — the *capability*
  ships (the probe runs in-container on every PR, and README gives the re-probe
  command), but neither directive fits a one-shot CLI image: a `HEALTHCHECK` is
  periodic liveness for a long-running container, and a preflight would probe the
  sandbox before `belay --help`, which needs none. It becomes right when **C7's
  console service** exists. **Resolved by C7 (2026-08-25):** the console service
  ships with a `healthcheck` against its `/health` endpoint — the long-running
  service the deferral was waiting for (L6).
- **Next after this item:** L4 — PyPI publish + quickstart flip.

### ✅ L4 · PyPI publish + quickstart flip — DONE 2026-08-24

- **Live-channel fact (corrected):** `belay-harness` is published to PyPI — live
  since **0.1.0** (2026-07-18); current **0.22.0**.
- **DONE =** `uv tool install belay-harness` / `pipx install` / `pip install`
  all work on a clean macOS and Linux box (CI-proven for the built artifact on both
  platforms via the `install` job; live-PyPI path measured, see the measurement
  below); the README's "until then, run from source" line is deleted (quickstart
  flipped); **time-to-first-verdict < 15 minutes** (roadmap metric) measured
  following the quickstart — see the measurement below.
- **Measurement (owner-measured n=1, degraded case per the runbook §5 — no stranger
  was available; recorded as exactly that):** **4 seconds** time-to-first-verdict.
  Environment: macOS 26.5.2, Apple Silicon, bare metal (not a VM); Python 3.11.15
  (uv-managed, inside the 3.10–3.12 band); installer uv 0.11.23,
  `uv tool install belay-harness` → `~/.local/share/uv/tools/belay-harness`;
  package belay-harness **0.22.0** from live PyPI. Stop condition per the runbook:
  `turn 0 write_note PASS` + the `effect:network NOT observed for 1/1 turn(s)`
  coverage line; `UNVERIFIED 0`. `belay sandbox check --scope` → `substrate ok`
  (darwin/seatbelt/containment-ok/clonefile-apfs). n=1 is a measurement, not a
  guarantee — recorded as such.
- **Completion contract:** work shipped — CI-proven artifact install, quickstart
  flipped; the timing clause is now measured (above), so the ✅ is checked by the
  operator per the runbook §5.

### ✅ L5 · Cross-platform verification pass — DONE 2026-08-24

- **DONE =** CI runs the full suite on Linux + macOS; any remaining platform skips
  are named with a cause in README; release checklist includes "tag → CI green on
  both platforms → publish to PyPI → build Docker image".
- **Checked 2026-08-24:** all three clauses verified against the repo — (1) the
  full suite runs on both platforms every PR (`ci.yml`: `test` on macos-latest,
  `test-linux` on pinned ubuntu-24.04, plus `install` ×2 and `docker`; README
  `#platform-coverage-macos-and-linux`); (2) platform skips name their cause and a
  gate test enforces it (`tests/test_platform_gate_named_causes.py`, README
  platform-coverage section); (3) `RELEASING.md` "Cut a release" step 2 now states
  explicitly that green covers both platforms **and** the `docker` job's in-image
  validation, closing the "build Docker image" element of the checklist line.

---

## Block C — The launch surface

### ✅ L6 · C7 live console ("watch and steer") — DONE 2026-08-24

- **belay-next slug:** `live-console` / C7.
- **DONE =** local-first live run feed with streaming per-turn verdicts
  (PASS/WARN/FAIL/UNVERIFIED + the coverage line on every surface), per the
  CAPABILITY_ROADMAP C7 spec and its acceptance tests. This is the visual a PH
  launch demos — today it's CLI output and gifs.
- **Checked 2026-08-24:** C7 acceptance met as tests — merged as PR #24
  (`3c326b9`, v0.23.0): `belay verify --json` machine contract (pinned fixture,
  one computation two renderers, text byte-identical); the Vue 3 + Vite + TS
  console (`console/`) with tail-streaming, replay-from-here, click/expand log,
  77 offline tests incl. the C7 UNVERIFIED-distinct-from-PASS correctness test
  and coverage-line-per-surface; `console:` compose service + HEALTHCHECK
  (the L3 deferral item C7 resolves) with the engine bundled in-image. L7 (the
  launch demo) is the remaining launch-surface item and uses this console.

### ☑ L7 · Launch demo — DONE 2026-09-05 (owner sign-off on the amended meaning)

- **The locked spec, as written:** one repo, one failing test, an agent told *"make the
  tests pass"* — it weakens the test and reports success. Belay flags the exact turn (A1
  invariant, with the diff); shown side-by-side with a green Langfuse trace of the same
  run. **Tagline:** *"Your agent lied. Your dashboard didn't notice. Mine did."*
- **AMENDED 2026-08-27 (owner, launch-demo PRD M2‴).** The corrupt success could not be
  produced on demand: **18 observed drives across three conditions** — two frontier
  models, an easy bug contract, a genuinely hard one, an expensive-suite lever — yielded
  **zero** (`docs/planning/launch-demo/demo-capture/DRIVES.md`). Nothing synthetic was
  substituted. The demo ships the **negative control**: a real agent fixed the bug
  honestly, ran the suite, said so, and Belay's verdict is all-green — every turn PASS
  plus the instance-level trajectory rule PASSing *"supported by 2 replayed command
  turn(s)"*. There is **no flag turn**, no Langfuse integration (C9 export-back is
  deferred), and no A3. The companion is the measured number: **11/60 = 18.3%**, with its
  decomposition. The "lied" tagline is retired for the demo's headline.
- **Built 2026-08-27/28** (`feat/launch-demo/aliz`, aspects A1–A3):
  - **A1** — `demo/` is self-contained: fixture repo, the committed capture (trace +
    snapshots + manifests) with `PROVENANCE.md`, and `demo/README.md` as the stranger's
    runbook. `tests/test_demo_capture.py` re-executes it every PR (10/10).
  - **A2** — the compose console runs the REAL API server and renders the capture. Three
    defects found by running it: `belay verify` had no `--timeout` (so every console
    verify errored), no default replay context, and a 60s subprocess wall that killed a
    300s-authorised replay. Measured after: **7/7 PASS, 0 UNVERIFIED, trajectory PASS**,
    through `POST /api/verify` with only the env defaults set.
  - **A3** — `npm run record:demo` regenerates `assets/belay-demo.gif` from the artifact;
    the README alt text, `docs/ROADMAP.md`, `CAPABILITY_ROADMAP.md:715` and
    `live-console/prd.md:12` are corrected to what shipped;
    `docs/planning/launch-demo/ph-assets.md` drafts the listing (which also clears the
    gate's *PH listing assets* row).
- **DONE =** the demo is a self-contained repo + runbook any stranger can reproduce, a
  fresh demo gif replaces the current one in the README, and the verdict is deterministic.
  **All three now hold** — under the amended meaning above.
- **☑ Ticked 2026-09-05 — OWNER SIGN-OFF, recorded.** M2‴ pre-registered that *"L7's
  DONE is re-opened with the owner before any redefinition — the checklist's L7 row is
  never marked DONE on an unreviewed meaning."* The meaning changed (a green demo, not a
  caught cheat). **The owner (aliz) reviewed the amended meaning and its evidence —
  `DRIVES.md` (18 observed drives, zero corrupt successes, the negative control), the
  committed capture with its provenance, the pinned all-green verdict, and the 11/60 =
  18.3% companion number — and signed off on 2026-09-05.** The box is now ticked on the
  owner's explicit recorded decision, not the implementer's.

---

## Block D — Optional, only after A–C are done

### ✅ L8 · C8 claim re-derivation (A3) — **cuttable, do not start early**

- **DONE =** C8 ships with A3 subordinated, `--no-claim-axis` refutation enforced by
  test, and every PASS/FAIL surviving unchanged. If the calendar slips, this is what
  slips — never Block A or B.
- **Marked DONE 2026-09-02** — C8 shipped: A3 is subordinated (downgrade-only; a
  WARN/FAIL/UNVERIFIED axis gated behind `--no-claim-axis` on `verify`, `phase0 run`
  and `corpus run`, absent-never-zero on every surface), and the refutation is
  enforced by `tests/test_refutation_no_claim_axis.py` ("this test is the company's
  positioning encoded as CI — it must never be weakened"): a corpus holding per-turn,
  trajectory and a banked claim case runs with and without the flag — every PASS and
  every FAIL verdict identical, the claim case SKIPs `CLAIM_AXIS_DISABLED` (never
  REGRESSION) — and the committed demo capture verifies to the same document with
  the axis live (D3 silence) and off.

---

## 🚦 READY TO PUBLISH — the gate

**Publish when ALL of the following hold:**

- [ ] **L1 ✅** — the Phase-0 number is published: ≥50 instances, ≥3 independent
      hand-audited TPs, FP rate stated, no INSTRUMENT SUSPECT, ledger re-renderable
      via `belay phase0 report`.
- [ ] **L2–L5 ✅** — a stranger can install and run Belay on macOS **and** Linux in
      under 15 minutes, with `docker run` and `pip install` both real paths.
- [x] **L6 ✅ + L7 ✅** — the console and the locked demo are the launch demo; the
      README demo assets are current. L7 ticked on the owner's recorded sign-off
      2026-09-05 (amended DONE meaning — the negative control).
- [ ] **≥1 external self-hoster** before launch day (roadmap Phase-1 target: ≥3) —
      someone who is not you installed it and caught a real failure on **their**
      agent; their report is a corpus case. **The package is ready** (invite +
      runbook + report template, drafted 2026-09-05 under
      `docs/planning/launch-readiness/external-self-hoster/`); the item stays ☐
      until a real external report lands with a banked corpus case id.
- [x] **PH listing assets drafted:** tagline, the number, the demo gif, the honest
      coverage line ("macOS+Linux sandbox; sees what crosses the MCP boundary; a
      PASS excludes the network dimension").
      **Drafted 2026-08-28** — `docs/planning/launch-demo/ph-assets.md`, all five
      elements plus a "claims that must NOT appear" list. **All three open
      questions answered by the owner 2026-09-05:** tagline §1's first line ships
      ("Your agent said the tests pass. Belay re-ran them."); the listing leads
      with the number, then the gif; no second FAIL gif (non-reproducible footage
      skipped deliberately). Box checked.
- [x] **L8** — C8 ships (2026-09-02): A3 subordinated, `--no-claim-axis` refutation
      enforced by `tests/test_refutation_no_claim_axis.py`, every PASS/FAIL surviving
      unchanged.

**If any item is still ☐, the launch date is not set — the item list is.** The last
check is "the gate is true," which is checkable, not a feeling.

---

## Progress log

| Date | belay-next pick | L-item | Outcome / commit |
|------|-----------------|--------|------------------|
| 2026-09-05 | `trace-ordering-fix` | Block 0 | ✅ DONE. C1 capture-fidelity fix, not a checklist item: the L3 follow-up (v0.21.0) is CLOSED. `_pump` forwards before it records, so a fast local server could have its `tools/list` RESPONSE recorded before its own REQUEST — an inverted pair does not correlate, no annotation snapshot is taken, and effect-conformance abstains for the whole run: honest, and a real coverage-loss path. Fixed in `src/belay/trace.py` **and nowhere else** — request ids are indexed under the writer's lock after the line is on disk; an s2c response parks on a `Condition` over that same lock until its key appears; bounded (2.0 s) and fail-open, so the readers still name an out-of-order pair exactly as before. No new record kind, no new field, no schema bump; `proxy.py`/`index.py`/`annotations.py`/`effect.py` untouched. **Measured** (stochastic, so quoted as observations): before, 20-run stresses of the committed fast-server fixture gave 15/20 and 12/20 runs with ≥1 broken correlation (46 and 60 broken records); after, 20/20 and 20/20 clean, 0 broken. The deterministic RED is in the unit tests, not the stress. **Honesty notes:** a COVERAGE gain, not a reclassification — `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16` stand unedited and nothing was recomputed; the residue is named (the pump calls the recorder synchronously, so a parked deferral delays the NEXT chunk on that direction — zero in the causal case, at most the deadline per orphan); snapshot-before-next-call is NOT fixed and cannot be by a recorder. 2114 → 2137 tests. |
| 2026-09-05 | — (launch-readiness pass, not a belay-next pick) | Gate | ✅ **The gate is down to ONE open item.** L7 ticked on the owner's recorded sign-off (amended DONE meaning — the negative control — reviewed against DRIVES.md, the committed capture, and the pinned verdict; the owner signs, not the implementer). PH listing assets finalized: the three owner questions answered (tagline §1 line 1; number-first then gif; no second FAIL gif — skipped for non-reproducibility). External self-hoster package drafted: invite + runbook + GitHub issue report template under `docs/planning/launch-readiness/external-self-hoster/` (gate target ≥1, roadmap ≥3). **Remaining: one real external self-hoster's report with a banked corpus case.** The gate's own rule is unchanged: *"If any item is still ☐, the launch date is not set — the item list is."* |
| 2026-09-05 | `observability-export-back` | Block 0 | ✅ DONE. C9's second aspect, not a checklist item: the export-back half of the locked Phase-1 interop deliverable (deferred by name since v0.5.0) ships as `belay interop export <otlp> <trace> [--server -- CMD…] [--out FILE] [--json]` — verdicts back into the OTLP document as span attributes plus one `belay.verdict` event, the fixture-collector round-trip (`CAPABILITY_ROADMAP.md:839`), with the coverage line and UNVERIFIED-never-PASS in-band. Merged as PR #30 (`13e2509`); v0.28.0 released. Aspects `export-engine` (one pure `build_enriched_document`; positional document-order pairing, never a silent zip; the attribute contract `belay.verdict.status/axis/cause/turn_index/coverage/sub_verdicts`; absent-never-zero; uncovered spans export UNVERIFIED + named cause; byte-stable pinned fixture), `export-cli` (document → `--out`/stdout, summary → stderr always; rc 0 on a successful export regardless of verdict contents — deliberately diverges from correlate's `_worst` gate; rc 2 preflight, rc 1 write failure; seatbelt-gated real-replay e2e), `export-docs` (deferral lines retired exactly as wide as the slice; the "Do not stage a Langfuse screenshot" prohibition survives verbatim; the stale `NOT_COVERED` deferral item corrected; launch assets untouched — owner territory). Guards: the flag-parity guard now covers `interop export` (the `--timeout` defect class, re-armed) and the platform-gate SCAN_AREA. **Honesty notes:** no verdict axis, corpus or published number moves (`11/60`, `precision 0.00`, `1/15`, `4/16` stand unedited); no live OTLP exporter, no Langfuse integration (still not built), no multi-trace aggregation (separate deferral); launch assets untouched. 2091 → 2114 tests. |
| 2026-09-02 | `claim-re-derivation-a3` | L8 | ✅ DONE. C8 — the last C-capability — ships on `feat/claim-re-derivation-a3/aliz`, merged as PR #28 (`8509d62`); v0.27.0. Aspects `evaluator` (the A3 engine: claim record → closed classifier gate → final state via final-turn replay → check under `contained`, network deny-all; exit code decides; exit 0 is silence D3; closed causes `NO_CLAIM_RECORDED`/`CLAIM_UNCLASSIFIABLE`/`NO_CHECK_AUTHOR`/`CHECK_DID_NOT_EXECUTE`/`FINAL_STATE_UNOBSERVABLE`; property test — A3 can never emit PASS), `author` (out-of-process BYOK: `BELAY_CLAIM_AUTHOR` / `--claim-author`, JSON-in/JSON-out, zero new deps, nothing leaves the box; live path is a manual gate), `demo-acceptance` (acceptance-4 re-scope D1: the demo capture stays all-green WITH A3 present — silence; a synthetic corrupt-success fixture FAILs on A3 and A1-trajectory from independent axes, A2 never FAILs on it), `corpus` (case schema v5 `claim` expected field, `{trace}-claim` namespace, recompute on the A3 dimension, `CLAIM_AXIS_DISABLED` SKIP never REGRESSION), `surfaces` (`--no-claim-axis` on verify/phase0/corpus + parity guard; text A3 line + JSON `claim_record` absent-key; `A3/...` canonical causes; phase0 A3 FAIL → `VERIFIED_FLAGGED` + banks intent-drift cases; ledger/report absent-never-zero; zero-LLM guard amended deliberately; **the refutation test** — corpus PASS/FAIL identical with and without the flag, "must never be weakened"). **Honesty notes:** A3 is dark by default (no author → absent, named on the coverage line); no real intent-drift case exists yet — the fixture is synthetic, the mint's next run fills the A3 column; `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16` stand unedited; `verdict.reduce` untouched. 2062 → 2091 tests. |
| 2026-09-01 | `corpus-trajectory-banking` | Block 0 | ✅ DONE. C6 follow-on, not a checklist item: the recorded mint defect — `phase0 run`'s trajectory ingest minted the same `trace-<instance>-turnN` id as the final turn's per-turn case, the guard refused (correctly), and zero of the shell-toolset mint's 23 trajectory FAILs (incl. all 11 hand-audited TPs) banked, so `corpus score` read `n/a` on the axis that earned the 18.3%. Merged as PR #27 (`6540942`); v0.26.0 released. Shipped as aspects `case-id-namespace` (trajectory cases mint `trace-<instance>-trajectory` — instance-level namespace, disjoint from `-turnN` by construction; one minting site in `add.py`, per-turn ids byte-identical, no schema change; RED-first: the defect shape — final-turn FAIL + trajectory FAIL — now banks both cases and recomputes MATCH), `score-denominator-proof` (labeled trajectory cases score with real denominators, `score()` unchanged; unrestorable pre-state stays unbankable fail-closed), `record-corrections` (corpus-trajectory spec corrected, AUDIT follow-up closed, STATUS.md entry, PHASE0_RESULTS pointer per its own policy). **Reclassification discipline:** `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16` stand unedited; nothing backfilled (s6 captures gone) — the value is forward-looking: the next mint's trajectory FAILs bank. 1957 → 1961 tests. |
| 2026-08-29 | `verify-tool-not-offered` | Block 0 | ✅ DONE. A2 correctness fix, not a checklist item: `belay verify` emitted a confident **FAIL** on a turn it never verified — a replay boundary that does not offer the recorded tool answers readably and identically, so DIVERGED + DETERMINISTIC scored a deterministic failure of a call that genuinely succeeded. Reproduced on the committed demo capture and fixed there (`"FAIL": 1` → `"UNVERIFIED": 1`, cause `replayed but the boundary does not offer the tool`, ~146 ms → ~69 ms). Shipped as aspects `boundary-probe` (the tools/list probe, positive evidence only, three-way fail-closed; both A2 sub-verdicts gated), `cause-and-surfaces` (three named causes on every surface incl. C9 and the console), `verify-shell-server` (the `--shell-server` parity `phase0 run` has had since `9138cea`, plus a flag-parity guard — this defect class had happened twice), `incidental-findings` (corpus recompute routing; a broadcast JSON-RPC id evicting its twin in `index.py`). **Reclassification, not improved detection** — UNVERIFIED rises by design (R7); `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16` stand unedited; the mint's 171 FAILs are historical and were NOT recomputed (the s6 captures no longer exist). A2 kept its teeth: 6 anti-overreach tests written before the abstention path, untouched, all 6 failing under an over-broad discriminator. 1851 → 1957 tests. |
| 2026-08-25 | `live-console` | L6 | ✅ DONE. Merged as PR #24 (`3c326b9`); v0.23.0 released. Aspects `console-app` (SPA: live run feed, per-turn verdicts, honesty contract — UNVERIFIED never PASS, coverage line on every surface, 77 offline tests), `verify-json` (the `--json` engine seam, pinned machine contract, text byte-identical), `compose-healthcheck` (the console as a compose service: built from this checkout, loopback `8080:8080`, `healthcheck` on `/health`, engine wheel bundled in-image, shares the engine's `/workspace` mount; the flipped `test_the_console_service_ships_with_a_healthcheck` regression-guards it; the image-build + /health test caught one CI-only defect on the pinned Linux runner — compact-JSON substring — fixed before merge). L7 (the launch demo) is the next launch-surface item and uses this console. |
| 2026-08-24 | `pypi-publish` | L5 | ✅ DONE. All three clauses verified: full suite green on macOS + Linux every PR (`test`, `test-linux`, `install`, `docker` jobs); platform skips named-caused and machine-checked (`test_platform_gate_named_causes.py`); `RELEASING.md` step 2 now states green covers both platforms + the docker job's in-image validation. |
| 2026-08-24 | `pypi-publish` | L4 | ✅ DONE. Work merged as PR #23 (`e441f7b`); v0.22.0 released (PyPI + GitHub Release live). Time-to-first-verdict measured: **4 s** (owner-measured n=1, degraded case — macOS 26.5.2 / Apple Silicon / Python 3.11.15 / uv 0.11.23 / belay-harness 0.22.0 from live PyPI; runbook stop condition met, UNVERIFIED 0; sandbox check substrate ok). Shipped: artifact-install CI job (macOS + ubuntu-24.04, wheel/sdist install, stamp, zero-dep, roundtrip), quickstart flipped to the live PyPI channel, `tests/test_quickstart_docs.py` machine-checked docs, timing runbook. L4 box checked 2026-08-24. |
| 2026-08-20 | `docker-selfhost` | L3 | ✅ Shipped as A1–A3: multi-stage `Dockerfile` (non-root, builds from a clean checkout), `docker-compose.yml` (engine only, console named not built), `tests/test_docker_{image,inimage,compose}.py`, the `docker` CI job on pinned ubuntu-24.04, `THREAT_MODEL.md` container section, README quickstart replacing the "no container yet" callout. In-image: `landlock ABI 8 (ok)` / containment ok / seccomp ok, whole suite green with every skip named, capture → verify roundtrip PASS. Three defects found by running the quickstart: prebuilt-wheel build, unwritable `/workspace`, and a trace-ordering race. GHCR publish deferred by name. |
| 2026-08-15 | `linux-sandbox` | L2 | ✅ Shipped as A1–A4; `test (Linux)` ubuntu-24.04 job green (1619 passed / 0 failed), macOS green (1795 passed / 25 named-caused skips), `THREAT_MODEL.md` Linux section written against measured artifacts, named-cause gate scan test enforced, reverse gate rewritten for cross-substrate SKIP. Uncommitted at handoff — integrator commits. |
