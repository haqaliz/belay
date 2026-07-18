# C6 — Failure corpus (inline brief)

No GitHub issue; source is `docs/technical/CAPABILITY_ROADMAP.md` §C6 (verbatim below) plus
`docs/ROADMAP.md` Phase-0 gate. Owner: aliz. Base branch: master. This is the FIRST capability
after the C1–C5 Phase-0 gate; C1–C5 are all merged (377 tests green on master @ 5ed31f8).

## C6. Failure corpus · week 5 (from CAPABILITY_ROADMAP.md)

**Why it is moat.** Moat #2, and the one that compounds. Every caught failure becomes a
labeled, replayable case that sharpens detection over time. This is the asset a competitor
cannot clone by reading our source, and the thing that makes a better base model make Belay
*better* rather than redundant — more cases, better checks.

**What we build:**
- A corpus format: each case = trace slice + pre-state handle + expected verdict + a
  human-audited label (true positive / false positive / unverifiable).
- `belay corpus add` from any flagged run; `belay corpus run` replays the whole corpus and
  asserts the expected verdicts — i.e. **the corpus is the regression suite**. Detection
  changes that break a past case fail CI.
- Precision/recall reporting against the audited labels, so "detection improved" is a measured
  claim rather than a vibe.
- Privacy by construction: cases store what the user's own infra already holds. Nothing is
  uploaded, ever. Sharing (Phase 2+) is opt-in and pattern-level, never raw state.
- **Every subsequent capability must add cases.** A capability that catches nothing new does
  not ship.

**Acceptance (test-first):**
- A Phase-0 flagged run round-trips into a corpus case and replays to the same verdict.
- A deliberately regressed detector fails `belay corpus run` with the exact case named.
- Precision/recall computed against a fixture corpus with known labels matches hand-computed
  values.
- Deterministic, no network.

**Eval data captured:** this capability *is* the eval data. It seeds from Phase 0's audited
corpus on day 1 rather than starting empty.

**Dependencies:** C1–C5 (all merged).

## Known building blocks already in the codebase (to CONFIRM in the dig — do not trust from memory)
- C5 shipped `corrupt_success_case(verdict) -> Optional[dict]` in `src/belay/verify/invariants.py`
  as a PURE shaper documented "no persistence; C6 owns storage" — C6 is the storage/replay layer
  it was built to feed. Natural seed of a corpus case.
- Trace format + reader (`docs/technical/TRACE_FORMAT.md`, `belay.replay.reader.read_trace`),
  snapshot persist/load + pre-state handle (`belay.replay.persist`, `belay.snapshot.substrate`),
  `verify_turn` -> `TurnVerdict(status, sub_verdicts, cause)`, and the `belay verify` CLI +
  subcommand pattern in `src/belay/cli.py` (argparse subparsers, `_cmd_verify`).

## Guardrails (from CLAUDE.md)
- Harness only; no agent framework, no LLM judge. The corpus label is HUMAN-audited; the verdict
  it asserts is the deterministic engine's, never a model's opinion.
- No raw-data egress: cases stay on the user's infra; nothing uploads. Corpus dirs are already
  gitignored (`/corpus/local/` per belay-worktrees skill).
- UNVERIFIED is a first-class label, never rendered/counted as PASS. Precision/recall must treat
  unverifiable honestly, not fold it into a positive.
