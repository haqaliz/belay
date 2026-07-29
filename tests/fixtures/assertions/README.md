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

| Fixture | Case · turn | What it is evidence of |
|---|---|---|
| `pylint_5859_t6_pre.py` / `_post.py` | `pylint-5859` t6 | the trailing comma that a line-diff reports as a removal (A2) |
| `pytest_5227_t11_pre.py` / `_post.py` | `pytest-5227` t11 | the only real weakening in existence — `fnmatch_lines` glob patterns (A4) |
| `flask_4045_t8_pre.py` / `_post.py` | `flask-4045` t8 | bare `assert`, and `pytest.raises(..., match=...)` |
| `flask_4992_t12_post.py` | `flask-4992` t12 | `pytest.fail(...)` |
| `flask_4992_t19_post.py` | `flask-4992` t19 | `common_object_test(...)` — the helper deliberately NOT recognised |
