"""A8: the verify layer consults NO model — the positioning, made a test with teeth.

This is the answer to the one question every reviewer asks: *"isn't this just an
LLM judge with extra steps?"* Belay's entire wedge is that its verdict is grounded
in **re-execution and diffing**, never in a model's opinion of itself — the C4
verdict is A2 replay-equivalence and effect-conformance, decided by running the
recorded tool call again and comparing state. A single stray `import openai` inside
`src/belay/verify/` would quietly turn the verdict into exactly the thing the project
exists to replace, and every other test would stay green while it did.

So this walks every module under `src/belay/verify/` AND `src/belay/corpus/` with `ast`
— never importing them, for the same reason `test_import_guard` does not: importing runs side effects and
reports on the venv rather than on the source that ships — and asserts that none of
them imports an inference client (a model SDK, a local-inference runtime, or an
LLM-orchestration framework), and that none reaches for a first-party module whose
name is inference-shaped (`belay.llm`, `belay.judge`, …). A docstring may *say*
"model" all it likes — and several do, precisely to state that no model is consulted
— because `ast` reads imports, not prose.

**The teeth are verified by hand, not asserted here.** The task that added this file
planted `import openai` in `src/belay/verify/turn.py`, ran this test, and watched it
FAIL naming that line, then reverted — because a guard nobody has watched fail is a
guard that might be passing vacuously. The non-vacuity control below (`_modules`
must find files, and the guard must actually see the imports those files do make)
keeps it from silently scanning nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "belay"
#: The layers whose verdict/measurement must be grounded in re-execution and diffing,
#: never a model: `verify/` (the A1/A2 verdict) AND `corpus/` (C6 — it stores and scores
#: those verdicts, and an inference client there would smuggle a judge into the metric or
#: a re-labeler into the corpus). Both are walked by the same guard.
GUARDED_ROOTS = (SRC / "verify", SRC / "corpus")

#: Third-party inference clients: hosted model SDKs, local-inference runtimes, and
#: LLM-orchestration frameworks. None of these may enter the verdict path. The set is
#: deliberately broad — a verdict grounded in re-execution needs none of them, so the
#: cost of an over-broad ban is zero and the cost of a missed one is the whole thesis.
_INFERENCE_CLIENTS = frozenset(
    {
        "openai",
        "anthropic",
        "cohere",
        "mistralai",
        "groq",
        "together",
        "replicate",
        "litellm",
        "google",  # google.generativeai / vertexai
        "vertexai",
        "boto3",  # bedrock is reached this way; verify has no business calling AWS
        "llama_cpp",
        "ctransformers",
        "ollama",
        "vllm",
        "transformers",
        "sentence_transformers",
        "torch",
        "tensorflow",
        "jax",
        "huggingface_hub",
        "langchain",
        "langchain_core",
        "langchain_openai",
        "llama_index",
        "guidance",
        "dspy",
        "instructor",
        "outlines",
    }
)

#: First-party module-name fragments that would smuggle inference in under the belay
#: namespace. A `belay.judge` or `belay.llm` imported into the verdict path is the same
#: failure wearing a first-party coat, so it is banned by the same guard.
_INFERENCE_FIRST_PARTY = frozenset(
    {"llm", "judge", "model", "models", "inference", "completion", "prompt", "prompts"}
)


def _modules() -> list[Path]:
    files = sorted(p for root in GUARDED_ROOTS for p in root.rglob("*.py"))
    assert files, f"no modules found under {GUARDED_ROOTS} — this guard would pass vacuously"
    return files


def _imported_names(path: Path) -> list[tuple[str, int]]:
    """Every module name `path` imports (dotted, full), with the line it appears on.

    `ast.walk` so an import nested inside a function counts too — a guard that only
    read the top of the file would be sidestepped by indenting one line. Both
    `import a.b` and `from a.b import c` are captured, dotted so a first-party
    `belay.judge` is distinguishable from the package root.
    """
    tree = ast.parse(path.read_bytes(), filename=str(path))
    names: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                names.append((node.module, node.lineno))
    return names


def _is_inference_import(dotted: str) -> bool:
    root = dotted.split(".")[0]
    if root in _INFERENCE_CLIENTS:
        return True
    if root == "belay":
        parts = set(dotted.split("."))
        return bool(parts & _INFERENCE_FIRST_PARTY)
    return False


def test_no_module_in_the_verify_layer_imports_an_inference_client() -> None:
    """The verdict path imports no model SDK, no inference runtime, no LLM framework.

    THE positioning, in code. A2's PASS/FAIL is re-execution and a state diff; if any
    verify module imported an inference client, the verdict would be — at least in
    part — a model's opinion, which is the "up-to-35%-false-positive LLM-as-judge" this
    project refuses to be. Watched FAIL against a planted `import openai` in turn.py
    before it was reverted, so this has teeth rather than passing by luck.
    """
    offenders = [
        f"{path.relative_to(SRC)}:{lineno} imports {dotted!r}"
        for path in _modules()
        for dotted, lineno in _imported_names(path)
        if _is_inference_import(dotted)
    ]
    assert not offenders, (
        "an inference client is imported inside src/belay/verify or src/belay/corpus:\n  "
        + "\n  ".join(offenders)
        + "\n\nWHY THIS IS A FAILURE: Belay's verdict is grounded in RE-EXECUTION and a"
        " state diff — it replays the recorded tool call and compares observed state to"
        " what was claimed. No model is consulted, and that is the entire answer to"
        " \"isn't this an LLM judge with extra steps?\". A model SDK in the verdict path"
        " turns the grounded verdict into a judge's guess — the up-to-35%-false-positive"
        " failure mode the project exists to replace. If verification ever legitimately"
        " needs a model (A3 claim re-derivation, C8), it does so where EXECUTION still"
        " decides the verdict, behind `--no-claim-axis`, and this guard is updated as a"
        " deliberate, visible decision — never sidestepped."
    )


def test_the_guard_actually_sees_the_imports_the_layer_makes() -> None:
    """Non-vacuity: the AST walk really is reading imports out of these files.

    A guard that parsed nothing, or whose `_imported_names` silently returned empty,
    would pass the ban above no matter what the code imported. This pins that the walk
    observes the real, mundane imports the verify layer legitimately makes (its own
    `belay.replay` re-execution machinery), so the ban is scanning something.
    """
    seen = {
        dotted for path in _modules() for dotted, _lineno in _imported_names(path)
    }
    # verify composes C3's re-execution; if the walk sees this, it is really reading imports.
    assert any(name.startswith("belay.replay") for name in seen), seen
    # And corpus/ is genuinely in scope: it imports its own case/verify machinery, so seeing
    # a belay.corpus import proves the guard walks corpus/, not just verify/.
    assert any(name.startswith("belay.corpus") for name in seen), seen
