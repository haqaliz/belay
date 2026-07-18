# Card: phase0-corpus-run (feat)

**Source:** No GitHub issue. Inline brief from the `belay-next` handoff (this session).
**Branch:** `feat/phase0-corpus-run/aliz` · **Owner:** aliz

## Brief

Build the **Phase-0 corpus runner** and publish **the number** that clears the Phase-0 gate.

Belay's engine (C1–C6) is shipped and merged: the MCP proxy trace capture (C1), the Seatbelt
sandbox + snapshot/restore (C2), deterministic replay (C3), A2 replay-verify (C4), A1
invariants (C5), and the C6 failure corpus (`belay corpus add/run/score`). But **the corpus is
empty** and **no violation-rate number has been published.** Commit `5ed31f8` says the Phase-0
gate was *"reached"* (machinery built) — not *cleared* (number published). `CLAUDE.md` names the
next step verbatim: *"run the Phase-0 corpus and publish the violation-rate number, then C7."*

The missing piece is the **runner**: drive ≥50 SWE-bench-lite instances through an open
MCP-speaking agent wired through the Belay proxy (using off-the-shelf MCP **filesystem + shell**
servers so the agent's edits actually traverse the boundary), run `belay verify` on every trace,
feed each flagged run into `belay corpus add`, hand-audit every flag, then publish a
violation-rate report **with its stated false-positive rate and UNVERIFIED rate**.

## Why this is next (from `belay-next`)

- **The gate beats the feature** (ROADMAP.md §Phase-0→1 gate). Before the number exists, the
  highest-leverage work is whatever produces it. C7 (live console) is building past an uncleared
  gate.
- **Retires R1 — the only *Fatal* risk** (ROADMAP.md risk register): "the premise is wrong —
  real agent runs contain ~no detectable violations." Every line of C7–C9 is wasted if R1 fires.
  Also exercises **R6** (do the interesting failures cross the MCP boundary) and **R7** (does
  UNVERIFIED dominate).
- **The machinery is built and waiting for input.** C6 shipped (`src/belay/corpus/`), but the
  corpus is empty. C6 without a corpus run is a regression suite with nothing to regress against.

## Load-bearing caveat (R6 / R1)

Belay v0 only verifies what crosses the **MCP boundary**. The corpus must be minted with MCP
filesystem + shell servers, and the runner needs an open agent that **routes its file/shell
actions through MCP** — not through built-in `Bash`/`Edit`. If the agent's real edits bypass the
proxy, the corpus captures nothing and the number is a **false zero**. Verify this with a single
instance before scaling to 50.

Secondary: SWE-bench-lite harnessing at ≥50 runs is real wall-clock; the audit is manual.

## Acceptance shape (test-first, from the handoff)

- A reproducible runner: a fixture SWE-bench-lite instance round-trips
  agent → proxy → trace → `corpus add` → same verdict on replay, **deterministic and offline
  against fake MCP servers**.
- ≥3 hand-audited true positives.
- A published number: violation rate **with** stated false-positive rate **and** UNVERIFIED rate,
  each UNVERIFIED traced to a named cause.
- Gate: PROCEED if the rate is reproducible and non-zero; PIVOT if it's ~0.

## Guardrails to honor (`CLAUDE.md`)

- No agent framework — we wrap whatever agent, we don't author/orchestrate it.
- No bare LLM judge — verdicts are execution-grounded; A3 never emits PASS.
- UNVERIFIED is never rendered as PASS.
- No raw-data egress — corpus cases stay under gitignored `corpus/local/`.
