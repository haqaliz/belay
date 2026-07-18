# Contributing to Belay

Thanks for your interest. Belay is the **agent harness** — a sandbox / deterministic-replay /
execution-grounded-verification engine — and contributions are welcome. This guide is short; the
few rules it does state are load-bearing.

## Ground rules (these are the moat, not bureaucracy)

Belay's entire value is an **honest, execution-grounded verdict**. A change that erodes that is a
regression no matter how much it adds. Before you build, read [CLAUDE.md](CLAUDE.md) and
[VISION.md](VISION.md); in particular:

1. **No agent framework.** Belay wraps whatever agent the user already runs — it never authors or
   orchestrates the agent.
2. **No LLM in the verdict.** A model may *write* a check (the future A3 axis), but only
   **execution** may decide a verdict. An AST test bans any inference import from the verdict path;
   do not work around it.
3. **`UNVERIFIED` is never `PASS`.** Where Belay cannot see or cannot ground a claim, it says so by
   name. Never upgrade an honest `UNVERIFIED` to a cheerful pass.
4. **No raw-data egress.** Belay runs on the user's infrastructure; traces and state stay local.
5. **Zero runtime dependencies.** The engine is stdlib-only. Dev-only tooling is fine; a runtime
   dependency needs a very good reason.

## Development setup

Python 3.10+ and [uv](https://github.com/astral-sh/uv). The sandbox and snapshot are macOS-only, so
the full suite runs best on macOS (one test is platform-gated off elsewhere).

```bash
git clone https://github.com/haqaliz/belay && cd belay
uv sync
uv run pytest          # run the suite
uv run ruff check .    # lint
uv run belay --help    # the CLI, from source
```

## The workflow

- **Test-first, always.** Belay is built strictly RED → GREEN → REFACTOR: no production code without
  a failing test first. Honesty properties get tests with *teeth* — watched failing against a stub
  before they are trusted (a guard nobody has seen fail may be passing vacuously).
- **Branch from `master`** (the base branch — there is no `main`). Name branches
  `<type>/<id>/<owner>`, e.g. `feat/live-console/aliz` or `bug/42/aliz`.
- **Keep the suite green** (`uv run pytest`) and the tree lint-clean (`uv run ruff check .`) on every
  commit.
- **Open a PR against `master`** with a clear description of what changed and, for anything touching
  a verdict, which axis (A1/A2/A3) it affects and what its explicit `UNVERIFIED` path is.

## Reporting bugs & ideas

Open a [GitHub issue](https://github.com/haqaliz/belay/issues). For anything security- or
privacy-sensitive, follow [SECURITY.md](SECURITY.md) instead of filing a public issue.

## License

By contributing, you agree that your contributions are licensed under the
[Apache-2.0 License](LICENSE).
