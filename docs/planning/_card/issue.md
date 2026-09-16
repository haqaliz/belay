# Corpus Shell-Axis Recompute Routing — unit card

> `gh` issue not used — `corpus-shell-routing` is a slug, not a numeric issue id (no
> GitHub issue exists for this work). Source is the inline brief below, produced by the
> `belay-next` skill handoff (2026-09-16).

## Brief

Build the corpus's shell-axis recompute completion: `belay corpus run --shell-server <cmd>`
threads the second replay boundary to trajectory/claim-case recompute (the seam exists —
`run_corpus` / `run_case` / `_recompute_trajectory_case` already accept
`shell_server_command`; only the CLI flag and its parity-table row are missing, named
NOT-built at `docs/planning/corpus-trajectory-banking/prd.md:145`). Without it, trajectory
cases banked by a two-server mint recompute through the stored single command and read as
false REGRESSION. Test-first REDs: a two-server mint banks a trajectory corrupt-success case
and `corpus run --shell-server` recomputes it MATCH; the no-flag path is byte-identical; the
flag-parity guard declares the widened set. Caveat: a trajectory case stores ONE resolved
command from its final turn — if that final turn is itself `run_process`, routing needs the
PRD's decision; decide also whether a trajectory case with `run_process` turns and no
supplied shell boundary SKIPs with a named cause (the `gate check` precedent) rather than
silently recomputing, and whether `corpus add --shell-server` lands in the same unit. Update
`tests/test_cli_flag_parity.py`, the `corpus run` help text, and `docs/STATUS.md`; no verdict
axis, schema or published number moves — `11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`
stand unedited.