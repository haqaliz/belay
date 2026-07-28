"""`python -m eval.minting_driver {one,batch}` — the committed mint commands.

The only argv-aware module in `eval/`. Everything it does is a thin translation of
command-line arguments into a `MintConfig` plus one call into `entrypoint.py`; the test
seams (`prepare`, `transport_factory`, `discover_tools`, `model_factory`) are Python
kwargs on those functions and are deliberately **never** exposed as flags — a flag that
substitutes a fake transport is a flag that can silently mint nothing.

**This is not a product surface.** It must never become `belay mint ...`, never appear in
`[project.scripts]`, and never import `belay` at module level (`CLAUDE.md` guardrail #1);
the optional in-process `--verify` imports it lazily, inside the call.

Two argument decisions are load-bearing, and both exist to make an expensive mistake
impossible rather than merely unlikely:

* **`--root` is required with no default.** A default root is how two mints silently
  share one batch directory: the second bridge either collides or contaminates the
  first's denominator, and the published number is then a number about two runs.
* **`--provider` and `--model` are explicit arguments.** No branch anywhere reads a
  vendor key to decide *what* to build. Credentials come from the environment; the
  choice never does, or the published number names the wrong model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from eval.minting_driver.entrypoint import (
    DEFAULT_CLONES_DIR,
    DEFAULT_CORPUS_DIR,
    DEFAULT_LEDGER_PATH,
    DEFAULT_MAX_STEPS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_REGISTRY_PATH,
    DEFAULT_REQUEST_TIMEOUT,
    PROVIDERS,
    MintConfig,
    MintConfigError,
    MissingCredentialsError,
    mint_from_registry,
    mint_one,
    preflight_servers,
    run_verify,
    verify_server_command,
)
from eval.minting_driver.resilience import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
)
from eval.minting_driver.servers import MissingServerError

PROGRAM = "python -m eval.minting_driver"


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """The flags both subcommands share. Kept in one place so they cannot drift."""
    parser.add_argument(
        "--root",
        required=True,
        metavar="dir",
        help=(
            "the mint root: workspaces, traces, snapshots, <root>/batch and (by default) "
            "<root>/checkpoint.json all live under it. REQUIRED and never defaulted — a "
            "shared root is how two mints silently mix into one batch directory. A fresh "
            "root is also how you re-mint an instance: a fresh ledger for a fresh attempt"
        ),
    )
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY_PATH),
        metavar="path",
        help=(
            f"the instance selection file to mint from (default: {DEFAULT_REGISTRY_PATH}, "
            f"the `instance-pool` aspect's deliverable). An absent file is a named error, "
            f"never an empty mint"
        ),
    )
    parser.add_argument(
        "--clones-dir",
        default=str(DEFAULT_CLONES_DIR),
        metavar="dir",
        help=f"cached bare clones, reused across instances (default: {DEFAULT_CLONES_DIR})",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        metavar="path",
        help="the resume ledger (default: <root>/checkpoint.json)",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=list(PROVIDERS),
        help=(
            f"which client mints (default: {DEFAULT_PROVIDER}). An EXPLICIT choice: no "
            f"exported key can change it, because a stray one would make the published "
            f"number name the wrong model"
        ),
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        metavar="name",
        help=f"the model id to mint with (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        metavar="seconds",
        help=(
            f"per-request timeout (default: {DEFAULT_REQUEST_TIMEOUT:g}s). Deliberately "
            f"not the transport's 10s, which a live model turn plus a cold `node` start "
            f"under Seatbelt does not fit into"
        ),
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=DEFAULT_MAX_STEPS,
        metavar="n",
        help=f"maximum agent steps per instance (default: {DEFAULT_MAX_STEPS})",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        metavar="n",
        help=(
            f"attempts per model call, INCLUDING the first (default: "
            f"{DEFAULT_MAX_ATTEMPTS}; 1 means no retries). Only TRANSIENT errors are "
            f"retried: a provider quota cap stops the mint at any setting, because the "
            f"observed retryDelay was 39043s and no bounded backoff reaches that"
        ),
    )
    parser.add_argument(
        "--retry-base-delay",
        type=float,
        default=DEFAULT_BASE_DELAY_SECONDS,
        metavar="seconds",
        help=(
            f"the first backoff between transient retries, doubling each time "
            f"(default: {DEFAULT_BASE_DELAY_SECONDS:g}s). 0 means retry immediately"
        ),
    )
    parser.add_argument(
        "--server-root",
        default=None,
        metavar="dir",
        help=(
            "where the pinned MCP servers are installed (default: eval/servers, or "
            "$BELAY_EVAL_SERVER_ROOT)"
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "after minting, run the printed `belay phase0 run` in-process over the batch "
            "just captured (requires belay to be importable; it is imported lazily)"
        ),
    )
    parser.add_argument(
        "--ledger",
        default=str(DEFAULT_LEDGER_PATH),
        metavar="path",
        help=f"where --verify writes the run ledger (default: {DEFAULT_LEDGER_PATH})",
    )
    parser.add_argument(
        "--corpus-dir",
        default=str(DEFAULT_CORPUS_DIR),
        metavar="dir",
        help=f"where --verify ingests flagged turns (default: {DEFAULT_CORPUS_DIR})",
    )


def build_parser() -> argparse.ArgumentParser:
    """The two-subcommand argv surface: `one <instance-id>` and `batch`."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Mint Phase-0 captures: drive an instance (or a whole selection) through the "
            "gated MCP proxy and bridge each capture into the layout `belay phase0 run` "
            "resolves. Eval machinery, not a product surface."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    one = subcommands.add_parser(
        "one",
        help="mint exactly one registry instance, by id (the Stage-1 tool)",
        description=(
            "Mint one instance by id. Identical code path to `batch` over a one-record "
            "list, so it rehearses the batch rather than rehearsing itself."
        ),
    )
    one.add_argument("instance_id", help="the instance_id to mint, as it appears in the registry")
    _add_common_arguments(one)

    batch = subcommands.add_parser(
        "batch",
        help="mint every instance in the registry, sequentially and resumably",
        description=(
            "Mint the whole selection. Sequential, resumable (re-run the same --root to "
            "skip everything already recorded) and error-contained (one bad instance is "
            "recorded `failed` and the mint continues)."
        ),
    )
    _add_common_arguments(batch)

    return parser


def config_from_args(args: argparse.Namespace) -> MintConfig:
    """A `MintConfig` from parsed arguments. Pure — no filesystem, no environment."""
    return MintConfig(
        root=Path(args.root),
        clones_dir=Path(args.clones_dir),
        registry_path=Path(args.registry),
        checkpoint_path=Path(args.checkpoint) if args.checkpoint else None,
        provider=args.provider,
        model=args.model,
        request_timeout=args.request_timeout,
        max_steps=args.max_steps,
        max_attempts=args.max_attempts,
        retry_base_delay=args.retry_base_delay,
        server_root=Path(args.server_root) if args.server_root else None,
    )


def build_config(argv: Sequence[str]) -> MintConfig:
    """Parse `argv` and return just the resolved `MintConfig` (the testable half)."""
    return config_from_args(build_parser().parse_args(list(argv)))


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Mint, print where the artifacts landed and how to score them, and exit.

    Exit codes: `0` on a completed mint (including one with contained per-instance
    failures — those are recorded facts, not a broken run), `2` for a setup error the
    operator must fix (a missing server install, an absent registry, a bad config,
    absent credentials). A setup error prints ONE legible line on stderr, never a
    traceback: the whole point of the preflight is that "you forgot `npm install`" reads
    as itself rather than as an hour of failed instances.
    """
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    try:
        cfg = config_from_args(args)
        if args.command == "one":
            report = mint_one(args.instance_id, cfg)
        else:
            report = mint_from_registry(cfg)
    except (MintConfigError, MissingCredentialsError, MissingServerError) as exc:
        print(f"mint: {exc}", file=sys.stderr)
        return 2

    print(report.render())

    if args.verify:
        # Re-resolved rather than carried: `preflight_servers` is a pure filesystem
        # lookup and the mint above already proved it succeeds.
        entrypoint = preflight_servers(cfg)
        return run_verify(
            report,
            server_command=verify_server_command(entrypoint),
            # Absolute, like every path in `MintConfig`: these name where the verify
            # output lands, and a relative path is only unambiguous from one CWD.
            ledger_path=Path(args.ledger).resolve(),
            corpus_dir=Path(args.corpus_dir).resolve(),
        )

    return 0


__all__ = ["build_config", "build_parser", "config_from_args", "main"]
