# PRD — shared corpus: the pattern catalog

**Issue:** #58 · **Slug:** `shared-corpus-patterns` · **Branch:** `feat/58/aliz`

## Problem

Phase 2's third goal is *"the team's failure corpus as a queryable, growing asset"*. Today
`corpus/` is local-only. Raw cases cannot be shared: a case bundles the trace, the pre-state
tree and the server command — the no-raw-data-egress guardrail (R12) forbids moving them,
and they carry whatever was in the user's workspace.

## What ships

**A shareable pattern catalog** — the part of a corpus that is safe to move:

- `belay corpus share export [--corpus-dir <dir>] --out <file>`: reads labeled cases and
  writes `belay-corpus-patterns/1`, a bundle of **whitelisted facts only**:
  `pattern_id`, `label`, `reduced_status`, `sub_verdicts` (axis/kind/status), `tools`
  (tool names), `invariant_rules` (rule names only — never scope bytes), `trajectory`
  (status only — never its cause), `claim` (status only — never its cause).
  **Never exported:** trace, manifests, prestate, server command, case id, provenance,
  paths, arguments, content, cause strings, recorded-miss notes.
- `belay corpus share import <file> [--corpus-dir <dir>]`: validates the schema, merges by
  `pattern_id` (idempotent, deterministic order), and refuses a malformed/unknown-schema
  bundle whole (exit 2, named).
- `belay corpus share list [--corpus-dir <dir>]`: counts by label, rule and tool.

Storage: `<corpus-dir>/patterns.json` — a file beside the case directories, so `corpus
run`/`score` are untouched. **Imported patterns are not cases:** they are never replayed and
never enter precision/recall (unknown provenance; mixing them would launder a stranger's
labels into your own measurement).

`pattern_id` is a sha256 over the canonical whitelisted facts, so two teams that saw the same
pattern dedupe to one entry, and no instance name can be recovered from it.

## Non-goals

- No case exchange, no raw data, no server/control plane, no auth, no upload endpoint.
- No replay of imported patterns, no scoring, no trust levels, no consent UI (invoking
  `share export` is the consent).
- No change to `corpus add/run/score/list/show/label`, or to any verdict.

## Acceptance criteria

1. Exporting a corpus yields only the whitelisted keys; a byte-level assertion proves no
   trace/manifest content, path, server command or cause string appears in the bundle.
2. `pattern_id` is stable across runs and across two identical cases; different labels yield
   different ids.
3. Import of the exported bundle is idempotent (second import adds nothing), sorts
   deterministically, and a malformed/unknown-schema bundle exits 2 named.
4. `share list` counts by label/rule/tool and states that patterns are not scored.
5. `corpus run` and `corpus score` behave exactly as before with a `patterns.json` present.
6. Empty corpus exports an empty, valid bundle (exit 0).

## Risks

- **R-a:** a whitelisted field still leaks something (a tool name can be proprietary).
  Accepted and documented: the operator sees the bundle before sending it.
- **R-b:** imported counts read as your own detection quality. Refused by construction: not
  scored, and the list says so.
- **R-c:** dedupe by hash hides near-duplicates. Accepted: exact-pattern dedupe is the
  honest unit; clustering is a later question.

## Open questions

- 🟡 **Q1:** include the case `label` distribution for unlabeled cases? Proposed: export only
  `pending`/labeled as-is; the list shows pending separately.
