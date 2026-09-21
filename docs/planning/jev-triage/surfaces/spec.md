# Spec — aspect `surfaces`

**Problem slice:** the `belay verify` surface — flags, loop integration, output, docs.

**In scope**
- Flags on `verify` only (mirroring the pinned `--claim-author`-on-verify-only decision,
  `tests/test_verify_claim_surfaces.py:202-219`): `--triage-author CMD` (one quoted
  string, shlex-split, exit 2 on un-lexable — `cli.py:946-962` shape), `--triage-threshold
  FLOAT`, `--triage-top-n INT`, `--no-triage` (wins over env — the `--no-claim-axis`
  shape, `cli.py:947`). Env: `BELAY_TRIAGE_AUTHOR`.
- Flag-parity guard registration (`tests/test_cli_flag_parity.py:62-148,184-198`).
- The per-turn loop (`cli.py:1034-1040`): build whitelisted features per turn, call the
  triage seam, decide replay/skip via the budget machinery, construct the skipped-turn
  `TurnVerdict` (UNVERIFIED + named cause) without ever calling `verify_turn`'s replay
  for a skipped turn.
- Additive `triage` section in `--json` + a text line, **absent-never-zero** (the
  `approval` section precedent); scores recorded in shadow mode.
- Docs: README quickstart line + the honest coverage statement touch
  ("triage never adds coverage; a skipped turn is UNVERIFIED-by-budget").
- ROADMAP / CAPABILITY_ROADMAP C10 rows corrected to the provider-neutral shape (docs
  sync commit).

**Out of scope:** other surfaces (phase0/corpus/gate/interop) — later slices; the console.

**Acceptance (test-first)**
- Each flag parses exactly on `verify`, is declared in the parity guard, and is refused
  (exit 2) on every other replay-bearing surface.
- A skipped turn renders UNVERIFIED with the named cause on text and `--json`; the
  `triage` section is absent when triage is off (absent-never-zero), present when on.
- Shadow mode records scores without changing any verdict.
- `--no-triage` beats a configured env.

**Dependencies:** `triage-seam`, `budget`. **Sequencing:** fourth.

**Open questions:** none blocking.