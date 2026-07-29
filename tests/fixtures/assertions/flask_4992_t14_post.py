# Verbatim from corpus case `trace-pallets__flask-4992-turn14`: the same excerpt of
# `tests/test_config.py` AFTER turn 14's `edit_file`. The turn's `newText` re-emits
# `test_config_from_file` BYTE-IDENTICALLY and appends `test_config_from_file_toml` below
# it — a true append. The appended function carries two genuinely new bare `assert`
# statements, inside the nested `load_toml` / `load_binary` helpers; both are additions.
#
# DO NOT REFORMAT. The trailing whitespace and the blank-line spacing are the agent's, and
# `newText` is reproduced here character for character.

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

def test_config_from_file_toml():
    app = flask.Flask(__name__)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # We will just write a mock for tomllib.load that takes a binary file
    def load_toml(f):
        assert f.read(1) == b"{"
        return json.loads("{" + f.read().decode("utf-8"))
        
    # We can just test with the same config.json but in binary mode
    app.config.from_file(
        os.path.join(current_dir, "static", "config.json"), 
        load=json.load, 
    ) # default mode is 'r'

    app.config.clear()
    
    # Let's mock a load function that expects binary
    def load_binary(f):
        data = f.read()
        assert isinstance(data, bytes)
        return json.loads(data.decode("utf-8"))
        
    app.config.from_file(
        os.path.join(current_dir, "static", "config.json"), 
        load=load_binary,
        mode="rb"
    )
    common_object_test(app)
