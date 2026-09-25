# silence-record — spec

PRD: `../prd.md` (M1, M2, S1, D-1 (a), D-2). Independent of `author-abstention`.

## Problem slice

D3 silence (the check exited 0) is invisible on `verify --json` and in the phase0 ledger,
where it is indistinguishable from "no author". `phase0 report` renders it with a sentence
that omits silence. Outcome: a sibling **`claim_silence`** record exists exactly when the
axis ran and the check exited 0; `claim` keeps meaning *an A3 verdict exists*.

## The derivation (no evaluator change)

`evaluate_claim` returns `None` with a non-`None` author **only** on exit 0
(`claims.py:277-278` is the no-author branch; every other branch returns a `Verdict`). So
at each surface: **silence ⇔ the evaluator was called ∧ it returned `None` ∧
`recorder.last_check is not None`**. A pin test locks the premise (AC 1), so the inference
can never silently rot.

## In scope

- `verify/json.py`: `claim_silence_record(check) -> dict` =
  `{"axis": "A3", "kind": "claim", "check": {"source": check.source, "exit_code": 0}}`;
  `VerifyReport.claim_silence: Optional[dict] = None`, emitted after `claim`, before
  `error`, omitted when `None`.
- `cli.py` verify: compute `claim_silence` at the existing A3 site (whole-trace, author
  configured); pass to `VerifyReport`. Text surface unchanged (already correct).
- `phase0/runner.py` + `ledger.py`: `InstanceRecord.claim_silence: Optional[dict]`,
  serialized only when set, loaded with default `None`.
- `phase0/report.py`: a silent instance renders `claim silence — the check {source!r}
  exited 0 (D3): no A3 verdict, never a PASS`; the aggregate appends `/ {n} silent (never
  PASS)` **only when n > 0**; `_CLAIM_UNRECORDED_SENTENCE` gains the missing clause (see
  AC 6).
- `tests/test_refutation_no_claim_axis.py`: the D-1 (a) amendment, and the module
  docstring updated to state the only permitted difference.
- `tests/test_coverage_surface_guard.py`: register the new render sites (S1).

## Out of scope

Status values, `claim` shape, gate, corpus (silence is never banked), interop, console.

## Acceptance criteria (tests written first)

1. **Premise pin:** over every `evaluate_claim` branch fixture with a non-`None` author,
   `result is None` ⇔ the runner's exit code was 0.
2. `verify --json` with a fake exit-0 author: `"claim" not in doc`, `doc["claim_silence"]
   == {"axis": "A3", "kind": "claim", "check": {"source": <src>, "exit_code": 0}}`. No
   author / `--no-claim-axis` / `--turn 0` / a FAIL / an UNVERIFIED claim: no
   `claim_silence` key. Key order: `…, claim?, claim_silence?, error`.
3. The pinned snapshot `tests/fixtures/verify_json_snapshot.json` is byte-identical
   (unmodified fixture).
4. **Refutation (D-1 a):** `{k: v for k, v in doc_on.items() if k != "claim_silence"} ==
   doc_off`; `doc_on["claim_silence"]["check"]["exit_code"] == 0`; `"claim_silence" not
   in doc_off`; spy counts unchanged (1 / 0). Nothing else in the module changes.
5. Ledger: round-trip preserves `claim_silence`; a ledger without the key loads with
   `None` and re-serializes byte-identically; a silent instance's disposition equals the
   no-author run's (silence never flags, never counts).
6. Report: silent instance line as above; aggregate `… / 1 silent (never PASS)`; an
   instance with neither `claim` nor `claim_silence` renders the unrecorded sentence,
   whose text now reads *"… (no claim author was configured for this run, the claim axis
   was disabled, or this ledger predates the field — a ledger written before
   `claim_silence` existed also records D3 silence this way); this is NOT a claim …"*.
   Every rendered silence line contains `never a PASS` (guard-registered).
7. Every existing assertion in `tests/test_verify_claim_surfaces.py` and
   `tests/test_phase0_claim.py` passes **unmodified** (`"claim" not in doc`, `inst.claim
   is None` still hold on silence).

## Risks

R-A (silence read as confirmation): no `status` key in the record, by construction, and
AC 6's wording on every render site. The sentence change in AC 6 alters the re-render of
old ledgers that have claim-less instances — **a deliberate text correction**, pinned in
`surface-threading` AC 5 as the only permitted difference.
