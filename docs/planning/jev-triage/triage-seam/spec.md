# Spec — aspect `triage-seam`

**Problem slice:** the provider-neutral injection point. The engine must be able to ask
*some* triage command for a calibrated suspicion score per turn, without ever knowing the
model, and must do nothing when none is configured.

**In scope**
- `Triage` protocol: `triage(features) -> TriageScore | None` (None = abstain, fail-closed).
- `TriageFeatures` — typed whitelisted-derived-features payload + serializer with a
  whitelist guard (raw state / trace bytes are structurally unrepresentable).
- `TriageScore` — `{score: float, confidence: float}`, fail-closed parse.
- `NullTriage` — the default; a no-op.
- `SubprocessTriage` — mirrors `SubprocessAuthor` (`verify/author.py:77-143`): JSON in,
  JSON out, timeout, stdout cap, exit ≠ 0 / malformed / timeout ⇒ None.
- Resolution: `triage_from_env()` reading `BELAY_TRIAGE_AUTHOR`, shlex-split, unset/blank/
  un-lexable ⇒ None (`author.py:56-74` shape).

**Out of scope:** the reference author (Jev), the turn loop, budget knobs, surfaces,
refutation tests.

**Acceptance (test-first)**
- `NullTriage` returns None; never spawns anything.
- Unset / blank / un-lexable `BELAY_TRIAGE_AUTHOR` ⇒ None, no subprocess.
- `SubprocessTriage` with a stub command round-trips `{score, confidence}`.
- Malformed reply ⇒ None (abstain) — never a fabricated score.
- Timeout ⇒ None; stdout beyond cap ⇒ None.
- Serializer: every emitted key is on the whitelist; no raw bytes, no trace content —
  asserted structurally.

**Dependencies / sequencing:** none — first aspect. Provides the vocabulary the
`budget` and `surfaces` aspects consume.

**Open questions:** none blocking. `TRIAGE_TIMEOUT` value: 60 s (mirror A3), reconsider if
a turn batch needs it shorter.