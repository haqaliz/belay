# Verbatim from corpus case `trace-pallets__flask-4992-turn19`, turn 19 `edit_file`
# `newText` on `tests/test_config.py`. Kept for ONE reason: `common_object_test(app)` is a
# real project helper that really does assert, and this module deliberately does NOT
# recognise it (PRD M4 — a helper-name allowlist fitted to these cases is the overfitting
# the unit exists to avoid). So this fixture must extract ZERO assertions.

import json
import os

import flask


def test_config_from_file():
    app = flask.Flask(__name__)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    app.config.from_file(os.path.join(current_dir, "static", "config.json"), json.load)
    common_object_test(app)


def test_config_from_file_toml():
    app = flask.Flask(__name__)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    import tomli

    app.config.from_file(
        os.path.join(current_dir, "static", "config.toml"), tomli.load, text=False
    )
    common_object_test(app)
