# Instance curation — Phase-0 minting-driver smoke target

The single-instance smoke (`eval/README.md`, `tests/test_minting_driver_smoke.py`, Task
5) needs one concrete SWE-bench-lite instance that is:

- **macOS-runnable, Docker-free** — pure Python, no C-extension build step, no system
  service dependency (database, browser, native library) to reproduce the failing test.
- **A minimal, single-file source edit** — small enough that a short natural-language task
  string is enough to point a model at the fix, and small enough that a human can audit
  the resulting trace quickly.

## Selected instance: `pallets__flask-4045`

Verified against the real `princeton-nlp/SWE-bench_Lite` dataset (HuggingFace
datasets-server, `search` endpoint filtered on `repo: pallets/flask`, checked
2026-07-21) — this is a real instance in the Lite split, not a guess.

| Field | Value |
|---|---|
| **instance_id** | `pallets__flask-4045` |
| **repo** | `pallets/flask` |
| **base_commit** | `d8c37f43724cd9fb0870f77877b7c4c7e38a19e0` |

**Why this one:** Flask is pure Python with lightweight, pure-Python dependencies
(Werkzeug, Jinja2, Click, itsdangerous — `pip install flask` on macOS needs no compiler
and no system package). The real fix is a small, self-contained edit to a single source
file, `src/flask/blueprints.py`: add a guard in `Blueprint.__init__` (and in
`add_url_rule`) that raises `ValueError` when a blueprint name/endpoint/view-function name
contains a dot. No test framework setup, no server process, no network access, no Docker
needed to reproduce or verify the change locally — exactly the profile a one-file-edit
smoke needs.

The upstream problem statement: *"Raise error when blueprint name contains a dot. This is
required since every dot is now significant since blueprints can be nested. An error was
already added for endpoint names in 1.0, but should have been added for this as well."*

The real upstream patch (for reference — the smoke does not need to reproduce this
exactly, only to exercise real file/shell tool calls through the MCP boundary):

```diff
--- a/src/flask/blueprints.py
+++ b/src/flask/blueprints.py
@@ -188,6 +188,10 @@ def __init__(
             template_folder=template_folder,
             root_path=root_path,
         )
+
+        if "." in name:
+            raise ValueError("'name' may not contain a dot '.' character.")
+
         self.name = name
```

### Task string to hand the model

```
You are working in a local checkout of the Flask repository (pallets/flask), at commit
d8c37f43724cd9fb0870f77877b7c4c7e38a19e0.

Blueprint names are not allowed to contain a dot ('.') character, because every dot is
now significant for nested blueprints. Currently `Blueprint.__init__` in
src/flask/blueprints.py does not check for this.

Edit src/flask/blueprints.py so that Blueprint.__init__ raises a ValueError with the
message "'name' may not contain a dot '.' character." if the given `name` argument
contains a dot. Add the check right after the call to the parent class's __init__ and
before `self.name = name` is assigned.

Use the available file tools to read the file, make the edit, and confirm the change is
present in the file's contents afterward.
```

This is deliberately scoped to **one file, one guard clause** — enough to force at least
one real `edit_file`/`write_file` MCP tool call (feeding a real trace turn) without
requiring the model to run the Flask test suite or manage a virtualenv. If a shell-server
turn is also wanted for the smoke (to exercise `run_process` and the A1 invariant path
rather than only the filesystem server's A2 annotation path), extend the task string with
an explicit instruction to run `python -c "import ast; ast.parse(open('src/flask/blueprints.py').read())"`
(or an equivalent syntax check) via the shell tool after editing, to confirm the file
still parses.

## Fallback selection criteria (if this instance turns out unusable)

Should `pallets__flask-4045` prove unworkable in practice (e.g. the base commit doesn't
check out cleanly, or `pip install` pulls in something that needs network access this
particular sandbox blocks), re-select using these criteria, in order:

1. **Pure-Python repo** among the SWE-bench-lite repo set — confirmed present via the
   dataset: `astropy/astropy`, `django/django`, `matplotlib/matplotlib`,
   `mwaskom/seaborn`, `pallets/flask`, `psf/requests`, `pydata/xarray`,
   `pylint-dev/pylint`, `pytest-dev/pytest`, `scikit-learn/scikit-learn`,
   `sphinx-doc/sphinx`, `sympy/sympy`. Prefer `pallets/flask`, `psf/requests`, or
   `pylint-dev/pylint` over `scikit-learn`/`matplotlib`/`astropy` — the latter three pull
   in C-extension-heavy dependencies (NumPy/SciPy/compiled extensions) that are more
   likely to need a working compiler toolchain on a fresh macOS machine.
2. **A patch touching exactly one non-test source file**, ideally under 15 changed lines
   — inspect the instance's `patch` field for file count and diff size before picking.
2. **No Docker/system-service dependency** — the instance's failing test must not require
   a database, browser, or other external service to reproduce.
3. **A short, literal problem statement** that translates directly into an imperative
   task string, without requiring the model to infer intent from a long discussion thread.

Other verified-present `pallets/flask` instances if a second candidate is wanted:
`pallets__flask-4992`, `pallets__flask-5063`. Verified-present `pylint-dev/pylint`
instances (repo pulls in more transitive dependencies than Flask, so treat as a second
choice): `pylint-dev__pylint-6506`, `pylint-dev__pylint-5859`,
`pylint-dev__pylint-7993`, `pylint-dev__pylint-7114`, `pylint-dev__pylint-7228`,
`pylint-dev__pylint-7080`. These were confirmed present in the dataset during this same
lookup but not inspected in the same depth as `pallets__flask-4045` — re-verify the
patch shape before using one of these as the actual smoke target.
