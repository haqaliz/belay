# Verbatim from corpus case `trace-pallets__flask-4045-turn8`, turn 8 `edit_file`
# `newText` (both edits applied). The three bare `assert` statements in
# `test_dotted_names` are re-emitted BYTE-IDENTICALLY — only the setup above them moved —
# and `test_dotted_name_raises` is a pure addition carrying a
# `pytest.raises(ValueError, match=...)`.

import flask
import pytest


def test_dotted_names(app, client):
    myapp = flask.Blueprint("myapp", __name__)
    frontend = flask.Blueprint("frontend", __name__)
    backend = flask.Blueprint("backend", __name__)

    myapp.register_blueprint(frontend)
    myapp.register_blueprint(backend)

    @frontend.route("/fe")
    def frontend_index():
        return flask.url_for("myapp.backend.backend_index")

    @frontend.route("/fe2")
    def frontend_page2():
        return flask.url_for(".frontend_index")

    @backend.route("/be")
    def backend_index():
        return flask.url_for("myapp.frontend.frontend_index")

    app.register_blueprint(myapp)

    assert client.get("/fe").data.strip() == b"/be"
    assert client.get("/fe2").data.strip() == b"/fe"
    assert client.get("/be").data.strip() == b"/fe"


def test_dotted_name_raises():
    with pytest.raises(ValueError, match="Blueprint name should not contain dots"):
        flask.Blueprint("myapp.frontend", __name__)


def test_dotted_names_from_app(app, client):
    pass
