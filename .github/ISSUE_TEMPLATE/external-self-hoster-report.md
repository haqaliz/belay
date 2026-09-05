---
name: External self-hoster report
about: Report an external install + real failure caught on YOUR agent (launch gate item)
title: "external self-hoster: [short description of the caught failure]"
labels: external-self-hoster
assignees: ''
---

<!-- The launch gate needs someone who is not the owner to have installed Belay,
run it against THEIR agent, and caught a real failure. This form is what makes
that report usable. Fill every section; "n/a" is a valid answer where noted. -->

## 1 · Environment

- Machine / OS / kernel: <!-- e.g. macOS 26.5.2 Apple Silicon · Linux 6.8 ubuntu-24.04 -->
- Install path: <!-- PyPI (`uv tool install belay-harness`) or container -->
- `belay --version`:
- Agent + MCP server: <!-- e.g. claude-code + @modelcontextprotocol/server-filesystem -->

## 2 · The run

- Task you gave the agent (verbatim or close):
- Trace + manifests: <!-- attach or link the .jsonl and .manifests sibling -->
- Verdict document: <!-- `belay verify --json ...` output for the run -->

## 3 · The caught failure

- Turn index and reduced status:
- Sub-verdicts and causes:
- **The coverage line** (must travel with every verdict quoted):
- Corpus case id(s): <!-- from `belay corpus add --label true-positive`; the
  case must re-run to MATCH with `belay corpus run` -->

## 4 · Your adjudication (the tool never labels itself)

- What you observed the agent do:
- What the verdict said:
- Do you call this a **true positive** (real failure), a **false positive**, or an
  **instrument artifact** (e.g. boundary does not offer the tool, replay timeout)?
  Why:

## 5 · Anything that broke

<!-- Setup failures, sandbox refusals, UNVERIFIED causes, docs gaps — all are
findings. Report them the same way; a false abstention is a finding, not a catch. -->

## 6 · Consent

<!-- This report may be cited (anonymised or named as you prefer) in the Belay
launch materials. -->
- [ ] OK to cite as-is
- [ ] OK to cite anonymised
- [ ] Do not cite