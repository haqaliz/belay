# PRD — C10. Calibrated triage seam (BYOK, optional) — slice 1: shadow mode

**Status:** prioritized next · owner demand-pull 2026-09-19 · **not started** ·
slices 2+ (calibration ledger, per-model reference authors) sequenced downstream
**Capability:** `docs/technical/CAPABILITY_ROADMAP.md` → C10 (corrected to the
provider-neutral shape by this unit).
**Supersedes:** `proposal/jev-triage` branch's Jev-named PRD — rewritten to a
model-agnostic seam per owner PS 2026-09-21.

---

## Problem

Execution-grounded replay (C3/C4) is the trustworthy verdict, and it is expensive. At
production trace volumes you cannot replay every turn. Today the only knobs are "replay
everything" (correct, costly) or coarse sampling (cheap, blind). We want a cheap,
**calibrated** way to spend the replay budget on the turns most likely to hide a violation —
without letting a cheap model anywhere near the verdict.

## Approach (guardrail-preserving, provider-neutral)

A cheap calibrated decision model (first: **Jev**, TypeSafe's "System One"; later: **laya**
or any other) **orders and samples** the replay queue and flags likely-suspect turns.

- It **orders and samples** the replay queue behind a budget knob and flags likely-suspect
  turns for the corpus.
- It **never** emits a Belay verdict, promotes anything to PASS, or downgrades a replay
  verdict. (Guardrail #2: a model may triage, only execution may decide.)
- **The seam is provider-neutral, by construction.** The engine never knows the model. The
  triage is a **subprocess command** (the A3 `SubprocessAuthor` pattern,
  `src/belay/verify/author.py:77-119`): the engine writes a JSON payload of **whitelisted
  derived features** on stdin and reads a `{score, confidence}` JSON on stdout, fail-closed.
  Any model — Jev, laya, a local model, a shell script — is one command. Jev ships as the
  **first reference author** (`reference_triage_author.py`); other models are later
  reference authors, never engine adapters. This is exactly why the engine has no HTTP
  client and no vendor import: the zero-LLM guard (`tests/test_verify_zero_llm.py`) holds.
- **BYOK, off by default.** A triage command is configured via `--triage-author CMD`
  (`belay verify`) or `BELAY_TRIAGE_AUTHOR` (mirroring `BELAY_CLAIM_AUTHOR`,
  `author.py:45`). Unset / blank / un-lexable ⇒ `None` ⇒ triage disabled, full replay,
  every verdict and exit code unchanged. **The engine never reads or forwards any API
  key** — credentials belong to the operator's command (the Jev reference author reads
  `BELAY_JEV_KEY` itself; the engine neither reads nor passes it). An owner-supplied key
  is used for local manual testing only, never for users, never committed.
- **Minimal egress.** The engine sends only **whitelisted derived features** — tool name,
  declared MCP annotations (tri-state), annotation-object presence, offered toolset, reply
  size, hashes (`hash_raw`/`hash_canonical`), turn index/seq, ordering, truncated flag,
  state-handle status, trace context ids, protocol version, `run_process` command_line.
  **Never raw state or trace bytes.** What is sent is named in the docs and **asserted on
  the constructed payload in a test**; a turn whose only useful signal would require raw
  egress is not triaged (it goes to full replay).
- **Shadow mode is the default** when a triage command is configured: replay everything,
  record the triage scores alongside, until the calibration ledger earns a tighter budget.

## Requirements

**Must**
- `Triage` seam (injectable, like the A3 author) with a `SubprocessTriage` implementation
  and a `NullTriage` default; unset ⇒ disabled, never a crash (mirror
  `author.py:56-74`).
- Replay-queue ordering/sampling by triage confidence, behind budget knobs: **confidence
  threshold and top-N-least-confident** (owner decision 2026-09-21).
- A skipped turn is **UNVERIFIED-by-budget** with a named `TRIAGE_*` cause, registered in
  the closed cause vocabulary (`src/belay/replay/report.py:69-138,152-172`) with the
  closed-vocabulary guard pattern (`tests/test_interop_attach.py:476-494`). **Never PASS.**
- Additive `triage` section in `belay verify --json` + a text line, **absent-never-zero**
  (the `approval` section precedent).
- Whitelisted derived-features payload; assertable in a test.
- **Fail-open on triage-command failure:** timeout, exit ≠ 0, or a malformed reply ⇒ the
  turn is **not** skipped — it goes to full replay. A broken triage command must never
  shrink the replay budget (accepted at the review gate, 2026-09-21).
- **Operational guardrails carried over from the A3 author:** `TRIAGE_TIMEOUT` (60 s,
  mirroring `AUTHOR_TIMEOUT`, `author.py:49`) and a 1 MiB stdout cap
  (`author.py:53`) — a hanging triage command must never hang `belay verify`.
- Flag-parity guard registration for every new flag
  (`tests/test_cli_flag_parity.py:62-148,184-198`).

**Should**
- The Jev reference author (`reference_triage_author.py`): reads the whitelisted features
  from stdin, calls the Jev REST endpoint with the operator's `BELAY_JEV_KEY` (read by the
  author only), returns `{score, confidence}` JSON, fail-closed. Model aliases refused;
  full model ids only (A3 precedent, `reference_claim_author.py:81`).
- A `manual`-marked live test for the owner's BYOK smoke check (owner-supplied key for
  local testing only; FAIL-with-instructions when the env is unset —
  `test_reference_claim_author_live.py:118-125` pattern).

**Won't (this slice)**
- **Calibration ledger** — Jev's confidence vs the replay verdict that followed. Downstream
  of the S-1 mint decision: it needs the corpus to bank **decided** per-turn cases, which
  the second corpus-mint run supplies (the instrument fix `effect-conformance-coverage`
  closed its named gate 2026-09-21; the ledger must never be built against a
  100%-UNVERIFIED column). This slice ships no ledger and saves no cost — that is the
  honest state.
- No other reference author (laya etc.) — the seam's provider-neutrality is proven by a
  stub, not by a second vendor integration.
- No verdict authority for the triage model, ever. No default-on behavior, no bundled or
  proxied key, no raw-state or trace-byte egress under any flag.
- No budget knobs on surfaces other than `belay verify` (phase0/corpus follow later,
  mirroring the pinned `--claim-author`-on-verify-only decision,
  `tests/test_verify_claim_surfaces.py:202-219`).

## Acceptance (test-first)

1. **Identity:** triage on vs off ⇒ **identical verdicts on the turns replayed** — the
   `--no-claim-axis`-style refutation (`tests/test_refutation_no_claim_axis.py` shape:
   byte-identical PASS/FAIL, anti-vacuity spy proving triage really engaged on the on-side
   and never on the off-side). A skipped turn is `UNVERIFIED`-by-budget, never PASS.
2. **Absent ⇒ no-op:** no `--triage-author` and no `BELAY_TRIAGE_AUTHOR` ⇒ triage is a
   no-op, every turn eligible for replay, **no network call and no subprocess** — asserted
   on the constructed request/env (scrubbed by absence, never `""`).
3. **Whitelist:** the payload sent to the triage command carries only the whitelisted
   derived features; a raw-state or trace-byte field never appears — asserted on the
   constructed payload.
4. **Determinism:** the triage command is stubbed — deterministic, **no network in CI**.
   A live call is `manual`-marked and owner-run (BYOK).
5. **Budget:** with a stub command, threshold and top-N each demonstrably skip exactly the
   named turns and never a PASS; shadow mode (configured command, no budget flags) replays
   everything and records scores alongside.
6. **Fail-open:** a triage command that times out, exits ≠ 0, or returns a malformed reply
   ⇒ every affected turn goes to full replay — never skipped, never PASS. Asserted with a
   deliberately broken stub.
7. **Guardrails:** the subprocess is bounded (timeout, stdout cap) — a hanging command
   cannot hang the verify run.
8. **Suite expectation:** ~2575 passing baseline; this slice grows it by ~40–60 tests; no
   published number moves (`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall
   0.00`, `3/93` stand unedited).

## Eval data captured

This slice captures **no verdict data** — nothing is skipped by default and nothing is
banked. What ships is the instrumentation the future ledger will need: per-turn triage
scores carried in the additive `triage` section, ready to be compared against the verdicts
replay produced. The **calibration ledger** (reliability curve, ECE, violations-skipped at
threshold) is slice 2 and lives downstream of the mint.

## Dependencies

C4 (a replay verdict to triage toward), C1 (the derived features), C6 (the corpus, where
the future ledger lives) — all shipped. The A3 author seam (`verify/author.py`,
`verify/claims.py:120-145`) is the pattern to mirror. The **flag-parity guard** and the
**closed cause vocabulary** are the two hard seams the new surface must register with
before it can land. The calibration-ledger half is **gated on the S-1 mint decision** (see
Won't).

## Honest limits

Triage only ever *saves cost*, never *adds coverage*: a skipped turn is
UNVERIFIED-by-budget, named as such, never PASS. Jev's calibration is a vendor claim until
the ledger measures it; until then the safe budget is **shadow mode** (replay everything,
record alongside), which is the default whenever a triage command is configured. The
engine's egress guarantee covers *its* payload to the triage command; what the operator's
command then sends to its model is the operator's contract — the reference author is
written to forward nothing but the whitelisted features, and that is asserted on *its*
constructed payload too.

## Open questions

- **Jev REST contract details** (endpoint path, key header name, request/response schema)
  for the reference author — owner to provide or the author lands against the documented
  contract with a stub-verified shape. **Owner answered 2026-09-21: REST + key; Jev
  author only; threshold + top-N.** The exact endpoint/schema is still needed before the
  live manual test can run — flagged, not blocking the seam.

## Out of scope

Anything beyond `belay verify` surfaces; the calibration ledger; per-model reference
authors beyond Jev; bundled keys; engine-side HTTP; any verdict authority for the triage
model; a shared/CI surface (Phase-2 gate demand item, unrelated).