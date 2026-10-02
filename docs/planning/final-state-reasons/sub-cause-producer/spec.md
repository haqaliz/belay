# Spec: sub-cause-producer

**Slice:** the vocabulary and the producer. Outcome: `evaluate_claim` records which of the four
reasons applied, on the claim record's `expected`, and nothing else changes.

**In scope:** four `SUB_CAUSE_FINAL_STATE_*` constants joining `SUB_CAUSES` and `__all__`; a
pinned cause-to-sub-cause map; `_unverified` rejecting a sub-cause under the wrong cause (`Abstention` has no cause);
`_materialize_final_state` surfacing its reason; one-line <=200-char detail (reason c includes
`reply.status`/`reply.cause`).

**Out of scope:** any surface rendering; corpus recompute; classifier; timeouts.

**Acceptance (failing tests first):**
- Each of 4 reasons, driven through the real `evaluate_claim`, yields its sub-cause (a: no
  calls; b: `replay_turn` raising; c: non-REPLAYED status; d: REPLAYED with no workspace).
- Cause is still `FINAL_STATE_UNOBSERVABLE`, status UNVERIFIED, message ends "never PASS".
- Guard pins 12 sub-causes and the map; `Abstention` rejects `AUTHOR_*` under
  `FINAL_STATE_UNOBSERVABLE` and vice versa.
- Detail is one line, <=200 chars, with a multi-line exception message and an over-long one.
- Caller-supplied `workspace=` still bypasses (no sub-cause, no cause).
- `--no-claim-axis` identity unchanged.

**Dependencies:** none (first). **Risk:** Q1 and Q2 in the PRD.
