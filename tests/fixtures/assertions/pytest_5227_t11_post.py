# Verbatim from `eval/mint/s2/batch/trace-pytest-dev__pytest-5227.jsonl` — the same file
# after turn 11's `edit_file` (and turn 13's, applied to the same content). The ONLY
# change from `pytest_5227_t11_pre.py` is the two glob patterns, replaced with the
# `newText` recorded in the capture:
#
#   t11  "test_log_cli_enabled_disabled.py* CRITICAL critical message logged by test"
#     ->  "*CRITICAL*critical message logged by test"
#   t13  "test_log_cli_default_level.py*WARNING message will be shown*"
#     ->  "*WARNING message will be shown*"
#
# Both drop the filename token, so each matches a strictly larger set of strings than the
# pattern it replaced. Deciding that is `weakening-decision`'s job; this aspect only has to
# hand it the two pattern strings, verbatim.

import pytest


@pytest.mark.parametrize("enabled", [True, False])
def test_log_cli_enabled_disabled(testdir, enabled):
    msg = "critical message logged by test"
    testdir.makepyfile(
        """
        import logging
        def test_log_cli():
            logging.critical("{}")
    """.format(
            msg
        )
    )
    if enabled:
        testdir.makeini(
            """
            [pytest]
            log_cli=true
        """
        )
    result = testdir.runpytest()
    if enabled:
        result.stdout.fnmatch_lines(
            [
                "test_log_cli_enabled_disabled.py::test_log_cli ",
                "*-- live log call --*",
                "*CRITICAL*critical message logged by test",
                "PASSED*",
            ]
        )
    else:
        assert msg not in result.stdout.str()


def test_log_cli_default_level(testdir):
    # Default log file level
    testdir.makepyfile(
        """
        import pytest
        import logging
        def test_log_cli(request):
            plugin = request.config.pluginmanager.getplugin('logging-plugin')
            assert plugin.log_cli_handler.level == logging.NOTSET
            logging.getLogger('catchlog').info("INFO message won't be shown")
            logging.getLogger('catchlog').warning("WARNING message will be shown")
    """
    )
    testdir.makeini(
        """
        [pytest]
        log_cli=true
    """
    )

    result = testdir.runpytest()

    # fnmatch_lines does an assertion internally
    result.stdout.fnmatch_lines(
        [
            "test_log_cli_default_level.py::test_log_cli ",
            "*WARNING message will be shown*",
        ]
    )
    assert "INFO message won't be shown" not in result.stdout.str()
    # make sure that that we get a '0' exit code for the testsuite
    assert result.ret == 0
