# Assertion-extraction fixtures — real content, copied out of the audited captures

Every `.py` file here is **verbatim test source from a real mint capture**, not a
hand-written illustration. The bodies were lifted out of the `oldText` / `newText` of the
recorded `edit_file` `tools/call` in
`corpus/local/<case>/trace.jsonl` (and, for `pytest_5227_*`, out of the `read_text_file`
reply in `eval/mint/s2/batch/trace-pytest-dev__pytest-5227.jsonl`). The captures
themselves are gitignored, ~5.5 GB, and **not movable** — these snippets are the part
that can be checked in, so the unit tests remain reproducible on any machine.

Only two things were added: the minimal enclosing scaffold needed to make the snippet a
parseable module (a `class TestFixme(CheckerTestCase):` header, an import line), and a
provenance comment naming the case and turn. **Assertion text is byte-identical to the
capture.** If you "tidy" a trailing comma or a quote style here, you have deleted the
evidence — `pylint_5859_t6_*` exists precisely because a trailing comma is what the
audit's closest call turned on.

These files are **data, not code**. Nothing imports or executes them — the tests read
their bytes and hand them to `belay.verify.assertions.extract`. `pyproject.toml` therefore
excludes this directory from `ruff`: an unused import or an undefined helper name in here
is a fact about the captured agent run, and `ruff --fix` would quietly rewrite the
evidence.

| Fixture | Case · turn | What it is evidence of |
|---|---|---|
| `pylint_5859_t6_pre.py` / `_post.py` | `pylint-5859` t6 | the trailing comma that a line-diff reports as a removal (A2) |
| `pylint_5859_t11_pre.py` / `_post.py` | `pylint-5859` t11 | a true append — `assertNoMessages()` re-emitted byte-identically, a whole new test method below it |
| `pytest_5227_t8_pre.py` / `_post.py` | `pytest-5227` t8 | the REQUIRED expectation update — same `assert`, new expected string. Wrongness is not weakness, and this is the control that says so |
| `pytest_5227_t11_pre.py` / `_post.py` | `pytest-5227` t11 **and t13** | the only real weakening in existence — `fnmatch_lines` glob patterns (A4). The post file carries both turns' edits |
| `flask_4045_t8_pre.py` / `_post.py` | `flask-4045` t8 | bare `assert`, and `pytest.raises(..., match=...)` |
| `flask_4992_t10_pre.py` / `_post.py` | `flask-4992` t10 | audit shape B — an anchored insert-before, where the edit's anchor is a pre-existing test |
| `flask_4992_t12_pre.py` / `_post.py` | `flask-4992` t12 | audit shape C — the run editing its own scratch test; `pytest.fail(...)`. The `_pre` file is empty of functions **on purpose**: the region had no predecessor at turn 0 |
| `flask_4992_t14_pre.py` / `_post.py` | `flask-4992` t14 | a true append — the `oldText` region re-emitted byte-identically |
| `flask_4992_t19_pre.py` / `_post.py` | `flask-4992` t19 | shapes B and C together, plus `common_object_test(...)` — the helper deliberately NOT recognised |

**On excerpting.** Each `_pre` / `_post` pair covers the *same* region of the *same* file:
the file as it stood at the task pre-state, and as it stood after the turn. Where a pair
includes `common_object_test`, it is included on **both** sides; where it is omitted, it is
omitted from both. The helper is byte-identical across every one of these turns, so
including it can only add three assertions that pair as equal — it changes what the
comparison has to chew on, never what it decides.
