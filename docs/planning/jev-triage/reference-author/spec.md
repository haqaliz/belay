# Spec — aspect `reference-author`

**Problem slice:** the first BYOK triage command — the Jev reference author — and the
proof that the seam is provider-neutral (any model = any command).

**In scope**
- `src/belay/verify/reference_triage_author.py`: reads whitelisted features from stdin,
  validates them against the whitelist (a non-whitelisted field ⇒ fail-closed error),
  POSTs to the Jev REST endpoint with the operator's `BELAY_JEV_KEY` (read by the author
  only), parses the response to `{score, confidence}` on stdout, fail-closed.
- Endpoint and model id configurable by env (`BELAY_JEV_ENDPOINT`, `BELAY_JEV_MODEL`),
  full model ids only, aliases refused (A3 precedent, `reference_claim_author.py:81`).
- Stdlib-only (urllib) — the zero-LLM guard (`tests/test_verify_zero_llm.py`) must stay
  green.
- Provider-neutrality proof: a second trivial triage command (test fixture) behaves
  identically through the seam — "laya later" is a reference author, never an engine
  change.

**Out of scope:** the exact Jev REST schema if the owner has not pinned it — the author
lands against the documented contract with a stub-verified shape; the live manual test is
the pin. Laya or any other reference author.

**Acceptance (test-first)**
- The author's constructed HTTP payload carries only whitelisted features — asserted on
  the constructed request (stub HTTP server).
- The key is read by the author from its env; the engine's constructed child env carries
  no key (engine-side assertion lives here as the honest-line pair).
- Malformed / unexpected response ⇒ fail-closed error, exit ≠ 0.
- `BELAY_JEV_ENDPOINT` absent ⇒ documented default or fail-closed error, never a guessed
  endpoint.
- The seam treats the Jev author and the trivial stub author identically.

**Dependencies:** `triage-seam` (the payload contract). **Sequencing:** second.

**Open questions:** Jev endpoint path + key header name + response schema — owner to
provide before the live manual test can run; the seam and stub-verified shape do not
block on it.