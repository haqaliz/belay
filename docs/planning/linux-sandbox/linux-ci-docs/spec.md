# Aspect A4 — Linux CI + honest docs

## Problem slice

Make the DONE criteria real: an ubuntu CI job runs the suite green with the
user-confirmed gating split, the reverse gate is rewritten, and the docs stop
claiming macOS-only — with a `THREAT_MODEL.md` Linux section that states exactly
what the Linux boundary does and does not enforce.

## In-scope

- **CI (M5):** `.github/workflows/ci.yml` gains an ubuntu job running the full
  suite. Test-gating split (user-confirmed reading of "no platform skips"):
  - substrate-independent sandbox/replay tests run on **both** platforms;
  - substrate-specific tests gain Linux analogues where meaningful (written in
    A2/A3);
  - genuinely seatbelt-only tests (e.g. `test_sbpl_limits.py`, which pins against
    `sandbox-exec` itself) stay darwin-gated with a **named cause** in README.
  The reverse gate (`test_corpus_roundtrip.py:103-105`, `skipif(sys.platform ==
  "darwin")` asserting the off-substrate SKIP) is rewritten now that Linux replay
  works.
- **Docs (M6):**
  - `docs/technical/THREAT_MODEL.md`: Linux section — what is enforced (write
    scope, network vocabulary), what is not (reads scoped or not on the Linux
    substrate — a different answer than macOS must be stated, not copied), denial
    provenance (shape-identical to macOS), the new R8 surface of the Linux
    launcher path, TMPDIR/world-writable `/tmp` difference
    (`scope.py:243-246`). **No claim published before measured.**
  - `README.md`: badge, "The sandbox is macOS only" section (lines 220-221),
    platform coverage line, named-caused gates.
  - `pyproject.toml`: Linux classifier added (line 33 currently lists only MacOS).
  - `docs/planning/launch-readiness/CHECKLIST.md`: L2 marked ✅ only when its DONE
    criteria hold; `docs/planning/linux-sandbox/` final docs.

## Out-of-scope

- L3 Docker image, L4 PyPI publish, L5 full cross-platform release matrix —
  separate checklist items that this slice unblocks.
- Widening the network vocabulary; verdict/trace semantics changes.

## Acceptance criteria (test-first)

1. The ubuntu CI job is green on the full suite with the gating split above:
   zero skips except the named-caused seatbelt-only gates and any pre-existing
   non-sandbox skips.
2. Every remaining platform skip in the sandbox/replay area has a named cause in
   README (asserted by a test that scans the skip markers against the README list,
   or by the CI job's skip-report step).
3. `test_corpus_roundtrip.py:103-105` reverse gate asserts the new reality (Linux
   replay works), not the old skip.
4. `THREAT_MODEL.md` Linux section exists, and every claim in it that names a
   behavior traces to a measured artifact (acceptance run or probe output from
   A1/A2/A3) — cross-referenced, not asserted.
5. README badge/classifier no longer claim macOS-only.
6. `CHECKLIST.md` L2 shows ✅ with the DONE criteria checked off.

## Dependencies / sequencing

Last aspect: needs A2 (containment) + A3 (snapshot) green on Linux first.
