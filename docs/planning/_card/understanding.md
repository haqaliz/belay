# Understanding — `phase0-stage3-publish`

Written after the Phase-2 dig. Everything below is grounded in files/commands actually
read or run; anything unverified is labelled.

> **Method note, stated for honesty:** the skill mandates fanning this dig out to the
> agents team. Three agents were dispatched (`dig-coverage-status`, `dig-mint-execution`,
> `dig-audit-publish`); all three idled without returning a brief, twice, including after
> an explicit nudge. The dig below was therefore performed directly in the main thread.
> The mechanism failed; the work was not skipped.

---

## 1. The headline correction to the brief

I wrote in the card that landing `verdict-coverage-status` is a sequencing nicety.
**That understates it. It is a hard prerequisite, and the reason is measured, not
theoretical.**

From the branch's own diff to `PHASE0_RESULTS.md`:

> *"Before it, a declared-false network promise dragged the whole turn to UNVERIFIED,
> which pinned **every** turn against the reference `@modelcontextprotocol/server-filesystem`
> at UNVERIFIED regardless of agent behavior (Stage 1 measured **12/12,
> `NO_VERIFIABLE_TURNS`, `INSTRUMENT SUSPECT`**)."*

The mint drives the reference filesystem server, which declares `openWorldHint: false`.
So **running Stage 3 on `master` as it stands today produces a void mint** —
`INSTRUMENT SUSPECT`, zero verifiable turns, no number. Stage 2's usable result
(2/9 flagged, 130 turns, 2 UNVERIFIED) was only obtainable *because it was run from the
coverage-status worktree*.

This also explains why Stage 2's artifacts live on that branch and nowhere else.

**Consequence:** the merge is task 1, it is not optional, and no mint may be launched
before it lands.

## 2. State of `feat/verdict-coverage-status/aliz` — green and small

- **Tests: `754 passed, 1 skipped, 1 deselected`, exit 0** (`uv run pytest -q` in
  `.claude/worktrees/feat-verdict-coverage-status`). No failures.
  (Note: `CLAUDE.md`'s "463 tests" is stale prose — worth fixing when the branch lands.)
- **Conflict surface is 5 files**, from intersecting `master...branch` with `branch...master`:
  `CLAUDE.md`, `README.md`, `docs/planning/_card/issue.md` (throwaway),
  `src/belay/cli.py`, `src/belay/replay/report.py`.
  The two doc files are prose merges; `_card/issue.md` is per-unit scratch. Only `cli.py`
  and `replay/report.py` are real code merges, and master's changes there came from
  `replay-relocation-shell` + the interop CLI wiring — different regions than the branch's
  rendering changes. **Low-to-moderate rebase risk**, not a rewrite.
- The branch touches **no** file under `src/belay/interop/` — which is the gap in §3.

## 3. ⚠️ Real gap the merge creates: interop renders a PASS with no coverage line

The branch's own honesty rule is *"the coverage boundary travels with the verdict, on
every surface"*, enforced by a test **per surface**. The C9 interop surface merged to
master **after** this branch forked, so it was never included:

- `src/belay/cli.py:1189–1259` (`_cmd_interop_correlate`) calls
  `interop_report.render(results)` and **never** touches `_VERIFY_COVERAGE`
  (`cli.py:430`) or `_emit_coverage` (`cli.py:590`).
- `src/belay/interop/attach.py:87–88` forwards `TurnVerdict.status` unchanged — so once
  `NOT_COVERED` lands, a turn whose network dimension is `NOT_COVERED` correlates and
  prints a bare **`PASS`** with no statement of what that PASS excluded.

Master's `CLAUDE.md` already names "the `NOT_COVERED` reclassification" as a *deferred*
interop follow-up — so this is known, not a surprise. But the branch's per-surface rule
turns it from "deferred" into "an inconsistency the merge itself introduces." **It must
be closed in this unit, test-first, before the mint** — it is exactly the over-claiming
failure mode this project exists to refuse.

## 4. The "re-derive from the committed ledger" contradiction — resolvable, with an honest boundary

I flagged this before the dig; it is **narrower than feared but real**.

- The ledger path is **caller-chosen**: `belay phase0 run <trace-dir> --ledger OUT.json`
  (`src/belay/cli.py:1000–1067`), written via `to_json(ledger)`. It is **not** inherently
  gitignored — pointing it at a tracked path (e.g. `docs/technical/`) commits it.
- `belay phase0 report <ledger.json>` (`cli.py:1080–1088`) is a **pure re-render**: no
  replay, no re-verification, no clock. So *the number* is genuinely re-derivable by a
  third party from the committed ledger alone.
- What is **not** re-derivable: the underlying cases. `/traces/`, `/runs/`, `/corpus/local/`,
  `/eval/mint/`, `/eval/clones/` are all gitignored (`.gitignore:18–35`) — correctly, per
  the no-raw-data-egress guardrail.

**So the acceptance property splits in two, and the write-up must say so rather than
blur it:** the *number* is publicly re-derivable from the committed ledger; the
*individual case* is reproducible only by re-running the mint. Claiming full case-level
auditability from the repo would be the exact over-claim this unit is supposed to avoid.

## 5. Practical prerequisite nobody wrote down: the clone cache is worktree-local

`eval/clones/` is **743 MB and exists only inside the `feat-verdict-coverage-status`
worktree**; it is absent from the primary checkout. It is gitignored, so it does not
travel to a new worktree. Stage 2's stated mitigation ("all seven bare clones are
pre-cached, so Stage 3 performs no clone") **only holds in that one directory**.

Options: run the mint from that worktree, or symlink/move the cache. Copying is fine
here — bare upstream mirrors are not run state, so the `belay-worktrees` "never copy
traces/corpus between worktrees" rule does not apply to them. (It *does* apply to
`/eval/mint/` and `/corpus/local/`.)

## 6. Verdict-axis placement

This unit **changes no verdict axis of its own**. It *measures* A1 + A2 as built, and
lands A2's `NOT_COVERED` sub-verdict. No A3, no LLM in the verdict path. The LLM in play
is the *minted agent under test*, which is the subject of measurement, not the judge —
consistent with the `CLAUDE.md` guardrails. No agent-framework drift: the minting driver
is eval-only and explicitly not a product surface.

## 7. Open questions for the interview (cannot be resolved from files)

1. **Scale/cost.** Stage 3 is ~65–70 instances; django+sympy are 58 of 65; one sympy
   instance ran ~15 min / 20 turns. Wall-clock plausibly **10–20+ hours** and a real BYOK
   spend. Who runs it, on whose key, and is there an abort threshold? The PRD notes there
   is currently **no abort threshold** and that this needs sign-off
   (`phase0-mint-execution/prd.md:308`).
2. **Does the corrupt-success subset tally need to be built?** Stage 2 requires reporting
   the raw A1 rate and the corrupt-success subset separately. Whether the corpus label
   vocabulary supports that dimension today is **not yet established** — I could not
   confirm it before writing this note, and it is the first thing the plan must settle.
3. **Re-mint Stage 1 first?** `CLAUDE.md` says the next step is re-minting the Stage-1
   instance to confirm the shell-relocation false positive is gone in the wild. Cheap
   (1 instance) and de-risks a 20-hour run. Recommend yes, as a gate on Stage 3.

## 8. Proposed task order

1. Land `verdict-coverage-status` (rebase, resolve 5 files, green suite, PR, merge, release).
2. Close the interop coverage-line gap, test-first (§3).
3. Settle the corrupt-success subset tally (§7.2) — build only if missing.
4. Commit pre-registered gate criteria into `PHASE0_RESULTS.md` (must precede the run).
5. Re-mint Stage 1 (1 instance) as a smoke gate.
6. Stage 3 (~65–70 incl. 3 controls), resumable.
7. Audit every flag; fill `PHASE0_RESULTS.md` with the split tally + the §4 boundary.
8. Fix the stale RUNBOOK; prune the two merged worktrees.
