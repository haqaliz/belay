"""The launch gif's CLAIMS are machine-checked, the way the install block's are.

Aspect `demo-gif-assets` (A3 of `launch-demo`, L7). The gif is the first thing a visitor
sees, and its alt text is a claim about a verdict — which is exactly the class of thing
this repo refuses to leave to review. The claim it replaced was wrong in both available
directions: it described a two-turn synthetic trace ("Turn 1's write … the A1 invariant
FAILs … a corrupt success caught") while the roadmap simultaneously said "turn 7", and the
COMMITTED capture has neither — it is the negative control, every turn PASS.

So the guard here is narrow and one-directional: **the README must not assert a FAIL, a
flag turn, or a caught cheat for the demo**, because `tests/test_demo_capture.py` asserts
by re-execution that the committed capture contains none. That module owns the verdict;
this one owns the agreement between the verdict and the front door. If the demo is ever
re-cut onto a capture that DOES fail, this test is the thing that has to be rewritten
deliberately — which is the point.

It also pins the reproduction path: an asset the docs say is regenerable by a script that
does not exist is a dead claim, and dead claims are how a record rots.

Deterministic string/parse checks on committed files. No browser, no network, no clock —
recording the gif is manual by design and never runs here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GIF = REPO_ROOT / "assets" / "belay-demo.gif"
GENERATOR = REPO_ROOT / "console" / "scripts" / "record-demo-gif.mjs"

#: Phrases that would assert the demo caught something. Each is the shape of a claim the
#: capture cannot support, not merely a word: "FAIL" alone appears legitimately in the
#: README's verdict vocabulary, and banning it would make the honest docs unwritable.
_CAUGHT_CLAIMS = (
    "invariant fails",
    "reduces to fail",
    "corrupt success caught",
    "flags turn",
    "belay flags",
    "weakens the test",
)


def _demo_img_tag() -> str:
    """The README's `<img>` tag for the demo gif, alt text included."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"<img[^>]*belay-demo\.gif[^>]*>", readme, re.DOTALL)
    assert match is not None, "the README no longer embeds assets/belay-demo.gif"
    return match.group(0)


def test_the_committed_gif_exists_and_is_a_gif() -> None:
    assert GIF.exists(), f"{GIF} is missing — the README embeds it"
    assert GIF.read_bytes()[:6] in (b"GIF87a", b"GIF89a"), "not a GIF by magic bytes"


def test_the_gif_is_regenerable_by_the_script_the_docs_name() -> None:
    """`npm run record:demo` must resolve to a file that exists."""
    package = json.loads((REPO_ROOT / "console" / "package.json").read_text(encoding="utf-8"))
    script = package.get("scripts", {}).get("record:demo")
    assert script is not None, "console/package.json lost the record:demo script"
    assert GENERATOR.name in script, f"record:demo no longer runs {GENERATOR.name}: {script!r}"
    assert GENERATOR.exists(), f"{GENERATOR} is missing — the docs claim the gif is regenerable"


@pytest.mark.parametrize("claim", _CAUGHT_CLAIMS)
def test_the_readme_demo_claims_nothing_the_capture_does_not_contain(claim: str) -> None:
    """The alt text may not assert a catch: the committed capture is all-PASS.

    `tests/test_demo_capture.py` is the authority on that verdict; this asserts the front
    door agrees with it.
    """
    assert claim not in _demo_img_tag().lower(), (
        f"the README's demo image claims {claim!r}, but the committed capture is the "
        "negative control — every turn PASS, no flag turn (tests/test_demo_capture.py)"
    )


def test_the_readme_demo_alt_carries_the_coverage_boundary() -> None:
    """A PASS shown without its coverage line is the failure mode NOT_COVERED creates."""
    alt = _demo_img_tag().lower()
    assert "not_covered" in alt, "the demo alt text dropped the coverage boundary"
    assert "network" in alt, "the demo alt text no longer names the uncovered dimension"
