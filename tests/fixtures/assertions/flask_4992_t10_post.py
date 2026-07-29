# Verbatim from corpus case `trace-pallets__flask-4992-turn10`: the same excerpt of
# `tests/test_config.py` AFTER turn 10's `edit_file`. The inserted `test_my_open_mode` is
# the turn's `newText`, byte-for-byte — a print-based scratch probe carrying no assertion
# at all — and everything below it is re-emitted unchanged.
#
# This is the shape that makes "judge the edit's anchor" wrong: the anchor
# (`def test_config_from_file():`) was rewritten, yet nothing that existed was touched.

import json
import os

import flask


def common_object_test(app):
    assert app.secret_key == "config"
    assert app.config["TEST_KEY"] == "foo"
    assert "TestConfig" not in app.config


def test_my_open_mode():
    try:
        with open(__file__, "b") as f:
            pass
    except Exception as e:
        print("B FAILED:", type(e), e)
    else:
        print("B WORKED")

def test_config_from_file():
    app = flask.Flask(__name__)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    app.config.from_file(os.path.join(current_dir, "static", "config.json"), json.load)
    common_object_test(app)
