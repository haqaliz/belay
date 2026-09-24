# claim-axis-legibility — understanding (Phase 2 dig, 2026-09-25)

Source: `docs/planning/_card/issue.md` (inline brief, belay-next handoff). A follow-on slice
of shipped C8 (A3, v0.27.0; reference author v0.34.0). Three read-only agents mapped the
engine, the surfaces, and the planning history; this note is their synthesis.

## What the work really is

Two recorded observability gaps on A3, both of the shape "a reader cannot tell what the
axis did":

1. **Silence is indistinguishable from absence — but only in the machine surfaces.**
   `evaluate_claim` returns `None` for *no author* (`claims.py:277-278`) and for *the check
   exited 0* (D3 silence, `claims.py:377`). The **text** surface already separates them
   (`_emit_claim` runs only with an author, `cli.py:1196-1199`, and prints "silence — the
   check exited 0 (D3)", `cli.py:1549-1552`). The ambiguity lives in **`verify --json`**
   (`claim` key omitted in both, `json.py:99-100`), the **phase0 ledger** (`claim` `None`
   in both, `runner.py:638-662`, `ledger.py:185-195`), and one rendered **sentence**:
   `_CLAIM_UNRECORDED_SENTENCE` (`phase0/report.py:400-404`) tells an exit-0 instance "no
   claim author was configured" — its own comment (397-400) lists silence, the text omits
   it. That last one is a small **existing defect**, not only a gap.
2. **`NO_CHECK_AUTHOR` does not say why.** The reason is discarded at the **author seam**,
   before the evaluator: `SubprocessAuthor.author_check` (`author.py:100-126`) turns
   timeout/launch failure (bare `except`), non-zero exit (stderr never read), stdout cap
   (silent truncation → parse failure), malformed JSON, non-object payload, a model's
   `{"error": …}` (reason string dropped), and bad `source`/`argv` into one `None`. The
   evaluator can only say "raised {ExcType}" vs "returned no executable check"
   (`claims.py:340-353`), and even that detail is dropped by every serializer
   (`claim_record` `json.py:273-303`, `_claim_summary` `runner.py:638-660`, `claim_case`).
   The reference author exits 1 with a **named** stderr message
   (`reference_claim_author.py:431-433`, classes at 139-158) — all lost. So run 3's
   `AUDIT.md:89` ("the ledger does not record which, and nobody observed it") is
   structural, not an oversight of that run.

## Affected areas

`verify/author.py` (seam), `verify/claims.py` (evaluator, `expected` dict at 462-468 is the
additive carrier, `RecordingAuthor`, `claim_case`), `verify/json.py` (`claim_record`,
`VerifyReport.as_dict`), `cli.py` (`_emit_claim`), `phase0/runner.py` (`_claim_summary`),
`phase0/ledger.py`, `phase0/report.py` (`_claim_line`, `_claim_section`, the sentence),
`corpus/case.py` (`_validate_claim`, schema v5 — ignores extra keys). **Not touched:**
`gate/` (compares `status` only and reads `claim_record` — unaffected as long as silence
never enters `claim`), interop, triage-ledger, console (none read the claim).

## Contradictions / pins that bind the design

- **The refutation test pins the ambiguity.**
  `tests/test_refutation_no_claim_axis.py:474` asserts `doc_on == doc_off` with an exit-0
  author, and the module says *"Do not weaken this module … If a surface change breaks the
  byte-identity, the surface change is wrong."* Its own comment (line ~505) names the gap:
  *"The JSON cannot show this itself — silence omits the claim record — so the spy is the
  proof."* **Any** `--json` legibility for silence breaks this equality by definition —
  that is exactly the difference being made visible. → **the owner's call at the review
  gate** (PRD §D-1).
- `tests/test_verify_claim_surfaces.py:422` asserts `"claim" not in doc` on silence, and
  `:360` compares the FAIL record with `==`. `tests/test_phase0_claim.py:361` asserts
  `inst.claim is None` on silence.
- **Doc drift, recorded not fixed here:** the A3 PRD lists `CHECK_TIMED_OUT`
  (`claim-re-derivation-a3/prd.md:120`) but the code folded timeouts into
  `CHECK_DID_NOT_EXECUTE` (`claims.py:85-88`); STATUS and C8 match the code.
- **No closed-vocabulary guard exists for claim causes** (only a hard-coded set in a
  `manual` test, `test_reference_claim_author_live.py:71-79`).
- `live-run.md:86-88` already proposed a fix (name A3's state on the coverage line, the
  way `effect:network` names `NOT_COVERED`) and deferred it.

## Out of scope (named)

The 10/12 `CLAIM_UNCLASSIFIABLE` (classifier coverage — the belay-next alternate);
`FINAL_STATE_UNOBSERVABLE`'s four collapsed reasons (`claims.py:403-421`, same shape,
different producer — a candidate follow-up); any verdict, status, reduction, or number.
