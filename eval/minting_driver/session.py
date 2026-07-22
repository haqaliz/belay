"""The real-server entrypoint: owns transport lifecycle around `run_task`.

`run_task` (`loop.py`) is deliberately transport-agnostic — it takes whatever object
satisfies the `Transport` protocol and never constructs or closes one. Something has to
own that: a real run spawns a subprocess (`StdioMcp`), and a subprocess that is never
closed on an exception or a `max_steps` bail-out is a leaked child process. `run_session`
is that owner — construct, run, and *always* close, in a `finally`, regardless of how
`run_task` returns or raises.
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol

from eval.minting_driver.loop import Transcript, Transport, run_task
from eval.minting_driver.model import Model


class ClosableTransport(Transport, Protocol):
    """`Transport` plus `close()` — what `run_session` needs to own a transport's
    lifecycle. `StdioMcp` (`transport.py`) satisfies this structurally.
    """

    def close(self) -> None: ...


#: A factory that builds one transport for one session, given the spawn command and
#: environment. Defaults to `StdioMcp` in `run_session`, but is injectable so tests can
#: supply a fake without spawning a real subprocess.
TransportFactory = Callable[[list[str], dict], ClosableTransport]


def _default_transport_factory(server_command: list[str], env: dict) -> ClosableTransport:
    # Imported lazily so importing this module never requires `subprocess` to succeed
    # in an environment that only wants the pure `run_task`/fakes path (and so a test
    # that injects its own `transport_factory` never needs a real `StdioMcp`).
    from eval.minting_driver.transport import StdioMcp

    return StdioMcp(server_command, env)


def run_session(
    model: Model,
    *,
    server_command: list[str],
    env: dict,
    system: str,
    task: str,
    max_steps: int,
    transport_factory: Optional[TransportFactory] = None,
    request_timeout: Optional[float] = None,
) -> Transcript:
    """Construct a transport for `server_command`/`env`, run one task through it, and
    always close it.

    `transport_factory` defaults to spawning a real `StdioMcp`; tests inject a fake
    factory (or fake transport) to exercise this deterministically, with no real
    subprocess and no real model. `close()` is called exactly once, in a `finally`, on
    every path: normal completion, `run_task` hitting `max_steps`, and `run_task`
    raising — the exception still propagates, but the transport is never leaked.

    `request_timeout` is forwarded verbatim to `run_task`, where it becomes the per-request
    ceiling on every `transport.request`. `None` (the default) leaves the transport's own
    `DEFAULT_TIMEOUT` in force — byte-identical to before the knob existed.
    """
    factory = transport_factory or _default_transport_factory
    transport = factory(server_command, env)
    try:
        return run_task(
            model,
            transport,
            system=system,
            task=task,
            max_steps=max_steps,
            request_timeout=request_timeout,
        )
    finally:
        transport.close()


__all__ = ["ClosableTransport", "TransportFactory", "run_session"]
