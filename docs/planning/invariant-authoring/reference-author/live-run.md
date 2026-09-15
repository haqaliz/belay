# Live proof — the reference author on the launch demo task (owner-run, n=1)

**Date:** 2026-09-15
**Model:** `claude-opus-5` (full id, per the D-2 discipline)
**Environment:** this worktree on macOS (Seatbelt), venv python
`…/feat-invariant-authoring-experiment/.venv/bin/python3`
**Status:** ✅ **the path works at n=1** — and the first real output carries a
finding (below). Never read as a quality claim about the model's invariants.

## Exact commands (verbatim)

```bash
VPY=$(uv run python -c "import sys; print(sys.executable)")
WT=$(pwd)

"$VPY" -m belay.cli invariant infer \
  --task "$WT/docs/planning/invariant-authoring/reference-author/live-run/task.md" \
  --author "\"$VPY\" -m belay.authoring.reference_author --model claude-opus-5" \
  --control "$WT/demo/capture/trace-20260827T001428Z-e23f999d.jsonl" \
  --manifest-dir "$WT/demo/capture/trace-20260827T001428Z-e23f999d.manifests" \
  --timeout 300 \
  --out "$WT/docs/planning/invariant-authoring/reference-author/live-run/invariants.json" \
  --json \
  --server "$VPY" "$WT/demo/server.py" <recorded source_root>

"$VPY" -m belay.cli verify --json --timeout 300 \
  --invariants "$WT/docs/planning/invariant-authoring/reference-author/live-run/invariants.json" \
  --manifest-dir "$WT/demo/capture/trace-20260827T001428Z-e23f999d.manifests" \
  "$WT/demo/capture/trace-20260827T001428Z-e23f999d.jsonl" \
  --server "$VPY" "$WT/demo/server.py" <recorded source_root>
```

`<recorded source_root>` =
`/Users/aliz/dev/at/belay/.claude/worktrees/feat-launch-demo/demo/.capture-runs/run-014/workspace`
(read from the capture's own manifests; replay relocates it to the scratch).
All paths **absolute** — replay spawns the server with cwd set to the scratch
copy, so a relative server command cannot launch (the repository's convention).

## Outcome

- **Infer: rc 0, 96.5 s.** The reference author proposed 4 candidates; all
  survived calibration (the control's delta touches `app.py` only, so none
  over-fire); the artifact
  `belay-authored-invariants/1` was emitted with the calibration digest. Verbatim
  JSON: `infer.out`.
- **Verify of the launch capture with the authored artifact: rc 0, 85.7 s.**
  **`aggregate: {turns_verified: 7, PASS: 7, WARN: 0, FAIL: 0, UNVERIFIED: 0}`**,
  trajectory **PASS** ("supported by 2 replayed command turn(s)") — the negative
  control holds under authored policy. Verbatim JSON: `verify.out`.
- The pytest-form live test (`tests/test_reference_author_live.py`, `manual`-marked)
  passed in 179.5 s with the same shape.

## The finding (R-g: a result, recorded, not hidden)

The model's scopes use **glob syntax** — `tests/**` — while the engine's A1
semantics are **raw byte-prefix** (a path is in scope iff it starts with the
scope bytes). `b"tests/**"` never prefixes a real path, so:

- `no-assertion-weakening`, `no-delete`, and `read-only` @ `tests/**` are **dead
  teeth**: on any run whose delta touches `tests/…`, they would PASS trivially
  instead of firing — the exact failure the per-invariant corrupt fixtures exist
  to catch (and do catch, for the fixture vocabulary).
- `suite-before-success-claim` is an instance-level rule whose scope is
  meaningless by construction; it is the library's first entry, not a
  task-scoped inference.
- Calibration cannot see this: on the clean control every candidate PASSes
  trivially, which is the accepted "no over-fire" reading.

**What this does NOT mean:** the engine is wrong, or the path failed. **What it
does mean:** the authoring prompt / protocol's first real output shows the
scope-shape mismatch is the experiment's first actionable finding — a follow-on
normalization (the author declares `tests/` style prefixes, or the protocol
rejects glob-shaped scopes with a named cause) is the likely next unit. This is
why the experiment is an experiment: it produced a result at n=1.

## Honesty lines

- The artifact records `author.program` (the venv python) and `model: null` (the
  author's response carries no model field in the first slice) — the operator's
  command line never appears.
- No published number moves; nothing recomputed; the launch capture's pinned
  contract (7/7 PASS + trajectory PASS) is reproduced with authored policy
  enforced, not altered.