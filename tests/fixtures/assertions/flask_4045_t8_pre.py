# Verbatim from corpus case `trace-pallets__flask-4045-turn8`, turn 8 `edit_file`
# `oldText` on `tests/test_blueprints.py`. This is the corpus's only MULTI-EDIT call:
# edit[0] rewrites this function's body, edit[1] inserts a whole new test above
# `test_dotted_names_from_app`. Three bare `assert` statements here; the post version
# re-emits all three byte-identically.

import flask
import pytest


def test_dotted_names(app, client):
    frontend = flask.Blueprint("myapp.frontend", __name__)
    backend = flask.Blueprint("myapp.backend", __name__)

    @frontend.route("/fe")
    def frontend_index():
        return flask.url_for("myapp.backend.backend_index")

    @frontend.route("/fe2")
    def frontend_page2():
        return flask.url_for(".frontend_index")

    @backend.route("/be")
    def backend_index():
        return flask.url_for("myapp.frontend.frontend_index")

    app.register_blueprint(frontend)
    app.register_blueprint(backend)

    assert client.get("/fe").data.strip() == b"/be"
    assert client.get("/fe2").data.strip() == b"/fe"
    assert client.get("/be").data.strip() == b"/fe"


def test_dotted_names_from_app(app, client):
    pass
