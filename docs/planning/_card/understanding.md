# Understanding — `phase0-corpus-mint`

Phase-2 dig, 2026-09-19. Four parallel agents mapped the mint harness, the corpus
banking/scoring path, the A3 claim seam, and the pre-registered gate/freeze protocol.
Everything below is cited; measured facts are marked **measured** and were produced by
running the thing, not by reading about it.

---

## 1. What the work is really asking

Not "run a mint". The brief's real ask is: **convert three shipped capabilities from
"a capability, not a result" into results, by producing real banked corpus cases.**

Three ledger entries wait on the same action:

| Entry | Quote | Source |
|---|---|---|
| A3 column | *"no real intent-drift case exists yet — the fixture is synthetic, the mint's next run fills the A3 column"* | `CHECKLIST.md:407` |
| Trajectory banking | *"the value is forward-looking: the next mint's trajectory FAILs bank"* | `CHECKLIST.md:408` |
| Recall | *"No miss has been banked, so recall remains unmeasured and precision still reads `n/a`"* | `CAPABILITY_ROADMAP.md` C6 |

**Measured baseline** (`belay corpus score`, this session): `TP 0 · FP 0 · FN 0 · TN 7 ·
precision n/a · recall n/a · coverage 1.00 · independent findings 0`.

---

## 2. Verdict-axis placement

**This unit changes no axis and must not.** It is a *measurement and banking* unit.

- **A1** — exercised (trajectory `suite-before-success-claim`; content
  `no-assertion-weakening`). Semantics untouched.
- **A2** — exercised. Untouched.
- **A3** — *filled*, not changed. A3 still can never emit PASS
  (`tests/test_verify_claims.py:333-340`).
- **Reduction** — untouched.

Any proposal to sharpen a rule so the mint produces more hits is **out of scope and
would invalidate the run** — that is fitting the detector to the measurement.

## 3. Guardrail check (`CLAUDE.md`)

| Guardrail | Status |
|---|---|
| No agent framework | ✅ `eval/minting_driver/` is eval-only, never the `belay` CLI |
| No bare LLM judge | ✅ A3's model writes a check; `contained()` execution decides by exit code (`claims.py:377-384`) |
| UNVERIFIED never PASS | ✅ preserved; this unit adds no rendering surface |
| No raw-data egress | ✅ BYOK subscription, on the owner's box |
| Corpus compounds | ✅ **this is the entire point** |
| Gets better as models improve | ✅ A3 + authored invariants |

---

## 4. Findings that change the shape of the unit

### 4.1 🔴 A mint ALONE cannot move `precision` off `n/a`

Every ingest site hardcodes `human_label="pending"` (`phase0/runner.py:459`, `:541`,
`:592`). `score()` excludes `pending` **first** (`corpus/metrics.py:219-221`), so
`tp=fp=0` and `_ratio(0,0) → None` (`:149-155`). The engine never labels its own cases
(D3); only `set_label` (`corpus/curate.py:46-146`), run by a human, can. The label trap
is enforced by a test that explicitly asserts `precision != 1.0`
(`tests/test_corpus_metrics.py:114-140`).

**Consequence:** the brief's acceptance line *"`corpus score` reports precision and
recall with real denominators"* **cannot be satisfied by minting.** It needs a second,
human step. See Q5.

### 4.2 🔴 Only 30 never-driven instances remain, and they are ~100% django+sympy

**Measured** (pool minus the union of every committed registry's real ids):

```
pool reals ................ 166
union of all registry reals 137
FRESH (never in a registry)  30   →  django 23, sympy 7
```

`selection.py:3-24` records why the stratified draw exists: *~83% of the eligible pool
is django+sympy, so a uniform draw of 50 would publish a django/sympy rate as an agent
rate.* **The residue is worse than the pool it was built to correct.**

Consequences: (a) n≥50 on fresh instances is **impossible**; (b) the stratification
that made 18.3% defensible **cannot be reproduced**; (c) re-driving an already-*banked*
instance hits `CaseExistsError`, fail-closed, no `--overwrite`
(`corpus/add.py:364-368`).

This is *survivable* only because the unit is **not a gate run** (§5).

### 4.3 🟡 The A3 column cannot be filled through the mint's `--verify` path

`eval/minting_driver/entrypoint.py:1029-1035` calls `run_batch(...)` **without
`claim_author=`**; the default is `None` (`phase0/runner.py:153`) and A3 engages only
when it is not None (`runner.py:419`). The README presents `--verify` and the printed
`belay phase0 run` as equivalent (`eval/README.md:727-729`) — **they are not**: only
the printed CLI command reads `BELAY_CLAIM_AUTHOR` (`cli.py:2593`).

### 4.4 🟡 No A3 reference author exists — writing one is real scope

Nothing in `src/` authors an A3 check. Only a `python3 -c` example
(`README.md:155-161`), a manual live gate (`tests/test_verify_author_live.py`), and a
CI fake. Two reusable precedents carry the **scrub-by-absence** idiom:
`src/belay/authoring/reference_author.py:60-64, 177-190` (closest analogue) and
`eval/minting_driver/clients/claude_cli_client.py:117-121, 709-723`.
`SubprocessAuthor` passes no `env=` (`author.py:107-113`) — scrubbing is the author's
job.

### 4.5 ✅ CORRECTION — the "flag-parity gap" in the brief is NOT a defect

The brief (and my `belay-next` handoff) called the missing `phase0 run --claim-author`
*"the same defect class the parity guard exists to catch."* **Wrong.** It is a recorded
decision: the parity table declares the surface set as exactly
`{verify, gate baseline, gate check}` with the reason in-line
(`tests/test_cli_flag_parity.py:131-137`), the open question is at
`claim-re-derivation-a3/author/spec.md:53-55`, it was decided at
`.../surfaces/plan_20260902.md:19-22`, and it is **pinned by a test asserting
`phase0 run --claim-author` exits 2** (`tests/test_verify_claim_surfaces.py:202-219`).

Adding the flag would turn two guards RED and reverse a decision. **The env var needs
no flag change at all.** Corrected in `issue.md`.

### 4.6 🔴 A real intent-drift case may not be producible on demand

A3 FAILs only if the agent asserts verification in its `Done` text (classified
`VERIFICATION`, `trajectory.py:112-127`) while the final state contradicts it. This is
the shape the launch demo **could not produce**: 18 observed drives, two frontier
models, an easy bug, a hard bug and an expensive-suite lever → **zero** corrupt
successes (`launch-demo/demo-capture/DRIVES.md`).

The honest framing, borrowed from `invariant-authoring`: **a run that produces no
intent-drift case is a recorded result, not a failure of the unit.**

### 4.7 ✅ `--root` is cwd-relative — the fix is to write outside the worktree

`entrypoint.py:224-236` resolves `--root` against cwd. A mint run from this worktree
embeds `.claude/worktrees/feat-phase0-corpus-mint/…` in every manifest `source_root`,
reproducing **the exact defect repaired at the start of this session** (three missing
symlinks; 1,344 dead path references; **measured** broken until restored).

**Decision: pin `--root` to an absolute path under `~/dev/at/holder/belay/mint/`.**
Durable by construction, not by a stub-symlink afterwards. Never rewrite recorded paths
(**measured**: breaks replay 0/11 → 7/11).

---

## 5. The unit is NOT a gate run — and the record says exactly how to say so

The ≥50 clause counts **instances minted** and is **detector-independent**
(`PHASE0_RESULTS.md:781-784`), so no run below it reaches a gate decision. The record
explicitly permits such runs and pre-registers the disclosure:

> *"The write-up's first paragraph states what this is not — not a gate run (≥50 counts
> instances minted, detector-independent), not a precision number, not a base rate…"*
> — `under-firing-measurable/miss-measurement/spec.md:97-99`

with the reason: *"**The top risk is misreading** … Mitigated in the script, in the
metrics, and in the write-up's first paragraph — **three places, because two have not
been enough before.**"*

### But a non-gate mint is still bound by all of these

| Rule | Source |
|---|---|
| **Rule D — freeze protocol**: tooling committed first in a commit containing **no result**; run **once**; verbatim output committed next, whatever it says; a second run only if **declared** | `phase0-mint-run/prd.md:97-101`; grep-checked, `mint-run/spec.md:42` |
| **Rule A — stage gating + stop-loss**: stage 1 probe → stage 2 (controls first) → stage 3 | `phase0-mint-run/prd.md:73-79` |
| **D-3 — a FAILing control VOIDS the mint**, regardless of later adjudication | `phase0-remint/prd.md:215`; `PHASE0_RESULTS.md:42` |
| **Exposure gate (D-1 reading)**: 0/N judged on the trajectory line → STOP | `phase0-remint/prd.md:94-101` |
| **`INSTRUMENT SUSPECT` → STOP**, never a 0% | `phase0-remint/prd.md:92`; `report.py:6-12, 66-78` |
| **Audit rules S-1…S-6** — notably **S-1 the auditor is the OWNER; agents prepare evidence, never judgments**, and **S-5 every trajectory FAIL is adjudicated** | `phase0-remint/audit-and-publish/plan_20260809.md:24-29` |
| **REPRODUCIBILITY gate** — clean-checkout `belay phase0 report` byte-identical; mismatch → STOP | `mint-shell-toolset-run/audit-and-publish/spec.md:24-25` |
| **Six honesty properties** | `phase0-live-mint/prd.md:310-317` |

**S-1 is load-bearing for this unit's shape**: I can prepare evidence; I cannot
adjudicate. The human labeling pass (§4.1) is *owner work* by pre-registered rule.

---

## 6. The composition to reuse (2026-08-12, the only one measured to produce TPs)

Frozen invocation, verbatim (`mint-run/acceptance-stage3.sh:5-12`):

```sh
set -euo pipefail
export BELAY_EVAL_SERVER_ROOT="${BELAY_EVAL_SERVER_ROOT:-$PWD/eval/servers}"
uv run python -m eval.minting_driver batch \
  --root eval/mint/s6c --registry eval/instances/stage6c.json \
  --provider claude-cli --model claude-opus-5 --max-steps 20 --request-timeout 120 \
  --toolset filesystem+shell
```

Operating point (`mint-shell-toolset-run/prd.md:146-149`): `claude-opus-5`,
`--max-steps 20`, `--request-timeout 120`, macOS Seatbelt, servers pinned in
`eval/servers/`. **Local `claude` is 2.1.277; the gate run used 2.1.228** — a stated
environment difference, not a blocker.

Verify side — **`--shell-server` MUST precede `--server`** (`--server` is
`nargs=REMAINDER` and swallows everything after it; `eval/README.md:790-793`).
**Measured this session:** I hit the REMAINDER defect myself — `--server -- node …`
fails with `unrecognized arguments`.

Pinned servers **present and working** (**measured**: `s1p` replayed
`VERIFIED_CLEAN`, 0/11 UNVERIFIED).

---

## 7. Contradictions between the brief and the code, stated not papered over

1. **"`corpus score` reports precision/recall with real denominators"** — not reachable
   by minting (§4.1). Needs an owner labeling pass.
2. **"the flag-parity gap"** — not a gap; a pinned decision (§4.5). **Corrected.**
3. **"Reuse the 2026-08-12 composition … n≥50"** — the brief does not claim n≥50, but
   the composition it names *was* an n=60 gate run. The instance supply makes that
   impossible (§4.2). The unit must state its own, smaller size and its
   non-gate status.
4. **"an A3 intent-drift FAIL banks a real case"** — cannot be *promised*, only
   attempted (§4.6). Acceptance must be written so an empty A3 column is a recorded
   result, not a red test.

---

## 8. Open questions for the PRD (⛔ owner decides)

- **Q1 — Publish a violation rate at all?** Recommend **NO**. Any rate from a ~100%
  django+sympy draw is precisely the artifact the stratified draw exists to prevent.
  Report dispositions and banked-case counts; decline the rate explicitly.
- **Q2 — Mint size and registry.** 30 fresh max. Pick n, build a registry by the
  committed generator pattern, record the seed in `SEED_HISTORY` (no silent re-roll).
- **Q3 — Is the owner labeling pass in scope?** If out, precision stays `n/a` and the
  unit must say so. If in, S-1 makes it owner work, which the implementer cannot do.
- **Q4 — A3: build a reference author?** (a) write one modeled on
  `reference_author.py`, (b) thread `author_from_env()` into `run_verify`
  (`entrypoint.py:1029`), or (c) skip A3 this run and say so.
- **Q5 — Controls.** CTL-1/2/3 + CTL-4 (positive, needs `filesystem+shell`). D-3 means
  a control FAIL **voids** the run — the re-mint died exactly here.
- **Q6 — `--root` location.** Recommend absolute under `~/dev/at/holder/belay/mint/`
  (§4.7).
- **Q7 — Live spend.** Real subscription time on `claude-opus-5`. Stop-loss is Rule A.

---

## 9. Out of scope (name them, do not drift)

- Sharpening any A1/A2/A3 rule to increase hits — that is fitting to the measurement.
- Re-deriving any published number: `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
  `recall 0.00`, `3/93` stand unedited.
- Adding `--claim-author` to `phase0 run` (§4.5) unless the owner reverses a decision.
- Fixing PR #38 (separate open branch, currently RED).
- Backfilling the s6 captures — **gone**; `mint/` holds only
  `s1 s1b s1p s2 s3 live-smoke-claude-cli`.
