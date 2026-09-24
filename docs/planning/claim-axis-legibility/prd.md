# claim-axis-legibility — PRD

> Unit: `feat/claim-axis-legibility/aliz`. Source: `docs/planning/_card/issue.md` (inline
> brief, belay-next 2026-09-25). Dig: `understanding.md` (this directory). A follow-on
> slice of shipped **C8** (A3 claim re-derivation, v0.27.0; reference author v0.34.0).
> **Legibility only — no verdict, status, reduction, or published number moves.**

## 1. Problem Statement

The A3 claim axis cannot say what it did, on the two surfaces a machine reads.

**(a) Silence reads as absence.** `evaluate_claim` returns `None` when no author is
configured (`claims.py:277-278`) and when the authored check exited 0 (D3 silence,
`claims.py:377`). `verify --json` omits `claim` in both (`json.py:99-100`); the phase0
ledger stores `None` in both (`runner.py:638-662`). A reader of either cannot tell
*checked and silent* from *never checked* — the collapse `NOT_COVERED` was introduced to
end on A2. The finding was recorded and deferred twice
(`phase0-corpus-mint/a3-author/live-run.md:60-88`, `docs/STATUS.md:259-263`), and it
already produces a **wrong sentence**: `belay phase0 report` tells an exit-0 instance *"no
claim author was configured"* (`phase0/report.py:400-404`; its own comment at 397-400
lists silence, the text omits it). The text surface of `verify` is already correct
(`cli.py:1196-1199`, `1549-1552`).

**(b) `NO_CHECK_AUTHOR` does not say why.** `SubprocessAuthor.author_check`
(`author.py:100-126`) collapses eight distinct failures — timeout, launch failure,
non-zero exit (stderr never read), stdout over the 1 MiB cap (silent truncation), bad
JSON, non-object payload, a model's `{"error": …}` (reason dropped), bad `source`/`argv`
— into one `None`. The reference author's named stderr message
(`reference_claim_author.py:431-433`) is lost with them. Every serializer then drops even
the evaluator's two-way detail (`json.py:273-303`, `runner.py:638-660`). **Evidence:** run
3's audit could not report why A3 abstained on both trajectory FAILs — *"The ledger does
not record which, and nobody observed it"* (`phase0-corpus-mint/audit-and-publish/AUDIT.md:89`).
The first real-data A3 measurement came back uninterpretable for this reason.

## 2. Goals & Success Metrics

- **G1.** On `verify --json` and the phase0 ledger, *axis never ran*, *axis ran and was
  silent*, and *axis produced a verdict* are three distinguishable shapes. Measured: a
  test per surface over all three, and the refutation's anti-vacuity proven **from the
  JSON itself**, not only from a spy.
- **G2.** Every `NO_CHECK_AUTHOR` carries exactly one sub-cause from a closed vocabulary,
  on every surface that shows the cause. Measured: one pinned test per sub-cause through
  a fake/subprocess author; a closed-vocabulary guard.
- **G3.** Nothing a verdict reader relies on moves. Measured: every turn status,
  trajectory status, A3 status, exit code, gate comparison, and corpus outcome identical
  before/after; the `--json` snapshot (no author) byte-identical; the committed
  `cm-*.json` ledgers re-render byte-identically; no published number edited.

## 3. User Personas & Scenarios

- **The owner auditing a mint.** Run 3 had 2 `NO_CHECK_AUTHOR`. After this unit the
  ledger says e.g. `AUTHOR_EXITED_NONZERO: exit 1 — AuthorTimeoutError: …`, and the
  audit can say whether the reference author timed out, refused, or was misconfigured —
  the difference between "tune the timeout" and "the model declined".
- **An operator piping `verify --json` into CI or the console.** Today an absent `claim`
  after setting `--claim-author` could mean the env var was wrong. After: a
  `claim_silence` record proves the check ran and exited 0; absence means the axis never
  ran.

## 4. Requirements

### Must-have

- **M1 — silence record (`verify --json`).** When the check exits 0, the document carries
  a new top-level key **`claim_silence`**: `{"axis": "A3", "kind": "claim", "check":
  {"source": …, "exit_code": 0}}`. Absent in every other case (no author,
  `--no-claim-axis`, `--turn N`, and whenever `claim` is present). `claim` keeps its
  meaning exactly: *an A3 verdict exists*. Silence is **never** a status value, never in
  `claim`, never rendered as or beside PASS.
- **M2 — silence record (phase0 ledger + report).** The ledger instance gains the same
  `claim_silence` record, omitted when unset (old ledgers byte-identical). `phase0
  report`'s A3 section counts silent instances separately — *"A3 ran and was silent (the
  check exited 0, D3) on N — never a PASS"* — and `_CLAIM_UNRECORDED_SENTENCE` stops
  attributing silence to a missing author.
- **M3 — abstention sub-cause at the seam.** `SubprocessAuthor` records why it abstained
  on each call (`last_abstention`: sub-cause + bounded detail). The `CheckAuthor`
  protocol (`Optional[Check]`) is **unchanged**; the evaluator reads the reason by
  attribute when present, so third-party in-process authors keep working and read as
  `AUTHOR_DECLINED` / `AUTHOR_RAISED`. Closed vocabulary (8):

  | Sub-cause | Producer | Detail |
  |---|---|---|
  | `AUTHOR_RAISED` | in-process author raised | exception type name |
  | `AUTHOR_DECLINED` | in-process author returned `None` | — |
  | `AUTHOR_NOT_LAUNCHED` | spawn failure | exception type name |
  | `AUTHOR_TIMED_OUT` | `subprocess.TimeoutExpired` | the timeout in seconds |
  | `AUTHOR_EXITED_NONZERO` | exit ≠ 0 | exit code + stderr's last non-empty line, ≤ 200 chars |
  | `AUTHOR_OUTPUT_OVER_CAP` | stdout > 1 MiB | the cap |
  | `AUTHOR_OUTPUT_MALFORMED` | bad JSON / non-object / bad `source`/`argv` | which shape check failed |
  | `AUTHOR_REPORTED_ERROR` | payload `{"error": …}` | the error string, ≤ 200 chars |

  Timeout is split from launch failure because they call for different operator fixes
  (the `verify-tool-not-offered` three-cause precedent).
- **M4 — sub-cause on every cause surface.** The A3 UNVERIFIED `expected` dict gains
  `sub_cause` (+ `sub_cause_detail`), threaded additively into `claim_record`,
  `_claim_summary` (ledger), `claim_case` (corpus), `verify` text (`UNVERIFIED
  [NO_CHECK_AUTHOR/AUTHOR_TIMED_OUT] — never PASS`), and `phase0 report`'s `_claim_line`.
  Keys are present **only** on `NO_CHECK_AUTHOR` records — FAIL and other UNVERIFIED
  records are byte-unchanged.
- **M5 — closed-vocabulary guard.** A test pins the claim `CAUSE_*` set and the
  sub-cause set (a new value without a registered producer and renderer fails). No such
  guard exists today.
- **M6 — no verdict moves.** The whole-suite pins in G3.
- **M7 — proven through the real CLI, not only through fakes.** A darwin-gated test runs
  `belay verify --json --claim-author <stub>` on the committed demo capture with stub
  subprocess authors that (i) exit 1 with a named stderr line, (ii) sleep past a short
  injected timeout, (iii) print malformed JSON, (iv) print `{"error": "…"}`, and (v) emit
  a valid exit-0 check — asserting the sub-cause (i–iv) and `claim_silence` (v) in the
  document **and** every turn status byte-identical to the no-author run. The fakes pin
  the vocabulary; this pins that the seam actually carries it end to end (the
  L7/`--timeout` lesson: a surface's own tests could not see what running it showed).

### Should-have

- **S1.** The coverage-surface guard (`tests/test_coverage_surface_guard.py`) registers
  every new render site, so the silence record can never be rendered without its
  "never a PASS" wording.
- **S2.** A committed-ledger re-render pin: `phase0 report` over the four
  `phase0-corpus-mint/mint-run/ledgers/cm-*.json` is byte-identical before/after (no test
  exercises committed ledgers today — the claim was made by hand).

### Nice-to-have

- **N1.** Correct the A3 PRD's `CHECK_TIMED_OUT` drift (`claim-re-derivation-a3/prd.md:120`)
  with an in-place annotation quoting what it replaces.

## 5. Technical Considerations

- **Capability / axis:** C8, A3 only. Pipeline position: post-replay, the claim
  evaluation over the materialized final state. Replay determinism is untouched — no
  replay, sandbox, restore, or trace code changes.
- **Verdict impact: none by construction.** `claim_silence` lives *outside* `claim` so
  every reader that treats `claim` as a verdict record — `gate/baseline.py:107-131`,
  `gate/compare.py:247-264`, `phase0/report.py:_claim_section` (which would count a new
  status as UNVERIFIED), `corpus/case.py:_KNOWN_CLAIM_STATUSES` (which would reject it) —
  is unaffected. A3 still never emits PASS; `verdict.reduce` untouched.
- **The UNVERIFIED path:** unchanged — every sub-cause is still UNVERIFIED
  `NO_CHECK_AUTHOR`. The sub-cause refines the *reason*, never the status.
- **Corpus schema:** `sub_cause` is an optional key inside `claim`; `_validate_claim`
  already ignores extra keys. **No schema bump** — an older loader drops a detail, it does
  not misread a verdict (`case.py:74-91`'s bump rule is about misreads). Silence is never
  banked (`claim_case` returns `None` for it today and keeps doing so).
- **Detail egress:** the stderr tail and `{"error"}` string are author-produced text that
  lands in local ledgers, which mint units **commit**. Bounded to 200 chars, one line.
  Never trace/state bytes. See OQ-2.
- **Zero dependencies preserved;** stdlib only.

## 6. Decisions for the owner (review gate)

- **D-1 — the refutation test must change, and this is the decision to make.**
  `tests/test_refutation_no_claim_axis.py:474` asserts the axis-on and axis-off `verify
  --json` documents are **equal**, under *"Do not weaken this module … If a surface change
  breaks the byte-identity, the surface change is wrong."* Any `--json` legibility for
  silence breaks that equality by definition — the difference is the thing being made
  visible. Its own comment concedes the gap: *"The JSON cannot show this itself — silence
  omits the claim record — so the spy is the proof."*
  **Recommendation (a):** amend the assertion to *`doc_on` minus exactly the
  `claim_silence` key equals `doc_off`, AND `doc_on["claim_silence"]` is present with
  `exit_code 0`, AND `doc_off` has no such key*, keeping the spy. The test's stated
  purpose — every PASS and FAIL identical, A3 never leaking into a verdict — is preserved
  exactly; the change is **stronger** (it proves the axis ran from the artifact itself)
  and names the only permitted difference (the `jev-triage` identity refutation's shape:
  "byte-identical, differing only in the additive section").
  **(b)** keep the test unmodified and leave `verify --json` silent — legibility lands in
  the ledger and report only. Fails brief item 1.
- **D-2 — `claim_silence` as a sibling key** (recommended) vs a new status inside
  `claim`. The latter is counted as UNVERIFIED by `phase0 report`, rejected by the corpus
  loader, and compared by the gate — a verdict-leak in three places.

## 7. Risks & Open Questions

- **R-A** (Med/Med) — a silence record read as "A3 confirmed the claim" → PASS in
  disguise. Mitigation: no status field; the word *silence* and "never a PASS" travel on
  every rendered surface (S1); D3's rationale (a re-derived claim is not a certification,
  `CAPABILITY_ROADMAP.md:819`) quoted in the key's docstring.
- **R-B** (Low/Med) — changing `SubprocessAuthor` breaks the A3 author's "never raises"
  contract. Mitigation: recording is side-channel only; return values identical; the
  existing author tests pass unmodified.
- **R-C** (Low) — third-party authors lack `last_abstention`. Mitigation: `getattr`
  default → `AUTHOR_DECLINED`/`AUTHOR_RAISED`, which is exactly what is observable.
- **Roadmap R7 (UNVERIFIED storm):** unaffected — no new UNVERIFIED; the no-author
  absence (the PRD's R7 defense, `claim-re-derivation-a3/prd.md:128-129`) is preserved.
- **OQ-1** — should the silence count also appear on `interop export` / the console? Today
  neither reads the claim at all. Proposed: no (named, not built).
- **OQ-2** — is a 200-char stderr tail acceptable in committed ledgers? Proposed: yes,
  one line, bounded; the alternative (sub-cause only) leaves the run-3 question — *which*
  reference-author error — unanswerable.
- **R-D — a hypothesis this unit makes testable, NOT a finding.** Belay kills a
  subprocess author at `AUTHOR_TIMEOUT = 60.0` s (`author.py:49`), while the reference
  author allows its own `claude -p` child 600 s (`reference_claim_author.py:67`). Run 3's
  two `NO_CHECK_AUTHOR` *could* be Belay's own timeout killing a still-working author —
  or a refusal, or a parse failure. Nothing recorded can say which (the 184.5 s in
  `a3-author/live-run.md` is the whole test's wall, not the author's), so this PRD asserts
  nothing about run 3. **Changing the timeout is out of scope** (it changes A3 behavior);
  if the next A3-enabled run reads `AUTHOR_TIMED_OUT`, that is the next unit's evidence.
- **Effort estimate:** 3 aspects, ~1 session. Predicted test delta **+35 to +55**, stated
  so the actual is compared against it (the `jev-triage` precedent: +40–60 predicted,
  +139 actual, recorded rather than hidden).
- **OQ-3** — a stale concurrency hazard: `last_abstention` is per-instance state. `verify`
  and `phase0` evaluate A3 sequentially (one claim per trace); pinned by a test rather
  than assumed.

## 8. Out of Scope

- The 10/12 `CLAIM_UNCLASSIFIABLE` in run 3 — classifier coverage, the belay-next
  alternate. No classifier change, no new A3 firing.
- `FINAL_STATE_UNOBSERVABLE`'s four collapsed reasons (`claims.py:403-421`) — same shape,
  different producer; a named follow-up.
- Any verdict, status, reduction, exit code, or gate behavior. Any published number
  (`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`, `recall 0.00`, `3/93` stand
  unedited). Re-rendering or re-deriving run 3's A3 results (the sub-causes were never
  recorded; they cannot be recovered after the fact — stated, never inferred).
- Surfaces that do not read the claim: interop, triage-ledger, console (OQ-1).

## 9. Aspects

1. **`author-abstention`** — the sub-cause vocabulary, `SubprocessAuthor.last_abstention`,
   the evaluator reading it into the `expected` dict, the closed-vocabulary guard (M3, M5).
2. **`silence-record`** — `claim_silence` on `verify --json` and the phase0 ledger, the
   report count and the corrected sentence, the refutation amendment per D-1 (M1, M2, S1).
3. **`surface-threading`** — `sub_cause` through `claim_record`, ledger, corpus case,
   `verify` text, `phase0 report`; the committed-ledger re-render pin; the real-CLI e2e
   (M4, M6, M7, S2, N1).

Sequencing: 1 → 3 (3 threads what 1 produces); 2 is independent of 1 and can run in
parallel.
