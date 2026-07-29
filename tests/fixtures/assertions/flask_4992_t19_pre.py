# Verbatim from corpus case `trace-pallets__flask-4992-turn19`: `tests/test_config.py` at
# the TASK pre-state, excerpted to the region turn 19's `oldText` covers.
#
# That `oldText` is `test_my_open_mode` FOLLOWED BY `test_config_from_file`, and turn 19
# replaces the pair with two real tests — so the run's own scratch test disappears. At the
# task pre-state only `test_config_from_file` existed, so the vanished `pytest.fail(...)`
# calls were never in the pre set and cannot have been removed from it. That is the whole
# fixture: shape C, judged against turn 0.
#
# `common_object_test` is deliberately NOT included, matching `flask_4992_t19_post.py`,
# which must extract zero assertions. It is unchanged across the turn either way.

import json
import os

import flask


def test_config_from_file():
    app = flask.Flask(__name__)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    app.config.from_file(os.path.join(current_dir, "static", "config.json"), json.load)
    common_object_test(app)
