"""Offline, deterministic tests for the committed mint entry point
(`eval/minting_driver/entrypoint.py`).

The entry point is the program that turns the already-built `eval/` parts (registry,
workspace prep, gated capture, bridge, checkpoint) into something a human can actually
run. These tests never spend, never touch the network, never spawn a subprocess and
never run git: they use the same seam-injection vocabulary as
`tests/test_minting_driver_batch.py` (`StubPrepare`, `OkTransport`, a counting model
factory, `discover_tools=lambda cmd: []`).

Two hazards drive most of what is asserted here, and both are *fake-PIVOT* vectors — a
mistake that produces an empty mint, which `belay phase0 run` reads as
`INSTRUMENT SUSPECT`:

1. a stray `ANTHROPIC_API_KEY` silently switching which model mints (so provider
   selection is an explicit argument, asserted behaviourally *and* structurally); and
2. `LocalOpenAICompatModel`'s `LOCAL_SENTINEL_API_KEY` fallback — right for Ollama,
   wrong for a hosted endpoint, where it 401s once per instance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eval.instances.registry import InstanceRecord, dump_registry
from eval.minting_driver import transport as transport_module
from eval.minting_driver.batch import run_mint
from eval.minting_driver.clients.local_client import LocalOpenAICompatModel
from eval.minting_driver.entrypoint import (
    DEFAULT_REQUEST_TIMEOUT,
    WORKSPACE_PLACEHOLDER,
    MintConfig,
    MintConfigError,
    MissingCredentialsError,
    RegistryNotFoundError,
    UnknownInstanceError,
    make_model_factory,
    mint_batch,
    mint_one,
    preflight_servers,
    resolve_credentials,
)
from eval.minting_driver.servers import PINNED_SERVERS, MissingServerError
from eval.minting_driver.workspace import layout_for

ENTRYPOINT_SOURCE = (
    Path(__file__).parent.parent / "eval" / "minting_driver" / "entrypoint.py"
)


class FakeOpenAIClient:
    """The `client=` injection seam of `LocalOpenAICompatModel` — never contacted here."""

    def __init__(self) -> None:
        self.chat = self  # type: ignore[assignment]
        self.completions = self  # type: ignore[assignment]

    def create(self, **kwargs: object) -> object:  # pragma: no cover - never called
        raise AssertionError("no model call may happen in this test")


def _record(instance_id: str, *, task: str = "make the edit") -> InstanceRecord:
    return InstanceRecord(
        instance_id=instance_id,
        repo="octo/repo",
        base_commit="abc1234",
        problem_statement="an issue to fix",
        task_string=task,
    )


# --------------------------------------------------------------------------------------
# Provider selection is an argument, never an environment sniff
# --------------------------------------------------------------------------------------


def test_provider_selection_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stray Anthropic key in the shell cannot change which model mints.

    The old smoke-test rule ("Anthropic if its key is set, else the local client") is
    exactly the hazard: the published number would name the wrong model. Here the
    provider is passed, the environment holds a competing key, and the built model is
    still the OpenAI-compat one — the REAL class, with a fake `client=`.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-be-ignored")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    factory = make_model_factory(
        provider="openai-compat",
        model="gemini-flash-latest",
        client=FakeOpenAIClient(),
    )
    model = factory([])

    assert isinstance(model, LocalOpenAICompatModel)


def test_entrypoint_module_never_sniffs_the_anthropic_key() -> None:
    """Structural guard: the env-sniff cannot be reintroduced without failing a test.

    The behavioural test above proves *this* build; this one prevents the branch from
    coming back. Same precedent as
    `tests/test_minting_driver_transport.py::test_transport_module_is_standalone`.
    """
    source = ENTRYPOINT_SOURCE.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" not in source, (
        "entrypoint.py must not name the Anthropic key at all: provider selection is an "
        "explicit argument, and credentials are the SDK's business"
    )


# --------------------------------------------------------------------------------------
# The timeout can never silently be the 10s transport default
# --------------------------------------------------------------------------------------


def test_entrypoint_requires_explicit_timeout(tmp_path: Path) -> None:
    """`None` and non-positive timeouts are refused; the default is not the 10s one."""
    with pytest.raises(MintConfigError, match="request_timeout"):
        MintConfig(root=tmp_path / "mint", request_timeout=None)  # type: ignore[arg-type]

    with pytest.raises(MintConfigError, match="request_timeout"):
        MintConfig(root=tmp_path / "mint", request_timeout=0.0)

    with pytest.raises(MintConfigError, match="request_timeout"):
        MintConfig(root=tmp_path / "mint", request_timeout=-1.0)

    # Imported and compared, never hardcoded: if the transport default moves, this test
    # still asserts the real property ("the mint does not inherit it").
    assert DEFAULT_REQUEST_TIMEOUT != transport_module.DEFAULT_TIMEOUT
    assert DEFAULT_REQUEST_TIMEOUT > transport_module.DEFAULT_TIMEOUT

    cfg = MintConfig(root=tmp_path / "mint")
    assert cfg.request_timeout == DEFAULT_REQUEST_TIMEOUT


def test_run_mint_rejects_a_none_request_timeout(tmp_path: Path) -> None:
    """`run_mint` itself refuses `None` — the hole is closed for every caller, not just
    the entry point. `None` used to fall through to `transport.DEFAULT_TIMEOUT = 10.0`,
    too tight for a live model turn plus a cold `node` start under Seatbelt."""
    with pytest.raises(ValueError, match="request_timeout"):
        run_mint(
            [_record("octo__repo-1")],
            root=tmp_path / "mint",
            clones_dir=tmp_path / "clones",
            model_factory=lambda tools: None,  # type: ignore[arg-type,return-value]
            build_server_command=lambda layout: ["node", "server.js"],
            checkpoint_path=tmp_path / "ckpt.json",
            request_timeout=None,  # type: ignore[arg-type]
            max_steps=8,
            system="sys",
        )

    with pytest.raises(ValueError, match="request_timeout"):
        run_mint(
            [_record("octo__repo-1")],
            root=tmp_path / "mint",
            clones_dir=tmp_path / "clones",
            model_factory=lambda tools: None,  # type: ignore[arg-type,return-value]
            build_server_command=lambda layout: ["node", "server.js"],
            checkpoint_path=tmp_path / "ckpt.json",
            request_timeout=0.0,
            max_steps=8,
            system="sys",
        )


# --------------------------------------------------------------------------------------
# Credentials are required by name — no silent sentinel
# --------------------------------------------------------------------------------------


def test_openai_compat_provider_requires_base_url_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset `OPENAI_API_KEY` is a loud error, not `LOCAL_SENTINEL_API_KEY`.

    The sentinel is right for Ollama and wrong for a hosted endpoint, where it produces
    a 401 on the first call of every instance — dozens of contained failures and an
    empty mint that reads as `INSTRUMENT SUSPECT`.
    """
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingCredentialsError) as excinfo:
        resolve_credentials("openai-compat")
    message = str(excinfo.value)
    assert "OPENAI_API_KEY" in message
    assert "OPENAI_BASE_URL" in message

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    with pytest.raises(MissingCredentialsError) as excinfo:
        resolve_credentials("openai-compat")
    assert "OPENAI_BASE_URL" in str(excinfo.value)

    # A blank value is as missing as an absent one.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    with pytest.raises(MissingCredentialsError):
        resolve_credentials("openai-compat")

    # And with both present, the resolved credentials are returned verbatim — no
    # sentinel substitution anywhere in the path.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    credentials = resolve_credentials("openai-compat")
    assert credentials["api_key"] == "sk-openai"
    assert credentials["base_url"] == "https://example.invalid/v1"


def test_make_model_factory_without_an_injected_client_requires_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The credential check fires at factory-build time, before any instance is driven."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")

    with pytest.raises(MissingCredentialsError):
        make_model_factory(provider="openai-compat", model="gemini-flash-latest")


def test_unknown_provider_is_a_named_error(tmp_path: Path) -> None:
    """A typo'd provider is refused at config time, listing the known providers."""
    with pytest.raises(MintConfigError, match="provider"):
        MintConfig(root=tmp_path / "mint", provider="openai")


# --------------------------------------------------------------------------------------
# Seams — the same vocabulary as `tests/test_minting_driver_batch.py`, ~15 lines
# duplicated deliberately rather than lifted into a premature shared fixture.
# --------------------------------------------------------------------------------------


class StubPrepare:
    """Workspace prep without git: makes the layout dirs and drops a fake trace file.

    The fake `trace-*.jsonl` is what the REAL `bridge_capture` moves — with no gated
    proxy running, nothing else would write one. Records which instances it prepared, in
    order, so a test can assert which were driven and which were never touched.
    """

    def __init__(self) -> None:
        self.prepared: list[str] = []

    def __call__(
        self, record: InstanceRecord, *, root: object, clones_dir: object
    ) -> object:
        layout = layout_for(record.instance_id, Path(str(root)))
        layout.work_dir.mkdir(parents=True, exist_ok=True)
        layout.trace_dir.mkdir(parents=True, exist_ok=True)
        layout.snapshot_dir.mkdir(parents=True, exist_ok=True)
        (layout.trace_dir / "trace-20260723T000000Z-abcd1234.jsonl").write_text(
            '{"turn": 0}\n', encoding="utf-8"
        )
        self.prepared.append(record.instance_id)
        return layout


class OkTransport:
    """A benign fake transport: canned replies, no subprocess, no trace side effects."""

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        method = obj["method"]
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": obj["id"], "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": obj["id"], "result": {"tools": []}}
        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        raise AssertionError(f"unexpected method: {method}")

    def notify(self, obj: dict) -> None:
        pass

    def close(self) -> None:
        pass


class SpyModelFactory:
    """Counts factory calls and hands back a fresh `ScriptedModel` each time."""

    def __init__(self) -> None:
        self.calls = 0
        self.models: list[object] = []

    def __call__(self, tools: object) -> object:
        from eval.minting_driver.fakes import ScriptedModel
        from eval.minting_driver.model import Done, ToolCall

        self.calls += 1
        model = ScriptedModel([ToolCall(name="read_file"), Done(reason="done")])
        self.models.append(model)
        return model


def _install_stub_server(server_root: Path, name: str = "filesystem") -> Path:
    """A fake 'installed' server: an empty file at the pinned entrypoint path.

    `resolve_server_entrypoint` only calls `.is_file()`, so this is a valid fixture and
    CI never runs `npm install` or spawns `node`.
    """
    entrypoint = server_root / PINNED_SERVERS[name].entrypoint
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text("// stub\n", encoding="utf-8")
    return entrypoint


# --------------------------------------------------------------------------------------
# The server preflight — loud, once, before anything is prepped or spent
# --------------------------------------------------------------------------------------


def test_missing_servers_fail_fast_with_install_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent `eval/servers/` names the exact pinned `npm install` to run."""
    monkeypatch.setenv("BELAY_EVAL_SERVER_ROOT", str(tmp_path / "servers"))

    cfg = MintConfig(root=tmp_path / "mint")
    with pytest.raises(MissingServerError) as excinfo:
        preflight_servers(cfg)

    message = str(excinfo.value)
    assert "npm install" in message
    assert "@modelcontextprotocol/server-filesystem@2026.7.10" in message


def test_preflight_runs_before_any_prep_or_model_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering assertion — this is what distinguishes a preflight from a contained
    per-instance failure.

    `build_server_command` is called INSIDE `run_mint`'s per-instance `try/except`, so a
    missing install would otherwise record every one of ~65 instances `failed` with the
    same message, produce an empty batch dir, and read as INSTRUMENT SUSPECT — a fake
    PIVOT from an `npm install` that was never run, an hour after the mint started.
    """
    monkeypatch.setenv("BELAY_EVAL_SERVER_ROOT", str(tmp_path / "servers"))
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    cfg = MintConfig(root=tmp_path / "mint")
    prepare = StubPrepare()
    factory = SpyModelFactory()

    with pytest.raises(MissingServerError):
        mint_batch(
            [_record("octo__repo-1"), _record("octo__repo-2")],
            cfg,
            model_factory=factory,
            prepare=prepare,
            transport_factory=lambda cmd, env: OkTransport(),
            discover_tools=lambda cmd: [],
        )

    assert prepare.prepared == [], "no workspace may be prepped before the preflight"
    assert factory.calls == 0, "no model may be constructed before the preflight"
    assert not cfg.checkpoint_path.exists(), "no checkpoint may be written"
    assert not cfg.batch_dir.exists(), "no batch dir may be created"


def test_preflight_passes_with_a_stub_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the pinned entrypoint present, the preflight returns its absolute path."""
    server_root = tmp_path / "servers"
    entrypoint = _install_stub_server(server_root)
    monkeypatch.setenv("BELAY_EVAL_SERVER_ROOT", str(tmp_path / "elsewhere"))

    # `--server-root` (cfg.server_root) wins over the environment variable.
    cfg = MintConfig(root=tmp_path / "mint", server_root=server_root)
    resolved = preflight_servers(cfg)

    assert resolved == entrypoint.resolve()
    assert resolved.is_absolute()


def test_mint_batch_runs_through_the_real_bridge_once_servers_are_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preflight OK -> the batch actually drives, bridges, and records `captured`."""
    server_root = tmp_path / "servers"
    _install_stub_server(server_root)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    cfg = MintConfig(root=tmp_path / "mint", server_root=server_root)
    prepare = StubPrepare()
    factory = SpyModelFactory()

    checkpoint = mint_batch(
        [_record("octo__repo-1")],
        cfg,
        model_factory=factory,
        prepare=prepare,
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )

    assert prepare.prepared == ["octo__repo-1"]
    assert factory.calls == 1
    assert checkpoint.status("octo__repo-1") == "captured"
    # The layout the stock `belay phase0 run` resolves — the real `bridge_capture` ran.
    assert (cfg.batch_dir / "trace-octo__repo-1.jsonl").is_file()
    assert (cfg.batch_dir / "trace-octo__repo-1.manifests").is_dir()


# --------------------------------------------------------------------------------------
# A fresh model client per instance — instance N never inherits instance N-1
# --------------------------------------------------------------------------------------


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str = "{}") -> None:
        self.id = call_id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content: str | None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message
        self.finish_reason = "stop"


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [_FakeChoice(message)]


class ScriptedOpenAIClient:
    """A fake OpenAI-compatible client: one scripted reply per `create`, all recorded.

    Shaped exactly like the slice of the SDK `LocalOpenAICompatModel` touches
    (`.chat.completions.create` -> `.choices[0].message.{content,tool_calls}`), so the
    REAL client class is under test and the `openai` package is never imported.
    """

    def __init__(self, script: list[_FakeMessage]) -> None:
        self._script = list(script)
        self.calls: list[list[dict]] = []
        self.chat = self  # type: ignore[assignment]
        self.completions = self  # type: ignore[assignment]

    def create(self, **kwargs: object) -> _FakeResponse:
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        # A deep-enough copy: the model mutates its running list in place.
        self.calls.append([dict(message) for message in messages])
        if not self._script:
            raise AssertionError(
                "ScriptedOpenAIClient: more calls than scripted replies"
            )
        return _FakeResponse(self._script.pop(0))


class RecordingModelFactory:
    """Wraps a real `ModelFactory` and keeps every model it built, in order."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.models: list[Any] = []

    def __call__(self, tools: object) -> Any:
        model = self._inner(tools)  # type: ignore[operator]
        self.models.append(model)
        return model


def test_fresh_model_client_per_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """The factory builds a NEW model on every call — never a cached singleton.

    `run_mint` calls `model_factory` once per instance, and the clients accumulate
    conversation state (`LocalOpenAICompatModel._openai_messages`). A factory that
    closed over one pre-built model would hand instance N instance N-1's conversation.
    Asserted on the REAL class with an injected fake `client=`, not on a stand-in.
    """
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    factory = make_model_factory(
        provider="openai-compat",
        model="gemini-flash-latest",
        client=FakeOpenAIClient(),
    )
    first = factory([])
    second = factory([])

    assert isinstance(first, LocalOpenAICompatModel)
    assert isinstance(second, LocalOpenAICompatModel)
    assert first is not second
    # Distinct list OBJECTS, not merely equal empty lists — a shared list is exactly how
    # a "cache the client, it's the same config" refactor would leak the conversation.
    assert first._openai_messages is not second._openai_messages
    assert first._seen == 0 and second._seen == 0


def test_conversation_state_does_not_bleed_between_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two instances driven through `mint_batch`: the second starts from an empty
    conversation, even though the first issued a tool call and got a result back."""
    server_root = tmp_path / "servers"
    _install_stub_server(server_root)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    client = ScriptedOpenAIClient(
        [
            # Instance 1, turn 1: a tool call (so a `role="tool"` message lands in its
            # conversation) ...
            _FakeMessage(None, [_FakeToolCall("call-1", "read_file")]),
            # ... turn 2: stop.
            _FakeMessage("instance one done"),
            # Instance 2, turn 1: stop immediately.
            _FakeMessage("instance two done"),
        ]
    )
    factory = RecordingModelFactory(
        make_model_factory(
            provider="openai-compat", model="gemini-flash-latest", client=client
        )
    )

    cfg = MintConfig(root=tmp_path / "mint", server_root=server_root, max_steps=4)
    checkpoint = mint_batch(
        [
            _record("octo__repo-1", task="TASK-ONE"),
            _record("octo__repo-2", task="TASK-TWO"),
        ],
        cfg,
        model_factory=factory,
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )

    assert checkpoint.status("octo__repo-1") == "captured"
    assert checkpoint.status("octo__repo-2") == "captured"
    assert len(factory.models) == 2, "one model per instance"
    assert factory.models[0] is not factory.models[1]

    # Instance 1's conversation really did accumulate a tool result ...
    first_conversation = factory.models[0]._openai_messages
    assert any(message["role"] == "tool" for message in first_conversation)
    assert any(
        "TASK-ONE" in str(message.get("content")) for message in first_conversation
    )

    # ... and none of it reached instance 2. Its FIRST request to the endpoint carried
    # only its own system + task messages: `_seen` was 0 when it began.
    second_request = client.calls[2]
    assert [message["role"] for message in second_request] == ["system", "user"]
    assert second_request[1]["content"] == "TASK-TWO"
    assert not any(
        "TASK-ONE" in str(message.get("content")) for message in second_request
    )


# --------------------------------------------------------------------------------------
# `mint_one` — the Stage-1 tool: one instance, by id, from committed code
# --------------------------------------------------------------------------------------


def _write_registry(path: Path, instance_ids: list[str]) -> Path:
    """A real registry file, written by the real `dump_registry` — never hand-rolled JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_registry([_record(instance_id) for instance_id in instance_ids], path)
    return path


def _mint_one_seams(prepare: object, factory: object) -> dict:
    """The fake seams every `mint_one` test uses: no git, no subprocess, no spend."""
    return {
        "model_factory": factory,
        "prepare": prepare,
        "transport_factory": lambda cmd, env: OkTransport(),
        "discover_tools": lambda cmd: [],
    }


def test_single_instance_entrypoint_is_importable_and_wired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One id in, one bridged capture out — through the SAME path the batch uses.

    `mint_one` is deliberately `mint_batch` over a one-record list, not a bespoke
    single-instance pipeline: Stage 1's whole value was rehearsing the batch path before
    the batch was spent on, and a separate pipeline would rehearse only itself (exactly
    what made the deleted `scratchpad/drive_one.py` worthless).
    """
    server_root = tmp_path / "servers"
    _install_stub_server(server_root)
    registry = _write_registry(
        tmp_path / "registry.json", ["octo__repo-1", "octo__repo-2", "octo__repo-3"]
    )

    cfg = MintConfig(
        root=tmp_path / "mint", registry_path=registry, server_root=server_root
    )
    prepare = StubPrepare()
    factory = SpyModelFactory()

    report = mint_one("octo__repo-2", cfg, **_mint_one_seams(prepare, factory))

    # Only the named instance was prepped, driven, and recorded.
    assert prepare.prepared == ["octo__repo-2"]
    assert factory.calls == 1
    assert report.checkpoint.status("octo__repo-2") == "captured"
    assert report.checkpoint.status("octo__repo-1") is None
    assert report.counts["captured"] == 1
    assert report.counts["failed"] == 0
    assert report.instance_ids == ("octo__repo-2",)

    # The REAL `bridge_capture` ran: the layout the stock `belay phase0 run` resolves.
    assert (cfg.batch_dir / "trace-octo__repo-2.jsonl").is_file()
    assert (cfg.batch_dir / "trace-octo__repo-2.manifests").is_dir()
    assert report.batch_dir == cfg.batch_dir
    assert report.checkpoint_path == cfg.checkpoint_path
    assert cfg.checkpoint_path.is_file()


def test_unknown_instance_id_is_a_named_error_listing_candidates(
    tmp_path: Path,
) -> None:
    """A typo'd id says so; it never mints nothing and calls that a run.

    An empty mint is not a null result — `belay phase0 run` reads it as
    `INSTRUMENT SUSPECT`, i.e. a *fake* PIVOT caused by operator setup.
    """
    server_root = tmp_path / "servers"
    _install_stub_server(server_root)
    registry = _write_registry(tmp_path / "registry.json", ["octo__repo-1", "octo__repo-2"])
    cfg = MintConfig(
        root=tmp_path / "mint", registry_path=registry, server_root=server_root
    )
    prepare = StubPrepare()

    with pytest.raises(UnknownInstanceError) as excinfo:
        mint_one("octo__repo-typo", cfg, **_mint_one_seams(prepare, SpyModelFactory()))

    message = str(excinfo.value)
    assert "octo__repo-typo" in message
    assert "2" in message, "the error must say how many records the registry does hold"
    assert prepare.prepared == [], "nothing may be prepped for an id that does not exist"


def test_missing_registry_file_names_the_instance_pool_aspect(tmp_path: Path) -> None:
    """An absent `--registry` is a named error, not a `FileNotFoundError` traceback.

    `eval/instances/selected.json` is the `instance-pool` aspect's deliverable and may not
    exist yet; the two aspects are order-independent, so this path must be legible.
    """
    server_root = tmp_path / "servers"
    _install_stub_server(server_root)
    cfg = MintConfig(
        root=tmp_path / "mint",
        registry_path=tmp_path / "nope" / "selected.json",
        server_root=server_root,
    )

    with pytest.raises(RegistryNotFoundError) as excinfo:
        mint_one(
            "octo__repo-1", cfg, **_mint_one_seams(StubPrepare(), SpyModelFactory())
        )

    message = str(excinfo.value)
    assert "selected.json" in message
    assert "instance-pool" in message


def test_verify_command_is_printed_with_the_workspace_placeholder(
    tmp_path: Path,
) -> None:
    """The reproduce-the-number command uses `{workspace}`, and takes no `--` separator.

    One static `--server` command verifies a heterogeneous batch: replay substitutes each
    trace's OWN recorded `source_root` for the placeholder, which is strictly more correct
    than restating a root the trace already carries. And `--server` is `nargs=REMAINDER`,
    so a `--` separator would be passed to `node`, not consumed by argparse.
    """
    from belay.replay.engine import WORKSPACE_PLACEHOLDER as ENGINE_PLACEHOLDER

    # `eval/` may not import `belay`, so the literal is restated — pinned here so the two
    # can never drift apart silently.
    assert WORKSPACE_PLACEHOLDER == ENGINE_PLACEHOLDER

    server_root = tmp_path / "servers"
    entrypoint = _install_stub_server(server_root)
    registry = _write_registry(tmp_path / "registry.json", ["octo__repo-1"])
    cfg = MintConfig(
        root=tmp_path / "mint", registry_path=registry, server_root=server_root
    )

    report = mint_one(
        "octo__repo-1", cfg, **_mint_one_seams(StubPrepare(), SpyModelFactory())
    )

    command = report.verify_command
    assert "belay phase0 run" in command
    assert str(cfg.batch_dir) in command
    assert WORKSPACE_PLACEHOLDER in command
    assert str(entrypoint.resolve()) in command
    assert " -- " not in command, "--server is nargs=REMAINDER; a separator would reach node"
    # The report renders the command it carries — the printed line IS the artifact.
    assert command in report.render()
