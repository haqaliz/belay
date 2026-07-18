# Security & Privacy

## The privacy model (read this first)

Belay is designed so that **your data never leaves your machine**. It runs on your own
infrastructure, has zero runtime dependencies, and has no upload path anywhere in the codebase.
Two properties are worth stating plainly because they are easy to get wrong:

- **A trace is as sensitive as the agent's most sensitive tool argument.** Capture is lossless by
  design, so API keys, tokens, file contents, and customer data crossing the MCP boundary land in
  the trace verbatim and fully recoverable. Trace files are created owner-only (`0600`); there is
  deliberately **no redaction and no secret scanning** (both are opinions, and a redacted trace
  cannot be replayed). **Treat a trace file as the credential it may contain**, and do not commit
  or share one without reviewing it.

- **Corpus cases stay local.** `belay corpus add` bundles a run's pre-state into a case; cases are
  written under `corpus/local/`, which is gitignored, and are never uploaded. Do not commit them.

The sandbox's guarantees and its exact limits (reads are not scoped; denial records are inferred;
macOS-only) are documented in [`docs/technical/THREAT_MODEL.md`](docs/technical/THREAT_MODEL.md).
Read it before relying on the word "sandbox".

## Supported versions

Belay is in **alpha** (`0.x`). Security fixes are made against the latest release and `master`;
older `0.x` tags are not maintained.

## Reporting a vulnerability

Please **do not open a public issue** for a security or privacy vulnerability.

Instead, report it privately via GitHub's **[Report a vulnerability](https://github.com/haqaliz/belay/security/advisories/new)**
(Security → Advisories) on the repository. Include a description, reproduction steps, and the
impact you foresee.

You can expect an acknowledgement within a few days. Once a fix is available, we will coordinate
disclosure and credit you in the release notes unless you prefer to remain anonymous.
