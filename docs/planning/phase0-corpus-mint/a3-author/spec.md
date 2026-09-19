# Aspect — `a3-author`

**Grade: deterministic.** Offline, test-first, no spend. Gates the live run.

## Problem slice

The A3 claim axis (C8) shipped 2026-09-02 and has **never run against a real agent trace**.
Two independent things block it, and both live in this aspect:

1. **No A3 reference author exists.** Nothing in `src/` authors an A3 check. What exists is
   a `python3 -c` example in `README.md:155-161`, a `manual`-marked live gate
   (`tests/test_verify_author_live.py`), and a deterministic CI fake
   (`tests/test_verify_author.py`). There is no runnable BYOK author a mint can point at.
2. **The mint's verify path cannot reach A3 at all.**
   `eval/minting_driver/entrypoint.py:1029-1035` calls `phase0_runner.run_batch(...)`
   **without `claim_author=`**. The default is `None` (`src/belay/phase0/runner.py:153`)
   and A3 engages only when it is not None (`runner.py:419`). So `--verify` can never fill
   the A3 column, regardless of `BELAY_CLAIM_AUTHOR`. The printed CLI command *can*
   (`cli.py:2593`), and `eval/README.md:727-729` wrongly presents the two as equivalent.

**Outcome:** a mint can fill the A3 column with a real verdict or a *named cause* — never
the silent `claim unrecorded` sentinel (`report.py:329-332`).

## In scope

### 1. The reference author

A `claude -p` BYOK author for the **A3 claim axis**, modeled directly on the shipped
`invariant infer` author (`src/belay/authoring/reference_author.py`) — same shape, same
guarantees, different payload.

Protocol (`src/belay/verify/author.py:1-30`, fail-closed parser at `:122-143`):

- **stdin** — `{"claim", "classification", "turns":[{"tool","seq"}], "final_state_files":[…]}`
- **stdout** — `{"source": <str>, "argv": [<str>,…]}` → a `Check`; or `{"error": …}` → `None`
- any malformed shape → `None` → `NO_CHECK_AUTHOR`. **Never raise.**

Hard requirements carried over from the precedent:

- **R6/R7 by construction:** `--tools ""` **and** `--strict-mcp-config` on the argv
  (`reference_author.py:17-20`).
- **`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` scrubbed by
  absence, never `""`** — `env.pop(name, None)` over a **copy** of `os.environ`, never
  mutating it (`reference_author.py:60-64, 177-190`). An empty value still occupies its
  precedence slot. **`ANTHROPIC_BASE_URL` is set on this box** (measured), so this is live,
  not theoretical.
- **Model aliases rejected** — full model ids only (`reference_author.py:66-69`).
- **Stdlib only.** The zero-runtime-dependency contract is non-negotiable.
- A `runner=` seam so every test is offline; the live path is `manual`-marked.

### 2. Reaching A3 from the mint

Thread `author_from_env()` into `entrypoint.run_verify` at `entrypoint.py:1029`, honoring
the lazy-`belay`-import constraint documented at `entrypoint.py:1011-1018` (importing
`belay` at module scope breaks the SDK-absent import contract).

The `--no-claim-axis` path must stay reachable and must keep A3 dark when set.

### 3. The documentation defect (OQ-4, resolved into this aspect)

`eval/README.md:727-729` claims `--verify` and the printed `belay phase0 run` are
equivalent. Correct it to state the A3 difference, or — once (2) lands — to state that they
are now equivalent *because* of it. The README must not claim an equivalence the code does
not hold.

## Out of scope

- **Adding `--claim-author` to `phase0 run`.** A recorded decision, not a gap: surface set
  declared with its reason at `tests/test_cli_flag_parity.py:131-137`, decided at
  `claim-re-derivation-a3/surfaces/plan_20260902.md:19-22`, and **pinned by a test
  asserting it exits 2** (`tests/test_verify_claim_surfaces.py:202-219`). Adding it turns
  two guards RED and reverses a decision. **Do not.**
- Any change to A3 semantics, the cause vocabulary, or the classifier.
- Prompt engineering aimed at making A3 fire more often — that is fitting the detector to
  the measurement.
- The live mint (aspect `mint-run`).

## Acceptance criteria (RED before GREEN)

| # | Criterion |
|---|---|
| A1 | Author emits a valid `{"source","argv"}` for a representative claim payload; `evaluate_claim` turns it into a `Check` (offline, `runner=` seam) |
| A2 | **Env scrub:** constructed env contains **none** of the three `ANTHROPIC_*` names — asserted on **absence**, and explicitly asserted **not** `""`. Test sets all three (incl. a non-empty `ANTHROPIC_BASE_URL`) before constructing |
| A3 | `os.environ` is **not mutated** by building the child env |
| A4 | **R6/R7:** constructed argv contains `--tools` with an empty value **and** `--strict-mcp-config` |
| A5 | A model **alias** is rejected; a full model id is accepted |
| A6 | Malformed author output — bad JSON, non-object, non-`str` source, non-`[str]` argv, non-zero exit, `{"error":…}` — each yields `None`, never an exception |
| A7 | Output over 1 MiB is truncated/refused per `author.py:53` without hanging |
| A8 | **Zero-dep:** the module imports no third-party package (AST scan, matching `tests/test_verify_zero_llm.py:26-32`) |
| A9 | `run_verify` with `BELAY_CLAIM_AUTHOR` set reaches A3 — the ledger's `claim` field is **populated** (verdict or named cause), not `None` |
| A10 | `run_verify` with `--no-claim-axis` keeps `claim` `None`, and A3 stays dark |
| A11 | **The never-PASS property still holds** — `tests/test_verify_claims.py:333-340` untouched and green |
| A12 | **The refutation still holds** — `tests/test_refutation_no_claim_axis.py` untouched and green |
| A13 | `eval/README.md`'s `--verify` equivalence claim matches the code |
| A14 | Full suite green; baseline **2540 passed / 25 skipped / 12 deselected** |
| A15 | The live author path is `manual`-marked and never in CI (`pyproject.toml:94` addopts) |

A11, A12 and A15 are **guard criteria**: they assert this aspect changed nothing it must
not. If any goes red, the aspect is wrong, not the guard.

## Dependencies & sequencing

- Depends on: nothing. Can run in parallel with `mint-registry`.
- Blocks: `mint-run` — the live run must not start until A1–A15 are green.

## Risks

| Risk | Note |
|---|---|
| The author writes a check that always exits 0 | Would make A3 silent (D3) rather than wrong. Silence is honest; a check that *fabricates* non-zero would not be. Bias toward silence |
| The check cannot launch under `contained()` deny-all network | Lands as `CHECK_DID_NOT_EXECUTE` with the runner's error verbatim — a named cause, satisfying M4. Acceptable |
| `SubprocessAuthor` passes no `env=` (`author.py:107-113`) | Scrubbing is **the author's** job, not Belay's. This is exactly why A2/A3 are written against the author's own constructed env |
| Threading `claim_author` changes mint behavior silently | A9/A10 pin both directions; `--no-claim-axis` must stay byte-identical |

## Open questions

- Should the author live in `src/belay/authoring/` beside the invariant author (shared
  idiom, product surface) or in `eval/` (eval-only)? **Lean `src/`**: the A3 axis is a
  product surface and `README.md:155-161` already documents an author contract for users;
  a reference implementation belongs where users can find it. Decide at plan time.
