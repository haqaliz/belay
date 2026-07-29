# Verbatim from corpus case `trace-pallets__flask-4992-turn10`: `tests/test_config.py` at
# the TASK pre-state, as returned by the run's own `read_text_file` reply, excerpted to
# the edited region plus the `common_object_test` helper the region calls.
#
# Turn 10's `oldText` is the single line `def test_config_from_file():` and its `newText`
# inserts a whole scratch test ABOVE it — audit shape B, an anchored insert-before. The
# helper's three bare `assert` statements are unchanged across the turn, so they are the
# pair that must compare EQUAL; whether the excerpt includes them cannot change the
# verdict, only whether the comparison has anything to chew on.

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
