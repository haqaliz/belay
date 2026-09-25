# author-abstention — spec

PRD: `../prd.md` (M3, M5). Sequencing: first; `surface-threading` consumes its output.

## Problem slice

`SubprocessAuthor.author_check` (`src/belay/verify/author.py:100-126`) turns eight distinct
failures into one `None`, and `evaluate_claim` (`src/belay/verify/claims.py:340-353`) can
then only say "raised X" / "returned no executable check". Outcome: every
`NO_CHECK_AUTHOR` verdict carries a **sub-cause** from a closed vocabulary in its
`expected` dict, plus a bounded one-line detail.

## In scope

- `claims.py`: the 8 `SUB_CAUSE_*` constants + `SUB_CAUSES` frozenset; a frozen
  `Abstention(sub_cause: str, detail: str)` dataclass; `RecordingAuthor.last_abstention`
  forwarding the inner author's; `evaluate_claim` writes `sub_cause` and
  `sub_cause_detail` into the `NO_CHECK_AUTHOR` `expected` dict and appends
  `" ({sub_cause}: {detail})"` to the message detail (detail omitted when empty).
- `author.py`: `SubprocessAuthor.last_abstention: Optional[Abstention]`, reset to `None`
  at the start of every call, set on every `None` return. `_parse_check` returns the
  failing shape reason alongside (private helper; public behavior unchanged).
- Detail sanitation helper: one line, printable, `≤ 200` chars (`…` suffix when cut).
- The closed-vocabulary guard test (claim `CAUSE_*` + `SUB_CAUSES`).

## Out of scope

Any surface serialization (`surface-threading`); the author timeout value; the
`CheckAuthor` protocol signature; `FINAL_STATE_UNOBSERVABLE`'s collapsed reasons.

## Acceptance criteria (tests written first)

1. `SubprocessAuthor` with a stub command per failure sets `last_abstention.sub_cause`:
   exit 1 + stderr `"x\nAuthorTimeoutError: boom\n"` → `AUTHOR_EXITED_NONZERO`, detail
   `"exit 1: AuthorTimeoutError: boom"`; `sleep` past `timeout=0.2` → `AUTHOR_TIMED_OUT`
   (detail names `0.2`); nonexistent executable → `AUTHOR_NOT_LAUNCHED`
   (`FileNotFoundError`); stdout `"not json"` → `AUTHOR_OUTPUT_MALFORMED` (`invalid
   JSON`); `[1]` → malformed (`not an object`); `{"source": 1, "argv": []}` → malformed
   (`bad source`); `{"error": "model declined"}` → `AUTHOR_REPORTED_ERROR` detail `"model
   declined"`; > 1 MiB unparseable stdout → `AUTHOR_OUTPUT_OVER_CAP`.
2. **Return values are identical to today** for every case above (`None`), and a valid
   check returns the same `Check` with `last_abstention is None`. The existing
   `tests/test_verify_author.py` passes **unmodified**.
3. `last_abstention` resets: a failing call then a succeeding call on the same instance
   leaves `None`.
4. Over-cap edge: a stdout whose first 1 MiB **parses** (valid JSON + >1 MiB trailing
   whitespace) still returns the check (today's behavior) — OVER_CAP is only named when
   the truncated payload fails to parse.
5. `evaluate_claim` with a fake author that returns `None` and exposes `last_abstention =
   Abstention("AUTHOR_TIMED_OUT", "60.0s")` → UNVERIFIED `NO_CHECK_AUTHOR`, `expected`
   holds `sub_cause`/`sub_cause_detail`; a fake **without** the attribute →
   `AUTHOR_DECLINED`, detail `""`; a raising fake → `AUTHOR_RAISED`, detail = exception
   type name. Through `RecordingAuthor` in all three.
6. Detail sanitation: newlines/control chars collapsed, 500-char stderr line → 200 chars
   ending `…`; empty stderr → detail `"exit 1"`.
7. Guard: the claim `CAUSE_*` names in `claims.__all__` equal a pinned set of 5; every
   `SUB_CAUSES` member is produced by a test in this module (the guard asserts the
   pinned set of 8 equals `SUB_CAUSES`); `sub_cause` appears **only** on
   `NO_CHECK_AUTHOR` (other causes and FAIL verdicts carry no such key — property test
   over every evaluator branch in `tests/test_verify_claims.py`'s fixtures).
8. Status never changes: every sub-cause case is `Status.UNVERIFIED`, cause
   `NO_CHECK_AUTHOR`.

## Risks

R-B (never-raises contract): recording is side-channel; the bare `except` stays, split
into `TimeoutExpired` / `OSError` / generic (generic → `AUTHOR_NOT_LAUNCHED` with the type
name — a launch-phase exception is all the `try` wraps).
