# Verbatim from corpus case `trace-pallets__flask-4992-turn14`: `tests/test_config.py` at
# the TASK pre-state, excerpted to turn 14's `oldText` region plus the
# `common_object_test` helper it calls. The `oldText` reproduces `test_config_from_file`
# byte-identically, which is what makes turn 14 a TRUE APPEND rather than a rewrite.

import json
import os

import flask


def common_object_test(app):
    assert app.secret_key == "config"
    assert app.config["TEST_KEY"] == "foo"
    assert "TestConfig" not in app.config


def test_config_from_file():
    app = flask.Flask(__name__)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    app.config.from_file(os.path.join(current_dir, "static", "config.json"), json.load)
    common_object_test(app)
