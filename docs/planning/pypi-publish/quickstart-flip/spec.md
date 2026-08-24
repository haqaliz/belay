# Aspect: quickstart-flip

Part of `docs/planning/pypi-publish/prd.md` (launch checklist L4). Make the README's
install path the live truth, machine-checked.

## Problem slice

The README install block still says *"Install (once v0.1.0 is published — until then,
run from source)"* (`README.md:56`) while the package has been live on PyPI since
0.1.0. The record is stale in three places: README, `RELEASING.md:22` (the "C7 →
v0.2.0" example), and `CHECKLIST.md:193-199` (L4's "v0.1.0 published" wording + no
completion-contract note).

## User outcome

A stranger landing on the README gets a true install path that CI has proven
(`artifact-install-ci`), and the launch checklist records L4's real state.

## In-scope requirements (from PRD M3, M4, M6, S1, S2)

- **README install section** (`README.md:54-62`): delete the "until then, run from
  source" caveat; `uv tool install belay-harness` headline, `pipx install` / `pip
  install` alternates; keep the distribution-name note (`README.md:60`); keep the
  Docker quickstart (`README.md:64-84`) and the Develop/from-source section
  (`README.md:287-297`) as the contribution path; add one line noting the package is
  published (S2, version-agnostic — "published to PyPI" without a hardcoded version
  that would rot).
- **Docs-consistency test** `tests/test_quickstart_docs.py` (default suite, fast,
  network-free):
  - README contains neither "until then, run from source" nor "once v0.1.0 is
    published";
  - README's install commands name `belay-harness` (the real dist, `pyproject.toml:9`)
    and the command `belay` (the real entrypoint, `pyproject.toml:52-53`);
  - `RELEASING.md` and `README.md` agree the distribution is `belay-harness`;
  - the stranger-timing runbook's install command matches the README's headline
    command (cross-aspect consistency, once `stranger-timing/runbook.md` exists).
- **`RELEASING.md:22`**: fix the stale "C7 → v0.2.0" example to a real pair (e.g. the
  docker-selfhost slice → v0.21.0) or a neutral phrasing.
- **`CHECKLIST.md` L4** (`:193-199`): correct "`belay-harness` v0.1.0 published" to
  the live-channel fact (published since 0.1.0, 2026-07-18; current 0.21.1); add the
  completion-contract note ("work shipped; the <15-min stranger timing is the
  remaining clause, per the runbook"); append a Progress-log row
  (`CHECKLIST.md:266-271` convention) marking the shipped work, leaving the ✅ for
  the operator after the timed run.

## Out of scope

- The 15-minute measurement itself (operator step, `stranger-timing` aspect).
- Any change to the Docker quickstart content (L3's deliverable).
- Publishing or version bumps.

## Acceptance criteria (test-first)

1. `tests/test_quickstart_docs.py` written FIRST and failing against the current
   README (the caveat string is present today — RED is provable now).
2. After the doc edits: the test passes; `uv run pytest -q` green.
3. `grep -rn "until then, run from source" README.md` → no match (also asserted by
   the test).
4. `CHECKLIST.md` L4 reads the live-channel fact and the completion contract; the
   progress-log row is present; the ✅ box stays unchecked (operator step).

## Dependencies & sequencing

- Second aspect: its claims rest on `artifact-install-ci` (CI-proven install) — build
  order A1 → A2 → A3.
- The cross-aspect consistency assertion needs `stranger-timing/runbook.md` to exist
  — write it in A3, or land the runbook path check as a follow-up note if A3 lags.

## Open questions / risks

- None material — the edits are doc-only; the risk is drift between docs (the
  consistency test is the cure) and the stale-vs-live wording (S2's version-agnostic
  phrasing avoids rot).