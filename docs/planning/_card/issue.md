# Issue / Brief — claim-re-derivation-a3

> Source: inline brief (belay-next handoff, 2026-09-02), confirmed by the owner.
> Branch: `feat/claim-re-derivation-a3/aliz` · Worktree: `.claude/worktrees/feat-claim-re-derivation-a3`
> Type: feat · No GitHub issue (slug id).

## Brief

C8, axis A3 — the last unshipped engine capability (CAPABILITY_ROADMAP.md:768-808). Dependencies C1-C7 are all met (git: v0.26.0, C1-C6 + C9 slice shipped, C7 console v0.23.0); the Phase 1->2 gate requires A3's refutation (ROADMAP.md:288) and Phase-1 Key Deliverables list it (ROADMAP.md:271). Build test-first: (1) the refutation guarantee — run the full corpus with and without `--no-claim-axis` and assert every PASS and every FAIL verdict is identical; (2) a property test that A3 cannot produce PASS for any input; (3) a synthesized check that fails to execute yields UNVERIFIED, never a guess; (4) the launch demo's "all tests pass" claim re-derived against the original suite yields exit 1 -> FAIL; (5) model calls sit behind an injectable seam and never run in CI. Caveat: R4 ("LLM judge with extra steps") is the named risk — the subordination and the `--no-claim-axis` refutation are the mitigation and must ship as tests; the harder risk is that synthesized checks must actually execute, and the live-model path is a manual gate, not CI.

## Source-of-truth references

- `docs/technical/CAPABILITY_ROADMAP.md:768-808` — C8 spec (what we build, acceptance, eval data, dependencies).
- `docs/ROADMAP.md:271` — Phase-1 Key Deliverable: "A3 shipped, subordinated, and refutable via `--no-claim-axis` (C8)".
- `docs/ROADMAP.md:288` — Phase 1 → 2 gate: "The deterministic spine holds: no shipped PASS is ever produced by A3, verified by test".
- `docs/ROADMAP.md:367` — R4 risk register entry.
- `docs/planning/launch-readiness/CHECKLIST.md:295` — L8 (C8), Block D, "cuttable, do not start early" (Blocks A–C now complete).
- `docs/planning/launch-demo/` — the demo capture the C8 acceptance (4) re-derives against.